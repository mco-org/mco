from __future__ import annotations

import json
from typing import Any, Dict, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class PiAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="pi",
            binary_name="pi",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="0.80.0",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "--list-models"]

    def supported_model_keys(self) -> List[str]:
        return ["model", "provider"]

    def supported_permission_keys(self) -> List[str]:
        return ["tool_profile"]

    def supported_context_keys(self) -> List[str]:
        return ["skills", "context_files"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        # Strict read-only tool allowlist: read files, search content,
        # find by name, list directories.  No bash / edit / write.
        # The tool allowlist is locked — context policy cannot widen it.
        ctx = input_task.metadata.get("provider_context", {})
        if not isinstance(ctx, dict):
            ctx = {}
        cmd = [
            "pi",
            "-p",
            "--mode", "json",
            "--no-session",
        ]
        # Context files: disabled by default (preserves existing behavior)
        if ctx.get("context_files") is True:
            pass  # omit --no-context-files, let Pi use its defaults
        else:
            cmd.append("--no-context-files")
        # Skills: disabled by default, can be "ambient" or explicit list
        skills = ctx.get("skills")
        if isinstance(skills, list) and skills:
            # Explicit skill preload: pass each skill name.
            # Omit --no-skills because it might suppress explicit --skill.
            for skill_name in skills:
                cmd.extend(["--skill", str(skill_name)])
        elif skills == "ambient":
            pass  # omit --no-skills, let Pi discover ambient skills
        else:
            cmd.append("--no-skills")
        # Extensions: always disabled. The extensions key is not supported
        # by Pi's supported_context_keys — the review_engine will reject it
        # in strict mode or drop it in best_effort.
        cmd.append("--no-extensions")
        permissions = input_task.metadata.get("provider_permissions", {})
        tool_profile = permissions.get("tool_profile", "read_only") if isinstance(permissions, dict) else "read_only"
        tools = {
            "read_only": "read,grep,find,ls",
            "write": "read,write,edit,grep,find,ls",
            "yolo": "read,write,edit,bash,grep,find,ls",
        }
        if tool_profile not in tools:
            raise ValueError("unsupported Pi tool_profile: {}".format(tool_profile))
        cmd.extend(["--tools", tools[str(tool_profile)]])
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        provider = input_task.metadata.get("provider")
        if isinstance(provider, str) and provider.strip():
            cmd.extend(["--provider", provider.strip()])
        cmd.append(input_task.prompt)
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return [
            "pi", "-p", "--mode", "json", "--no-session",
            "--tools", "read,grep,find,ls", "--no-context-files",
            "--no-skills", "--no-extensions", "<prompt>",
        ]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        return '"type":"agent_end"' in stdout_text

    @staticmethod
    def _extract_final_text_from_jsonl(jsonl_text: str) -> str:
        """Extract final assistant text from pi --mode json JSONL event stream.

        Collects text_delta events from the message_update stream and
        concatenates them into a single text string.
        """
        text_parts: List[str] = []
        for line in jsonl_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "message_update":
                assistant_event = event.get("assistantMessageEvent")
                if not isinstance(assistant_event, dict):
                    continue
                if assistant_event.get("type") == "text_delta":
                    delta = assistant_event.get("delta")
                    if isinstance(delta, str):
                        text_parts.append(delta)
        return "".join(text_parts)

    @staticmethod
    def _extract_from_agent_end(jsonl_text: str) -> str:
        """Alternative: extract final text from agent_end event's messages array.

        Falls back to agent_end extraction if text_delta yields nothing.
        """
        text_parts: List[str] = []
        for line in jsonl_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "agent_end":
                messages = event.get("messages")
                if not isinstance(messages, list):
                    continue
                # Find the last assistant message
                for msg in reversed(messages):
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("role") != "assistant":
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            t = block.get("text")
                            if isinstance(t, str):
                                text_parts.append(t)
                    break
                break
        return "".join(text_parts)

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        if not text:
            return []
        # Extract final text from JSONL event stream
        final_text = self._extract_final_text_from_jsonl(text)
        if not final_text:
            final_text = self._extract_from_agent_end(text)
        if not final_text:
            return []
        return normalize_findings_from_text(final_text, ctx, "pi")
