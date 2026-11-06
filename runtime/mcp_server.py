"""MCP server mode for MCO — exposes tools over stdio MCP protocol.

Start with: mco serve
Configure in MCP client: {"command": "mco", "args": ["serve"]}
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Envelope helpers ──

def _ok(data: Any) -> Dict[str, Any]:
    """Wrap a successful result in the standard envelope."""
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    """Wrap an error in the standard envelope."""
    return {"ok": False, "error": {"code": code, "message": message}}


# ── Progress bridge ──

class _ProgressBridge:
    """Forward runtime invocation events to MCP progress notifications.

    A long broker run looks like a hang to the host: the tool call sits silent
    for the whole run, so a client that caps request duration cancels it and the
    provider cost is spent without producing an answer. MCP hosts reset their
    request timeout whenever a progress notification arrives, so emitting
    heartbeats keeps an honest long run alive.

    Invoked from provider worker threads, so every notification is scheduled
    back onto the server event loop. A failure disables the bridge rather than
    breaking the run: a host that sent no progressToken simply gets no
    notifications.
    """

    def __init__(self, ctx: Any, loop: Any, total: int, min_interval_seconds: float = 5.0) -> None:
        self._ctx = ctx
        self._loop = loop
        self._total = max(1, total)
        self._min_interval = min_interval_seconds
        self._done = 0
        # None, not 0.0: time.monotonic() has an arbitrary epoch, so comparing
        # against 0.0 throttles away the first heartbeat on a machine whose
        # monotonic clock is younger than the interval.
        self._last_emit: Optional[float] = None
        self._disabled = False

    def __call__(self, event: Dict[str, Any]) -> None:
        if self._disabled:
            return
        import time

        event_type = str(event.get("type", ""))
        provider = str(event.get("provider", "") or "")
        if event_type == "invocation_finished":
            self._done += 1
        elif event_type == "output_delta":
            now = time.monotonic()
            if self._last_emit is not None and now - self._last_emit < self._min_interval:
                return
            self._last_emit = now
        elif event_type not in ("invocation_started", "task_finished"):
            return
        self._emit(self._done, self._describe(event_type, provider, event))

    @staticmethod
    def _describe(event_type: str, provider: str, event: Dict[str, Any]) -> str:
        if event_type == "invocation_started":
            return "{}: started".format(provider or "provider")
        if event_type == "output_delta":
            return "{}: working".format(provider or "provider")
        if event_type == "invocation_finished":
            return "{}: {}".format(provider or "provider", event.get("status", "finished"))
        return "run {}".format(event.get("status", "finished"))

    def _emit(self, progress: int, message: str) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ctx.report_progress(
                    progress=float(progress), total=float(self._total), message=message,
                ),
                self._loop,
            )
        except Exception:
            self._disabled = True
            return
        future.add_done_callback(self._check)

    def _check(self, future: Any) -> None:
        if future.cancelled() or future.exception() is not None:
            self._disabled = True


def _progress_callback(ctx: Any, providers: str) -> Optional[_ProgressBridge]:
    """Build a progress bridge when the host supports it, else None."""
    if ctx is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    total = len([item for item in providers.split(",") if item.strip()]) or 1
    return _ProgressBridge(ctx, loop, total)


# ── Validation helpers ──

def _is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True, check=False, cwd=str(path),
    )
    return result.returncode == 0


def _validate_repo(repo: str, require_git: bool = False) -> Optional[Dict[str, Any]]:
    """Validate repo path. Returns error envelope or None if valid."""
    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return _err("invalid_repo", "Repository path does not exist: {}".format(repo))
    if require_git and not _is_git_repo(repo_path):
        return _err("invalid_repo", "Not a git repository: {}".format(repo))
    return None


def _resolve_provider_selection(providers_csv: str) -> tuple[List[str], Optional[Dict[str, Any]]]:
    """Validate an explicit built-in provider selection without dropping entries."""
    from .cli import SUPPORTED_PROVIDER_LIST, SUPPORTED_PROVIDERS

    providers = [provider.strip() for provider in providers_csv.split(",") if provider.strip()]
    if not providers:
        return [], _err(
            "provider_selection_required",
            "Ask the user which agents MCO should use, then provide one or more of: {}".format(
                SUPPORTED_PROVIDER_LIST,
            ),
        )
    invalid = [provider for provider in providers if provider not in SUPPORTED_PROVIDERS]
    if invalid:
        return [], _err("invalid_providers", "Unknown providers: {}".format(", ".join(invalid)))
    return providers, None


def _override_or(override: Any, fallback: int) -> int:
    """Accept a positive per-call timeout override, else keep the policy value."""
    if isinstance(override, bool) or not isinstance(override, int) or override <= 0:
        return fallback
    return override


def _resolve_policy(repo_root: str) -> "Any":
    """Resolve the effective review policy for an MCP call.

    The CLI merges global (~/.mco/config.json) and project (.mcorc.json/.yaml)
    config into its policy; the MCP path ignored both and silently fell back to
    the hardcoded dataclass defaults. That made configured timeouts invisible to
    every MCP tool and left runs without a global deadline.

    Mirrors the CLI's timeout merge, including registered-agent `timeout`
    entries, so the same config produces the same deadlines on both paths.
    """
    import sys

    from .config import ReviewPolicy, load_config_files

    default = ReviewPolicy()
    try:
        file_config = load_config_files(repo_root)
    except Exception as exc:
        # A broken config must not take the broker down, but it must not look
        # like an intentional default either.
        print("[mco] warning: falling back to default policy: {}".format(exc), file=sys.stderr)
        return default
    if not isinstance(file_config, dict):
        return default
    raw = file_config.get("policy")
    if not isinstance(raw, dict):
        raw = {}

    def _positive_int(key: str, fallback: int) -> int:
        value = raw.get(key, fallback)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return fallback
        return value

    def _valid_timeout(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    provider_timeouts = dict(default.provider_timeouts)
    configured_timeouts = raw.get("provider_timeouts")
    if isinstance(configured_timeouts, dict):
        for provider, seconds in configured_timeouts.items():
            if _valid_timeout(seconds):
                provider_timeouts[str(provider).strip()] = seconds

    # A pin may be the documented shorthand string or the long dict form; the
    # CLI accepts both, so the MCP path must too.
    provider_models = dict(default.provider_models)
    configured_models = raw.get("provider_models")
    if isinstance(configured_models, dict):
        for provider, entry in configured_models.items():
            name = str(provider).strip()
            if isinstance(entry, str):
                model = entry.strip()
                if model:
                    provider_models[name] = {"model": model}
            elif isinstance(entry, dict):
                provider_models[name] = entry

    # Registered agents may carry their own timeout; an explicit
    # policy.provider_timeouts entry stays authoritative, matching the CLI.
    for agent in file_config.get("agents", []) or []:
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name", "")).strip()
        seconds = agent.get("timeout")
        if name and _valid_timeout(seconds) and name not in provider_timeouts:
            provider_timeouts[name] = seconds

    return ReviewPolicy(
        timeout_seconds=_positive_int("timeout_seconds", default.timeout_seconds),
        stall_timeout_seconds=_positive_int("stall_timeout_seconds", default.stall_timeout_seconds),
        review_hard_timeout_seconds=_positive_int(
            "review_hard_timeout_seconds", default.review_hard_timeout_seconds,
        ),
        max_provider_parallelism=_positive_int(
            "max_provider_parallelism", default.max_provider_parallelism,
        ),
        provider_timeouts=provider_timeouts,
        provider_models=provider_models,
    )


# ── Sync helpers (called via asyncio.to_thread from async tool handlers) ──

def _sync_doctor(providers_csv: Optional[str]) -> Dict[str, Any]:
    """Check provider installation and auth status."""
    from .cli import DEFAULT_DOCTOR_PROVIDERS, _doctor_provider_presence, SUPPORTED_PROVIDERS
    from .provider_risk import provider_risk

    if providers_csv:
        providers = [p.strip() for p in providers_csv.split(",") if p.strip()]
        valid = [p for p in providers if p in SUPPORTED_PROVIDERS]
        if not valid:
            return _err("invalid_providers", "No valid providers in: {}".format(providers_csv))
        providers = valid
    else:
        providers = list(DEFAULT_DOCTOR_PROVIDERS)

    presence_map = _doctor_provider_presence(providers)

    result_providers = []
    for provider in providers:
        presence = presence_map.get(provider)
        if presence is None:
            continue
        result_providers.append({
            "name": provider,
            "detected": bool(presence.detected),
            "auth_ok": bool(presence.auth_ok),
            "version": presence.version,
            "binary_path": presence.binary_path,
            "risk": provider_risk(provider),
        })

    return _ok({"providers": result_providers})


def _sync_review(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
    execution_mode: str = "read_only",
    invocation_timeout_seconds: int = 0,
    review_timeout_seconds: int = 0,
    event_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run the thin read-only review preset and return raw invocation outputs."""
    from .adapters import adapter_registry
    from .execution_modes import EXECUTION_MODES, execution_permissions
    from .invocation_runtime import default_invocations, run_invocation_workflow, validate_execution_scope

    err = _validate_repo(repo)
    if err:
        return err
    repo_path = Path(repo).resolve()

    valid_providers, provider_error = _resolve_provider_selection(providers)
    if provider_error:
        return provider_error
    if execution_mode not in EXECUTION_MODES:
        return _err("invalid_execution_mode", "Unknown execution mode: {}".format(execution_mode))

    provider_permissions = {}
    for provider in valid_providers:
        permissions = execution_permissions(provider, execution_mode)
        if permissions is None:
            return _err(
                "unsupported_execution_mode",
                "{} does not support execution mode {}; use yolo or choose another provider".format(
                    provider, execution_mode,
                ),
            )
        provider_permissions[provider] = permissions

    try:
        scope = validate_execution_scope(
            str(repo_path),
            [p.strip() for p in target_paths.split(",") if p.strip()] or ["."],
            ["."],
        )
        adapters = adapter_registry()
        policy = _resolve_policy(str(repo_path))
        invocations = default_invocations(valid_providers, scope, policy.provider_models)
        hard_timeout = _override_or(invocation_timeout_seconds, policy.timeout_seconds)
        global_timeout = _override_or(review_timeout_seconds, policy.review_hard_timeout_seconds)
        result = run_invocation_workflow(
            invocations=invocations,
            adapters=adapters,
            repo_root=str(repo_path),
            prompt=prompt or "Review the selected scope and report any concerns in natural language.",
            timeout_seconds=policy.stall_timeout_seconds,
            hard_timeout_seconds=hard_timeout,
            provider_permissions=provider_permissions,
            provider_models=policy.provider_models,
            allow_paths=["."],
            provider_timeouts=policy.provider_timeouts,
            max_provider_parallelism=policy.max_provider_parallelism,
            global_timeout_seconds=global_timeout if global_timeout > 0 else None,
            event_callback=event_callback,
        )
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(result)


def _sync_run(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
    execution_mode: str = "write",
    invocation_timeout_seconds: int = 0,
    review_timeout_seconds: int = 0,
    event_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """General-purpose multi-agent task execution."""
    from .adapters import adapter_registry
    from .execution_modes import EXECUTION_MODES, execution_permissions
    from .invocation_runtime import default_invocations, run_invocation_workflow, validate_execution_scope

    err = _validate_repo(repo)
    if err:
        return err
    repo_path = Path(repo).resolve()

    valid_providers, provider_error = _resolve_provider_selection(providers)
    if provider_error:
        return provider_error
    if execution_mode not in EXECUTION_MODES:
        return _err("invalid_execution_mode", "Unknown execution mode: {}".format(execution_mode))

    provider_permissions = {}
    for provider in valid_providers:
        permissions = execution_permissions(provider, execution_mode)
        if permissions is None:
            return _err(
                "unsupported_execution_mode",
                "{} does not support execution mode {}; use yolo or choose another provider".format(
                    provider, execution_mode,
                ),
            )
        provider_permissions[provider] = permissions

    try:
        scope = validate_execution_scope(
            str(repo_path),
            [p.strip() for p in target_paths.split(",") if p.strip()] or ["."],
            ["."],
        )
        policy = _resolve_policy(str(repo_path))
        hard_timeout = _override_or(invocation_timeout_seconds, policy.timeout_seconds)
        global_timeout = _override_or(review_timeout_seconds, policy.review_hard_timeout_seconds)
        result = run_invocation_workflow(
            invocations=default_invocations(valid_providers, scope, policy.provider_models),
            adapters=adapter_registry(),
            repo_root=str(repo_path),
            prompt=prompt,
            timeout_seconds=policy.stall_timeout_seconds,
            hard_timeout_seconds=hard_timeout,
            provider_permissions=provider_permissions,
            provider_models=policy.provider_models,
            allow_paths=["."],
            provider_timeouts=policy.provider_timeouts,
            max_provider_parallelism=policy.max_provider_parallelism,
            global_timeout_seconds=global_timeout if global_timeout > 0 else None,
            event_callback=event_callback,
        )
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(result)


# ── MCP Server ──

def ensure_mcp_installed() -> None:
    """Check that mcp.server.fastmcp is available. Raises ImportError if not."""
    import importlib
    importlib.import_module("mcp.server.fastmcp")


async def run_server() -> None:
    """Start the MCP stdio server with all MCO tools registered."""
    from mcp.server.fastmcp import Context, FastMCP

    mcp = FastMCP("mco")

    @mcp.tool()
    async def mco_doctor(providers: str = "") -> dict:
        """Check provider installation and auth status.

        Args:
            providers: Comma-separated provider list (default: all).
        """
        return await asyncio.to_thread(_sync_doctor, providers or None)

    @mcp.tool()
    async def mco_review(
        repo: str,
        prompt: str,
        providers: str,
        ctx: Context,
        target_paths: str = ".",
        execution_mode: str = "read_only",
        invocation_timeout_seconds: int = 0,
        review_timeout_seconds: int = 0,
    ) -> dict:
        """Run a thin read-only review and return raw provider answers.

        Args:
            repo: Path to repository root.
            prompt: Review instructions.
            providers: User-confirmed comma-separated provider list (e.g. "claude,codex,gemini").
            target_paths: Comma-separated scope paths (default: ".").
            execution_mode: "read_only", "write", or "yolo" (default: "read_only").
        """
        return await asyncio.to_thread(
            _sync_review, repo, prompt, providers, target_paths, execution_mode,
            invocation_timeout_seconds, review_timeout_seconds,
            _progress_callback(ctx, providers),
        )

    @mcp.tool()
    async def mco_run(
        repo: str,
        prompt: str,
        providers: str,
        ctx: Context,
        target_paths: str = ".",
        execution_mode: str = "write",
        invocation_timeout_seconds: int = 0,
        review_timeout_seconds: int = 0,
    ) -> dict:
        """General-purpose multi-agent task execution.

        Args:
            repo: Path to repository root.
            prompt: Task instructions.
            providers: User-confirmed comma-separated provider list.
            target_paths: Comma-separated scope paths (default: ".").
            execution_mode: "read_only", "write", or "yolo" (default: "write").
        """
        return await asyncio.to_thread(
            _sync_run, repo, prompt, providers, target_paths, execution_mode,
            invocation_timeout_seconds, review_timeout_seconds,
            _progress_callback(ctx, providers),
        )

    await mcp.run_stdio_async()
