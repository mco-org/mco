"""MCO Memory Bridge — connects MCO to evermemos-mcp for cross-run memory."""
from __future__ import annotations


def register_hooks(hooks: object, request: object) -> None:
    """Fill pre_run and post_run slots on RunHooks.

    Called by review_engine when --memory is enabled.
    Creates a BridgeContext (not module globals) and closes over it.
    """
    from .core import BridgeContext, make_pre_run, make_post_run

    memory_space = getattr(request, "memory_space", None)
    ctx = BridgeContext(memory_space_override=memory_space)

    hooks.set_pre_run(make_pre_run(ctx))    # type: ignore[attr-defined]
    hooks.set_post_run(make_post_run(ctx))   # type: ignore[attr-defined]
