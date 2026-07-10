from __future__ import annotations

import json
import unittest

from runtime.acp.adapter import AcpAdapter
from runtime.adapters.codex import CodexAdapter
from runtime.adapters.pi import PiAdapter


class AnswerTransportTests(unittest.TestCase):
    def test_codex_transport_decodes_answer_deltas_final_and_usage(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "item.delta", "item": {"type": "agent_message", "delta": "Hello"}}),
                json.dumps({"type": "item.delta", "item": {"type": "agent_message", "delta": " world"}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Hello world"}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}}),
            ]
        )

        result = CodexAdapter().decode_transport(raw)

        self.assertEqual([delta.text for delta in result.deltas], ["Hello", " world"])
        self.assertEqual(result.final_answer, "Hello world")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.usage, {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14})

    def test_pi_transport_ignores_thinking_and_protocol_logs(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "secret"}}),
                json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Pi"}}),
                json.dumps({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": " answer"}}),
                json.dumps({"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": "Pi answer"}]}]}),
            ]
        )

        result = PiAdapter().decode_transport(raw)

        self.assertEqual([delta.text for delta in result.deltas], ["Pi", " answer"])
        self.assertEqual(result.final_answer, "Pi answer")
        self.assertEqual(result.status, "succeeded")
        self.assertIsNone(result.usage)

    def test_acp_transport_decodes_text_blocks_and_status_without_tool_content(self) -> None:
        updates = [
            {"method": "session/update", "params": {"state": "working", "content": [{"type": "thinking", "text": "secret"}, {"type": "text", "text": "ACP"}]}},
            {"method": "session/update", "params": {"state": "idle", "content": [{"type": "tool_result", "output": "ignored"}, {"type": "text", "text": " answer"}], "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}}},
        ]

        result = AcpAdapter(provider_id="test", binary_name="test").decode_transport(updates)

        self.assertEqual([delta.text for delta in result.deltas], ["ACP", " answer"])
        self.assertEqual(result.final_answer, "ACP answer")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.usage, {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})

    def test_acp_adapter_accepts_completed_text_from_its_runtime_boundary(self) -> None:
        result = AcpAdapter(provider_id="test", binary_name="test").decode_transport("ACP answer")

        self.assertEqual(result.final_answer, "ACP answer")
        self.assertEqual([delta.text for delta in result.deltas], ["ACP answer"])



if __name__ == "__main__":
    unittest.main()
