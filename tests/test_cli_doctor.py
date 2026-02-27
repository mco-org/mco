from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime.cli import build_parser, main
from runtime.contracts import ProviderPresence


class CliDoctorTests(unittest.TestCase):
    def test_parser_accepts_doctor_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        self.assertEqual(args.command, "doctor")
        self.assertEqual(args.providers, "claude,codex")
        self.assertFalse(args.json)

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
            ("detected", "binary_path", "version", "auth_ok", "reason", "ready"),
        )
        self.assertEqual(payload["providers"]["claude"]["ready"], True)
        self.assertEqual(payload["providers"]["codex"]["ready"], False)
        self.assertEqual(payload["providers"]["codex"]["reason"], "auth_check_failed")

    def test_doctor_rejects_invalid_provider_set(self) -> None:
        with redirect_stderr(io.StringIO()):
            exit_code = main(["doctor", "--providers", "unknown"])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
