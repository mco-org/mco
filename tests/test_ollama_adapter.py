from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from runtime.adapters.ollama import OllamaAdapter
from runtime.contracts import NormalizeContext, TaskInput


class TestOllamaAdapter(unittest.TestCase):
    @patch("runtime.adapters.shim.shutil.which", return_value="/usr/local/bin/ollama")
    @patch("runtime.adapters.ollama.subprocess.run")
    def test_detect_checks_binary_and_model(self, mock_run, mock_which) -> None:
        mock_run.return_value.stdout = "NAME ID SIZE MODIFIED\ncodellama abc 3GB now\n"
        mock_run.return_value.returncode = 0
        adapter = OllamaAdapter(provider_id="ollama-codellama", model="codellama")
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertTrue(presence.auth_ok)
        self.assertEqual(presence.binary_path, "/usr/local/bin/ollama")

    @patch("runtime.adapters.shim.shutil.which", return_value="/usr/local/bin/ollama")
    @patch("runtime.adapters.ollama.subprocess.run")
    def test_detect_returns_auth_false_when_model_is_missing(self, mock_run, mock_which) -> None:
        mock_run.side_effect = [
            SimpleNamespace(stdout="ollama version 0.1.0\n", stderr="", returncode=0),
            SimpleNamespace(stdout="NAME ID SIZE MODIFIED\nother-model abc 3GB now\n", stderr="", returncode=0),
        ]
        adapter = OllamaAdapter(provider_id="ollama-codellama", model="codellama")
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertFalse(presence.auth_ok)
        self.assertEqual(presence.reason, "model_not_found")

    def test_build_command_uses_model(self) -> None:
        adapter = OllamaAdapter(provider_id="ollama-codellama", model="codellama")
        task = TaskInput(
            task_id="task-1",
            prompt="review this",
            repo_root=".",
            target_paths=["."],
        )
        command = adapter._build_command(task)
        self.assertEqual(command[:3], ["ollama", "run", "codellama"])
        self.assertIn("review this", command[-1])

    def test_normalize_parses_findings(self) -> None:
        adapter = OllamaAdapter(provider_id="ollama-codellama", model="codellama")
        findings = adapter.normalize(
            '{"findings":[{"finding_id":"f1","severity":"high","category":"bug","title":"Bug",'
            '"evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.8,"fingerprint":"fp"}]}',
            NormalizeContext(task_id="task-1", provider="claude", repo_root=".", raw_ref="raw/ollama.stdout.log"),  # type: ignore[arg-type]
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "Bug")
