from __future__ import annotations

import unittest

from runtime.adapters.parsing import extract_final_text_from_output, inspect_contract_output


class ParsingContractTests(unittest.TestCase):
    def test_extract_final_text_from_plain_text(self) -> None:
        text = "This is the final answer."
        self.assertEqual(extract_final_text_from_output(text), text)

    def test_extract_final_text_from_codex_like_event_stream(self) -> None:
        text = (
            '{"type":"thread.started"}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Interim"}]}}\n'
            '{"type":"result","result":"Final concise answer."}'
        )
        self.assertEqual(extract_final_text_from_output(text), "Final concise answer.")

    def test_extract_final_text_from_qwen_like_array_stream(self) -> None:
        text = (
            '[{"type":"assistant","message":{"content":[{"type":"text","text":"step-1"}]}},'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"最终回答"}]}}]'
        )
        self.assertEqual(extract_final_text_from_output(text), "最终回答")

    def test_extract_final_text_ignores_trailing_low_signal_tokens(self) -> None:
        text = (
            '[{"type":"assistant","message":{"content":[{"type":"text","text":"Final summary sentence for callers."}]}}'
            ',{"type":"result","result":"Final summary sentence for callers.","stats":{"keywords":["cli","orchestrator","runtime"]}}]'
        )
        self.assertEqual(extract_final_text_from_output(text), "Final summary sentence for callers.")

    def test_contract_json_valid(self) -> None:
        text = '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"t","evidence":{"file":"a.py","line":1,"symbol":null,"snippet":"x"},"recommendation":"r","confidence":0.5,"fingerprint":"fp"}]}'
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)
        self.assertEqual(info["dropped_count"], 0)

    def test_contract_json_invalid_shape(self) -> None:
        text = '{"findings":[{"severity":"low"}]}'
        info = inspect_contract_output(text)
        self.assertFalse(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 0)
        self.assertGreaterEqual(info["dropped_count"], 1)

    def test_contract_json_allows_missing_optional_line_symbol(self) -> None:
        text = (
            '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"t",'
            '"evidence":{"file":"a.py","snippet":"x"},"recommendation":"r","confidence":0.5,"fingerprint":"fp"}]}'
        )
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)
        self.assertEqual(info["dropped_count"], 0)

    def test_plain_text_with_findings_word_is_not_parse_ok(self) -> None:
        text = "we have findings but this is not json"
        info = inspect_contract_output(text)
        self.assertFalse(info["parse_ok"])
        self.assertFalse(info["has_contract_envelope"])
        self.assertEqual(info["parse_reason"], "no_contract_envelope")

    def test_mixed_contract_envelopes_prefers_valid_candidate(self) -> None:
        text = (
            '{"findings":[{"finding_id":"bad","severity":"low"}]}\n'
            '{"findings":[{"finding_id":"good","severity":"low","category":"maintainability","title":"t",'
            '"evidence":{"file":"a.py","line":1,"symbol":null,"snippet":"x"},"recommendation":"r","confidence":0.5,"fingerprint":"fp"}]}'
        )
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)
        self.assertEqual(info["dropped_count"], 0)
        self.assertEqual(info["parse_reason"], "ok")

    def test_codex_event_stream_embedded_contract_json(self) -> None:
        text = (
            '{"type":"item.completed","item":{"type":"agent_message","text":"{\\"findings\\":[{\\"finding_id\\":\\"c1\\",'
            '\\"severity\\":\\"high\\",\\"category\\":\\"bug\\",\\"title\\":\\"t\\",\\"evidence\\":{\\"file\\":\\"a.py\\",'
            '\\"line\\":1,\\"symbol\\":null,\\"snippet\\":\\"x\\"},\\"recommendation\\":\\"r\\",\\"confidence\\":0.9,'
            '\\"fingerprint\\":\\"fp\\"}]}"}}'
        )
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)

    def test_opencode_event_stream_embedded_fenced_json(self) -> None:
        text = (
            '{"type":"text","part":{"type":"text","text":"```json\\n{\\"findings\\":[{\\"finding_id\\":\\"o1\\",'
            '\\"severity\\":\\"low\\",\\"category\\":\\"maintainability\\",\\"title\\":\\"t\\",\\"evidence\\":{\\"file\\":\\"o.py\\",'
            '\\"line\\":null,\\"symbol\\":null,\\"snippet\\":\\"x\\"},\\"recommendation\\":\\"r\\",\\"confidence\\":0.7,'
            '\\"fingerprint\\":\\"fp\\"}]}\\n```"}}'
        )
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)

    def test_qwen_array_stream_embedded_contract_json(self) -> None:
        text = (
            '[{"type":"assistant","message":{"content":[{"type":"text","text":"{\\"findings\\":[{\\"finding_id\\":\\"q1\\",'
            '\\"severity\\":\\"medium\\",\\"category\\":\\"performance\\",\\"title\\":\\"t\\",\\"evidence\\":{\\"file\\":\\"q.py\\",'
            '\\"line\\":2,\\"symbol\\":null,\\"snippet\\":\\"x\\"},\\"recommendation\\":\\"r\\",\\"confidence\\":0.5,'
            '\\"fingerprint\\":\\"fp\\"}]}" }]}}]'
        )
        info = inspect_contract_output(text)
        self.assertTrue(info["parse_ok"])
        self.assertEqual(info["schema_valid_count"], 1)


if __name__ == "__main__":
    unittest.main()
