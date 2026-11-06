from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from runtime.adapters import adapter_registry
from runtime.cli import main


class ProviderCompatibilityTests(unittest.TestCase):
    def test_kimi_is_available_with_shim_and_acp_fallback(self) -> None:
        for transport in ("shim", "acp"):
            with self.subTest(transport=transport):
                self.assertEqual(adapter_registry(transport=transport)["kimi"].id, "kimi")

    def test_requested_team_can_preview_explicit_models_without_execution(self) -> None:
        providers = ("agy", "pi", "opencode", "hermes", "kimi", "codex", "grok")
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            args = ["run", "--repo", tmp, "--prompt", "Reply OK", "--dry-run", "--json", "--execution-mode", "yolo"]
            for provider in providers:
                args.extend(["--agent", provider + ":example-model"])
            with contextlib.redirect_stdout(output):
                code = main(args)
        self.assertEqual(code, 0, output.getvalue())
        payload = json.loads(output.getvalue())
        for provider in providers:
            with self.subTest(provider=provider):
                self.assertIn({"provider": provider, "model": "example-model"}, [{"provider": item["provider"], "model": item["model"]} for item in payload["invocations"]])
                self.assertFalse(payload["providers_detail"][provider]["policy"]["would_fail_strict"])

    def test_kimi_review_and_run_apply_bundled_tool_profiles(self) -> None:
        for command, filename, risk in (("review", "kimi-read-only.md", "read_only"), ("run", "kimi-write.md", "workspace_write")):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main([command, "--repo", tmp, "--prompt", "Review", "--providers", "kimi", "--dry-run", "--json"])
                self.assertEqual(code, 0, output.getvalue())
                detail = json.loads(output.getvalue())["providers_detail"]["kimi"]
                invocation = detail["command_template"]
                profile = Path(invocation[invocation.index("--agent-file") + 1])
                self.assertEqual(profile.name, filename)
                self.assertTrue(profile.is_file())
                self.assertEqual(detail["risk"]["level"], risk)


if __name__ == "__main__":
    unittest.main()
