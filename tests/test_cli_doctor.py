from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime.cli import SUPPORTED_PROVIDER_LIST, build_parser, main
from runtime.contracts import ProviderPresence


class CliDoctorTests(unittest.TestCase):
    def test_parser_accepts_doctor_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")
        self.assertEqual(args.providers, SUPPORTED_PROVIDER_LIST)
        self.assertFalse(args.json)
        self.assertFalse(args.skill_health)

    def test_doctor_json_payload_contract(self) -> None:
        probe = {
            "claude": ProviderPresence(
                provider="claude",
                detected=True,
                binary_path="/usr/local/bin/claude",
                version="1.0.0",
                auth_ok=True,
                reason="ok",
            ),
            "codex": ProviderPresence(
                provider="codex",
                detected=True,
                binary_path="/usr/local/bin/codex",
                version="0.105.0",
                auth_ok=False,
                reason="auth_check_failed",
            ),
        }
        output = io.StringIO()
        with patch("runtime.cli._doctor_provider_presence", return_value=probe):
            with redirect_stdout(output):
                exit_code = main(["doctor", "--providers", "claude,codex", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(tuple(payload.keys()), ("command", "overall_ok", "ready_count", "provider_count", "providers"))
        self.assertEqual(payload["command"], "doctor")
        self.assertEqual(payload["overall_ok"], False)
        self.assertEqual(payload["ready_count"], 1)
        self.assertEqual(payload["provider_count"], 2)
        self.assertEqual(
            tuple(payload["providers"]["claude"].keys()),
            ("detected", "binary_path", "version", "auth_ok", "reason", "ready", "risk"),
        )
        self.assertEqual(payload["providers"]["claude"]["ready"], True)
        self.assertEqual(payload["providers"]["claude"]["risk"]["level"], "read_only")
        self.assertEqual(payload["providers"]["codex"]["risk"]["level"], "workspace_write")
        self.assertEqual(payload["providers"]["codex"]["ready"], False)
        self.assertEqual(payload["providers"]["codex"]["reason"], "auth_check_failed")

    def test_doctor_rejects_invalid_provider_set(self) -> None:
        with redirect_stderr(io.StringIO()):
            exit_code = main(["doctor", "--providers", "unknown"])
        self.assertEqual(exit_code, 2)

    def test_doctor_invalid_provider_json_uses_error_envelope(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["doctor", "--providers", "claude,unknown", "--json"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"]["subtype"], "invalid_providers")
        self.assertIn("unknown", payload["error"]["message"])

    def test_doctor_human_report_suggests_ready_providers_when_not_ok(self) -> None:
        probe = {
            "claude": ProviderPresence(
                provider="claude",
                detected=True,
                binary_path="/usr/local/bin/claude",
                version="1.0.0",
                auth_ok=True,
                reason="ok",
            ),
            "codex": ProviderPresence(
                provider="codex",
                detected=False,
                binary_path=None,
                version=None,
                auth_ok=False,
                reason="binary_not_found",
            ),
        }
        output = io.StringIO()
        with patch("runtime.cli._doctor_provider_presence", return_value=probe):
            with redirect_stdout(output):
                exit_code = main(["doctor", "--providers", "claude,codex"])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("Next Steps", text)
        self.assertIn("Ready providers: claude", text)
        self.assertIn("--providers claude", text)

    def test_doctor_json_classifies_copilot_risk(self) -> None:
        probe = {
            "copilot": ProviderPresence(
                provider="copilot",
                detected=True,
                binary_path="/usr/local/bin/copilot",
                version="1.0.65",
                auth_ok=True,
                reason="ok",
            ),
        }
        output = io.StringIO()
        with patch("runtime.cli._doctor_provider_presence", return_value=probe):
            with redirect_stdout(output):
                exit_code = main(["doctor", "--providers", "copilot", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["providers"]["copilot"]["risk"]["level"], "approval_bypass")


if __name__ == "__main__":
    unittest.main()
