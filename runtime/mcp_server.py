"""MCP server mode for MCO — exposes tools over stdio MCP protocol.

Start with: mco serve
Configure in MCP client: {"command": "mco", "args": ["serve"]}
"""
from __future__ import annotations

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
) -> Dict[str, Any]:
    """Run the thin read-only review preset and return raw invocation outputs."""
    from .adapters import adapter_registry
    from .config import ReviewPolicy
    from .execution_modes import EXECUTION_MODES, execution_permissions
    from .invocation_runtime import parse_invocations, run_invocation_workflow, validate_execution_scope

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
        invocations = parse_invocations(
            ["{}:default".format(provider) for provider in valid_providers],
            scope,
        )
        default_policy = ReviewPolicy()
        result = run_invocation_workflow(
            invocations=invocations,
            adapters=adapters,
            repo_root=str(repo_path),
            prompt=prompt or "Review the selected scope and report any concerns in natural language.",
            timeout_seconds=default_policy.stall_timeout_seconds,
            hard_timeout_seconds=default_policy.timeout_seconds,
            provider_permissions=provider_permissions,
            allow_paths=["."],
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
) -> Dict[str, Any]:
    """General-purpose multi-agent task execution."""
    from .adapters import adapter_registry
    from .config import ReviewPolicy
    from .execution_modes import EXECUTION_MODES, execution_permissions
    from .invocation_runtime import parse_invocations, run_invocation_workflow, validate_execution_scope

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
        default_policy = ReviewPolicy()
        result = run_invocation_workflow(
            invocations=parse_invocations(
                ["{}:default".format(provider) for provider in valid_providers],
                scope,
            ),
            adapters=adapter_registry(),
            repo_root=str(repo_path),
            prompt=prompt,
            timeout_seconds=default_policy.stall_timeout_seconds,
            hard_timeout_seconds=default_policy.timeout_seconds,
            provider_permissions=provider_permissions,
            allow_paths=["."],
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
    from mcp.server.fastmcp import FastMCP

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
        target_paths: str = ".",
        execution_mode: str = "read_only",
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
        )

    @mcp.tool()
    async def mco_run(
        repo: str,
        prompt: str,
        providers: str,
        target_paths: str = ".",
        execution_mode: str = "write",
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
        )

    await mcp.run_async(transport="stdio")
