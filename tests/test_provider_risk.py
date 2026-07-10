from __future__ import annotations

import unittest

from runtime.contracts import PROVIDER_IDS
from runtime.provider_risk import effective_provider_risk, provider_risk


class ProviderRiskTests(unittest.TestCase):
    def test_all_builtin_providers_have_classified_risk(self) -> None:
        for provider in PROVIDER_IDS:
            with self.subTest(provider=provider):
                self.assertNotEqual(provider_risk(provider)["level"], "unknown")

    def test_copilot_is_approval_bypass(self) -> None:
        self.assertEqual(provider_risk("copilot")["level"], "approval_bypass")

    def test_grok_defaults_to_approval_prompts(self) -> None:
        self.assertEqual(provider_risk("grok")["level"], "workspace_write")

    def test_cursor_defaults_to_read_only_ask_mode(self) -> None:
        self.assertEqual(provider_risk("cursor")["level"], "read_only")

    def test_grok_always_approve_override_is_visible(self) -> None:
        risk = effective_provider_risk("grok", {"approval_mode": "always-approve"})
        self.assertEqual(risk["level"], "approval_bypass")

    def test_cursor_agent_mode_override_is_visible(self) -> None:
        risk = effective_provider_risk("cursor", {"mode": "agent"})
        self.assertEqual(risk["level"], "workspace_write")

    def test_cursor_force_override_is_approval_bypass(self) -> None:
        risk = effective_provider_risk("cursor", {"force": "true"})
        self.assertEqual(risk["level"], "approval_bypass")

    def test_codex_read_only_override_reduces_effective_risk(self) -> None:
        risk = effective_provider_risk("codex", {"sandbox": "read-only"})
        self.assertEqual(risk["level"], "read_only")

    def test_claude_accept_edits_override_increases_effective_risk(self) -> None:
        risk = effective_provider_risk("claude", {"permission_mode": "acceptEdits"})
        self.assertEqual(risk["level"], "workspace_write")

    def test_unknown_permission_value_is_not_guessed(self) -> None:
        risk = effective_provider_risk("codex", {"sandbox": "custom-sandbox"})
        self.assertEqual(risk["level"], "unknown")


if __name__ == "__main__":
    unittest.main()
