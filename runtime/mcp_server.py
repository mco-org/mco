"""MCP server mode for MCO — exposes tools over stdio MCP protocol.

Start with: mco serve
Configure in MCP client: {"command": "mco", "args": ["serve"]}
"""
from __future__ import annotations

import asyncio
import os
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


# ── Sync helpers (called via asyncio.to_thread from async tool handlers) ──

def _sync_doctor(providers_csv: Optional[str]) -> Dict[str, Any]:
    """Check provider installation and auth status."""
    from .cli import _doctor_provider_presence, SUPPORTED_PROVIDERS

    if providers_csv:
        providers = [p.strip() for p in providers_csv.split(",") if p.strip()]
        valid = [p for p in providers if p in SUPPORTED_PROVIDERS]
        if not valid:
            return _err("invalid_providers", "No valid providers in: {}".format(providers_csv))
        providers = valid
    else:
        providers = list(SUPPORTED_PROVIDERS)

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
        })

    return _ok({"providers": result_providers})


def _sync_review(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
    diff_mode: Optional[str] = None,
    diff_base: Optional[str] = None,
    memory: bool = False,
    space: Optional[str] = None,
) -> Dict[str, Any]:
    """Run structured multi-agent code review."""
    from .review_engine import ReviewRequest, run_review
    from .config import ReviewPolicy
    from .cli import SUPPORTED_PROVIDERS

    require_git = bool(diff_mode or diff_base)
    err = _validate_repo(repo, require_git=require_git)
    if err:
        return err
    repo_path = Path(repo).resolve()

    provider_list = [p.strip() for p in providers.split(",") if p.strip()]
    valid_providers = [p for p in provider_list if p in SUPPORTED_PROVIDERS]
    if not valid_providers:
        return _err("invalid_providers", "No valid providers in: {}".format(providers))

    effective_diff_mode = diff_mode
    if diff_base and not effective_diff_mode:
        effective_diff_mode = "branch"

    try:
        req = ReviewRequest(
            repo_root=str(repo_path),
            prompt=prompt,
            providers=valid_providers,
            artifact_base=str(repo_path / "reports" / "review"),
            policy=ReviewPolicy(),
            target_paths=[p.strip() for p in target_paths.split(",") if p.strip()],
            memory_enabled=memory,
            memory_space=space or None,
            diff_mode=effective_diff_mode,
            diff_base=diff_base or None,
        )
        result = run_review(req, review_mode=True, write_artifacts=False)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok({
        "task_id": result.task_id,
        "decision": result.decision,
        "terminal_state": result.terminal_state,
        "findings_count": result.findings_count,
        "findings": result.findings,
    })


def _sync_run(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
) -> Dict[str, Any]:
    """General-purpose multi-agent task execution."""
    from .review_engine import ReviewRequest, run_review
    from .config import ReviewPolicy
    from .cli import SUPPORTED_PROVIDERS

    err = _validate_repo(repo)
    if err:
        return err
    repo_path = Path(repo).resolve()

    provider_list = [p.strip() for p in providers.split(",") if p.strip()]
    valid_providers = [p for p in provider_list if p in SUPPORTED_PROVIDERS]
    if not valid_providers:
        return _err("invalid_providers", "No valid providers in: {}".format(providers))

    try:
        req = ReviewRequest(
            repo_root=str(repo_path),
            prompt=prompt,
            providers=valid_providers,
            artifact_base=str(repo_path / "reports" / "review"),
            policy=ReviewPolicy(),
            target_paths=[p.strip() for p in target_paths.split(",") if p.strip()],
        )
        result = run_review(req, review_mode=False, write_artifacts=False)
    except Exception as exc:
        return _err("execution_error", str(exc))

    # Only include final_text (not full output_text) to keep response compact
    slim_results: Dict[str, Any] = {}
    for provider, pr in result.provider_results.items():
        slim_results[provider] = {
            "success": pr.get("success"),
            "final_text": pr.get("final_text", ""),
        }

    return _ok({
        "task_id": result.task_id,
        "decision": result.decision,
        "terminal_state": result.terminal_state,
        "provider_results": slim_results,
    })


def _sync_findings_list(
    repo: str = ".",
    space: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """List persisted findings from evermemos memory."""
    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        return _err("missing_api_key", "EVERMEMOS_API_KEY environment variable is required")

    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .findings_cli import list_findings

    repo_path = str(Path(repo).resolve())
    slug = infer_space_slug(repo_path, explicit=space or None)
    findings_space = "coding:{slug}--findings".format(slug=slug)

    try:
        client = EverMemosClient(api_key=api_key)
        findings = list_findings(client, findings_space, status_filter=status or None)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(findings)


def _sync_memory_status(
    repo: str = ".",
    space: Optional[str] = None,
) -> Dict[str, Any]:
    """Show memory space overview."""
    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        return _err("missing_api_key", "EVERMEMOS_API_KEY environment variable is required")

    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .memory_cli import get_status_data

    repo_path = str(Path(repo).resolve())
    slug = infer_space_slug(repo_path, explicit=space or None)

    try:
        client = EverMemosClient(api_key=api_key)
        data = get_status_data(client, slug)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(data)


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
        diff_mode: str = "",
        diff_base: str = "",
        memory: bool = False,
        space: str = "",
    ) -> dict:
        """Run structured multi-agent code review.

        Args:
            repo: Path to repository root.
            prompt: Review instructions.
            providers: Comma-separated provider list (e.g. "claude,codex,gemini").
            target_paths: Comma-separated scope paths (default: ".").
            diff_mode: "branch", "staged", or "unstaged" (default: disabled).
            diff_base: Git ref for branch diff (implies diff_mode="branch").
            memory: Enable evermemos memory layer.
            space: Memory space slug (auto-inferred if empty).
        """
        return await asyncio.to_thread(
            _sync_review, repo, prompt, providers, target_paths,
            diff_mode or None, diff_base or None, memory, space or None,
        )

    @mcp.tool()
    async def mco_run(
        repo: str,
        prompt: str,
        providers: str,
        target_paths: str = ".",
    ) -> dict:
        """General-purpose multi-agent task execution.

        Args:
            repo: Path to repository root.
            prompt: Task instructions.
            providers: Comma-separated provider list.
            target_paths: Comma-separated scope paths (default: ".").
        """
        return await asyncio.to_thread(
            _sync_run, repo, prompt, providers, target_paths,
        )

    @mcp.tool()
    async def mco_findings_list(
        repo: str = ".",
        space: str = "",
        status: str = "",
    ) -> dict:
        """List persisted findings from evermemos memory.

        Args:
            repo: Repository root path (for space inference).
            space: Space slug override (auto-inferred if empty).
            status: Filter by status: "open", "fixed", "rejected", etc.
        """
        return await asyncio.to_thread(
            _sync_findings_list, repo, space or None, status or None,
        )

    @mcp.tool()
    async def mco_memory_status(
        repo: str = ".",
        space: str = "",
    ) -> dict:
        """Show memory space overview (findings count, agent scores, briefing).

        Args:
            repo: Repository root path (for space inference).
            space: Space slug override (auto-inferred if empty).
        """
        return await asyncio.to_thread(
            _sync_memory_status, repo, space or None,
        )

    await mcp.run_async(transport="stdio")
