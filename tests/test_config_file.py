# tests/test_config_file.py
"""Tests for config file loading and merging."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from runtime.config import load_config_files


class TestLoadConfigFiles(unittest.TestCase):
    def test_no_config_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_config_files(tmp)
            self.assertEqual(result, {})

    def test_project_config_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"providers": ["claude"], "quiet": True}
            with open(os.path.join(tmp, ".mcorc.json"), "w") as f:
                json.dump(cfg, f)
            result = load_config_files(tmp)
            self.assertEqual(result["providers"], ["claude"])
            self.assertTrue(result["quiet"])

    def test_global_config_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            global_dir = os.path.join(tmp, ".mco")
            os.makedirs(global_dir)
            cfg = {"transport": "acp"}
            with open(os.path.join(global_dir, "config.json"), "w") as f:
                json.dump(cfg, f)
            result = load_config_files("/nonexistent", global_config_dir=global_dir)
            self.assertEqual(result["transport"], "acp")

    def test_project_overrides_global(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            global_dir = os.path.join(tmp, "global", ".mco")
            os.makedirs(global_dir)
            with open(os.path.join(global_dir, "config.json"), "w") as f:
                json.dump({"providers": ["claude"], "quiet": False}, f)
            with open(os.path.join(tmp, ".mcorc.json"), "w") as f:
                json.dump({"providers": ["claude", "codex"]}, f)
            result = load_config_files(tmp, global_config_dir=global_dir)
            self.assertEqual(result["providers"], ["claude", "codex"])
            self.assertFalse(result["quiet"])  # global value preserved when not overridden

    def test_invalid_json_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, ".mcorc.json"), "w") as f:
                f.write("not valid json {{{")
            result = load_config_files(tmp)
            self.assertEqual(result, {})
