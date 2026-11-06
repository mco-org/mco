from __future__ import annotations

import json
from dataclasses import replace
import unittest

from runtime.adapters.hermes import HermesAdapter
from runtime.adapters.opencode import OpenCodeAdapter
from runtime.adapters.pi import PiAdapter
from runtime.contracts import TaskInput
from runtime.config import ReviewPolicy
from runtime.policy import provider_policy_preview


def _task(**metadata) -> TaskInput:
    return TaskInput(
        task_id="compatibility", prompt="Review this repository.",
        repo_root="/tmp", target_paths=["."], timeout_seconds=60,
        metadata=metadata,
    )


class CurrentAgentAdapterTests(unittest.TestCase):
    def test_opencode_unverified_plugin_isolation_fails_strict_policy(self) -> None:
        policy = ReviewPolicy(provider_context={"opencode": {"plugins": False}})
        preview = provider_policy_preview("opencode", OpenCodeAdapter(), policy)
        self.assertEqual(preview["failure_reason"], "context_policy_enforcement_failed")
        self.assertEqual(preview["applied_context"], {})
        best_effort = provider_policy_preview(
            "opencode", OpenCodeAdapter(), replace(policy, enforcement_mode="best_effort"),
        )
        self.assertEqual(best_effort["dropped_context_keys"], ["plugins"])
        self.assertEqual(best_effort["failure_reason"], "")

    def test_opencode_uses_process_working_directory_without_removed_dir_flag(self) -> None:
        adapter = OpenCodeAdapter()
        self.assertNotIn("--dir", adapter._build_command(_task()))
        self.assertNotIn("--dir", adapter._build_command_for_record())

    def test_opencode_model_override_is_supported_and_forwarded(self) -> None:
        adapter = OpenCodeAdapter()
        self.assertEqual(adapter.supported_model_keys(), ["model"])
        command = adapter._build_command(_task(model=" openai/gpt-5 "))
        self.assertEqual(command[command.index("--model") + 1], "openai/gpt-5")

    def test_hermes_context_files_disabled_keeps_provider_configuration(self) -> None:
        command = HermesAdapter()._build_command(_task(provider_context={"context_files": False}))
        self.assertIn("--ignore-rules", command)
        self.assertNotIn("--safe-mode", command)
        self.assertNotIn("--ignore-user-config", command)

    def test_pi_success_parses_json_instead_of_requiring_compact_serialization(self) -> None:
        raw = json.dumps({"type": "agent_end", "messages": []}) + "\n"
        self.assertTrue(PiAdapter()._is_success(0, raw, ""))
        self.assertFalse(PiAdapter()._is_success(1, raw, ""))

    def test_pi_success_does_not_accept_agent_end_inside_answer_text(self) -> None:
        raw = json.dumps({"type": "message_update", "assistantMessageEvent": {
            "type": "text_delta", "delta": '"type":"agent_end"',
        }})
        self.assertFalse(PiAdapter()._is_success(0, raw, ""))

    def test_pi_ends_option_parsing_before_prompt(self) -> None:
        task = replace(_task(), prompt="--help")
        command = PiAdapter()._build_command(task)
        self.assertEqual(command[-2:], ["--", "--help"])

    def test_pi_provider_override_requires_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires.*model"):
            PiAdapter()._build_command(_task(provider="openai"))

    def test_pi_final_model_error_or_abort_is_not_success(self) -> None:
        for reason in ("error", "aborted"):
            with self.subTest(reason=reason):
                raw = "\n".join(json.dumps(event) for event in [
                    {"type": "agent_end", "willRetry": False, "messages": [
                        {"role": "assistant", "content": [{"type": "text", "text": "old answer"}], "stopReason": "toolUse"},
                        {"role": "assistant", "content": [], "stopReason": reason, "errorMessage": "failed"},
                    ]},
                    {"type": "agent_settled", "aborted": reason == "aborted"},
                ])
                result = PiAdapter().decode_transport(raw)
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.final_answer, "")
                self.assertFalse(PiAdapter()._is_success(0, raw, ""))

    def test_pi_latest_run_waits_until_settled(self) -> None:
        raw = json.dumps({"type": "agent_end", "willRetry": False, "messages": []})
        self.assertEqual(PiAdapter().decode_transport(raw).status, "running")
        raw += '\n' + json.dumps({"type": "agent_settled", "aborted": False})
        self.assertEqual(PiAdapter().decode_transport(raw).status, "succeeded")

    def test_pi_retry_success_replaces_failed_attempt(self) -> None:
        events = [
            {"type": "agent_end", "willRetry": True, "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "old partial"}], "stopReason": "error"},
            ]},
            {"type": "agent_start"},
            {"type": "agent_end", "willRetry": False, "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "new answer"}], "stopReason": "stop"},
            ]},
            {"type": "agent_settled", "aborted": False},
        ]
        pending = PiAdapter().decode_transport(json.dumps(events[0]))
        self.assertEqual(pending.status, "running")
        result = PiAdapter().decode_transport("\n".join(json.dumps(event) for event in events))
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.final_answer, "new answer")

    def test_pi_exhausted_retry_remains_failed_when_settled(self) -> None:
        raw = "\n".join(json.dumps(event) for event in [
            {"type": "agent_end", "willRetry": True, "messages": [
                {"role": "assistant", "content": [], "stopReason": "error"},
            ]},
            {"type": "auto_retry_end", "success": False, "finalError": "retry failed"},
            {"type": "agent_settled", "aborted": False},
        ])
        self.assertEqual(PiAdapter().decode_transport(raw).status, "failed")

    def test_pi_token_limit_is_failure_even_when_json_process_exits_zero(self) -> None:
        raw = "\n".join(json.dumps(event) for event in [
            {"type": "agent_end", "willRetry": False, "messages": [
                {"role": "assistant", "content": [{"type": "text", "text": "Truncated answer"}], "stopReason": "length"},
            ]},
            {"type": "agent_settled", "aborted": False},
        ])
        self.assertEqual(PiAdapter().decode_transport(raw).status, "failed")
        self.assertFalse(PiAdapter()._is_success(0, raw, ""))


if __name__ == "__main__":
    unittest.main()
