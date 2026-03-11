"""Single-slot hook pair for MCO run lifecycle.

Phase 1 design: one pre_run slot, one post_run slot. Not a multi-hook
registry -- if multiple consumers are needed later, refactor to a list.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Dict, List, Optional

PreRunHook = Callable[..., Optional[str]]
PostRunHook = Callable[..., None]


class RunHooks:
    """Holds at most one pre_run and one post_run hook.

    Hook failures are logged to stderr but never block execution.
    """

    def __init__(self) -> None:
        self._pre_run: Optional[PreRunHook] = None
        self._post_run: Optional[PostRunHook] = None

    def set_pre_run(self, hook: PreRunHook) -> None:
        self._pre_run = hook

    def set_post_run(self, hook: PostRunHook) -> None:
        self._post_run = hook

    def invoke_pre_run(
        self,
        prompt: str,
        repo_root: str,
        providers: List[str],
    ) -> Optional[str]:
        if self._pre_run is None:
            return None
        try:
            return self._pre_run(prompt=prompt, repo_root=repo_root, providers=providers)
        except Exception as exc:
            print(f"[mco] pre_run hook error: {exc}", file=sys.stderr)
            return None

    def invoke_post_run(
        self,
        findings: List[Dict[str, Any]],
        provider_results: Dict[str, Dict[str, Any]],
        repo_root: str,
        prompt: str,
        providers: List[str],
    ) -> None:
        if self._post_run is None:
            return None
        try:
            self._post_run(
                findings=findings,
                provider_results=provider_results,
                repo_root=repo_root,
                prompt=prompt,
                providers=providers,
            )
        except Exception as exc:
            print(f"[mco] post_run hook error: {exc}", file=sys.stderr)
        return None
