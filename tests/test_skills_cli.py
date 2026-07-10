from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runtime.cli import main


class SkillsCliTests(unittest.TestCase):
    def test_skills_read_prints_bundled_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: mco-cli\n---\nbody\n", encoding="utf-8")
            output = io.StringIO()
            with patch("runtime.cli._package_root", return_value=root):
                with redirect_stdout(output):
                    exit_code = main(["skills", "read"])
            self.assertEqual(exit_code, 0)
            self.assertIn("name: mco-cli", output.getvalue())

    def test_skills_read_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill-body\n", encoding="utf-8")
            output = io.StringIO()
            with patch("runtime.cli._package_root", return_value=root):
                with redirect_stdout(output):
                    exit_code = main(["skills", "read", "--json"])
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["skill"], "mco-cli")
            self.assertEqual(payload["content"], "skill-body\n")

    def test_skills_status_json_includes_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill-body\n", encoding="utf-8")
            output = io.StringIO()
            with patch("runtime.cli._package_root", return_value=root):
                with redirect_stdout(output):
                    exit_code = main(["skills", "status", "--repo", tmp, "--json"])
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertIn("skill_health", payload)
            self.assertIn("skill_drift", payload)

    def test_skills_sync_without_agent_returns_selection_error(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["skills", "sync", "--json"])
        self.assertEqual(exit_code, 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["error"]["subtype"], "agent_selection_required")

    def test_skills_sync_dry_run_returns_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill-body\n", encoding="utf-8")
            output = io.StringIO()
            with patch("runtime.cli._package_root", return_value=root):
                with redirect_stdout(output):
                    exit_code = main(["skills", "sync", "--agent", "codex", "--dry-run", "--json"])
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["dry_run"])
            self.assertIn("--copy", payload["argv"])


if __name__ == "__main__":
    unittest.main()
