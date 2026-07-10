from __future__ import annotations

import unittest

from runtime.adapters import ClaudeAdapter, CommandShimAdapter, CopilotAdapter, CursorAdapter, GeminiAdapter, GrokAdapter, HermesAdapter, OllamaAdapter, OpenCodeAdapter, QwenAdapter


class StandardTransportTests(unittest.TestCase):
    def test_nonzero_exit_is_not_reclassified_by_answer_text(self) -> None:
        adapter = CommandShimAdapter.from_command_text("custom", "python3 -c 'print(1)'")

        self.assertFalse(adapter._is_success(1, "the answer says everything is fine", ""))

    def test_plain_text_provider_transport_preserves_opaque_answer(self) -> None:
        adapters = [
            ClaudeAdapter(),
            GeminiAdapter(),
            OpenCodeAdapter(),
            QwenAdapter(),
            HermesAdapter(),
            CopilotAdapter(),
            GrokAdapter(),
            CursorAdapter(),
            OllamaAdapter(),
            CommandShimAdapter.from_command_text("custom", "python3 -c 'print(1)'"),
        ]
        answer = "Answer with a literal {json} fragment.\n"

        for adapter in adapters:
            with self.subTest(provider=adapter.id):
                result = adapter.decode_transport(answer)
                self.assertEqual(result.final_answer, answer)
                self.assertEqual([delta.text for delta in result.deltas], [answer])
                self.assertIsNone(result.usage)


if __name__ == "__main__":
    unittest.main()
