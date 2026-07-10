from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from runtime.cli import main
from runtime.skill_health import check_skill_health


class SkillHealthTests(unittest.TestCase):
    def test_disabled_returns_skipped(self) -> None:
        health, drift = check_skill_health(enabled=False)
        self.assertEqual(health["status"], "skipped")
        self.assertEqual(drift["status"], "skipped")
        self.assertFalse(health["enabled"])

    def test_reference_match_reports_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("---\nname: mco-cli\n---\n", encoding="utf-8")

            install_dir = root / ".cursor" / "skills" / "mco-cli"
            install_dir.mkdir(parents=True)
            install_path = install_dir / "SKILL.md"
            install_path.write_text(skill_path.read_text(encoding="utf-8"), encoding="utf-8")

            health, drift = check_skill_health(
                enabled=True,
                package_root=root,
                cwd=root,
            )

        self.assertEqual(health["status"], "ok")
        self.assertEqual(drift["status"], "ok")
        self.assertIn("project-cursor", drift["matched"])
        self.assertEqual(drift["drifted"], [])

    def test_reference_drift_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            reference = skill_dir / "SKILL.md"
            reference.write_text("reference-content\n", encoding="utf-8")

            install_dir = root / ".claude" / "skills" / "mco-cli"
            install_dir.mkdir(parents=True)
            install = install_dir / "SKILL.md"
            install.write_text("stale-content\n", encoding="utf-8")

            health, drift = check_skill_health(
                enabled=True,
                package_root=root,
                cwd=root,
            )

        self.assertEqual(health["status"], "drift")
        self.assertEqual(drift["status"], "drift")
        self.assertIn("project-claude", drift["drifted"])

    def test_missing_reference_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            health, drift = check_skill_health(
                enabled=True,
                package_root=root,
                cwd=root,
            )

        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["reason"], "reference_skill_not_found")
        self.assertEqual(drift["status"], "ok")

    def test_bundled_only_ignores_cwd_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "package"
            bundled_dir = package_root / "skills" / "mco-cli"
            bundled_dir.mkdir(parents=True)
            (bundled_dir / "SKILL.md").write_text("bundled\n", encoding="utf-8")

            repo_skill = root / "skills" / "mco-cli"
            repo_skill.mkdir(parents=True)
            (repo_skill / "SKILL.md").write_text("repo\n", encoding="utf-8")

            health, _ = check_skill_health(
                enabled=True,
                package_root=package_root,
                cwd=root,
                reference_preference="bundled_only",
            )

        self.assertEqual(
            Path(str(health["reference"]["path"])).resolve(),
            (bundled_dir / "SKILL.md").resolve(),
        )


class CliDoctorSkillTests(unittest.TestCase):
    def test_doctor_without_skill_health_omits_skill_fields(self) -> None:
        output = io.StringIO()
        with patch("runtime.cli._doctor_provider_presence", return_value={}):
            with redirect_stdout(output):
                exit_code = main(["doctor", "--providers", "claude", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertNotIn("skill_health", payload)
        self.assertNotIn("skill_drift", payload)

    def test_doctor_skill_health_json_includes_skill_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill-body\n", encoding="utf-8")

            output = io.StringIO()
            with patch("runtime.cli._doctor_provider_presence", return_value={}):
                with redirect_stdout(output):
                    exit_code = main([
                        "doctor",
                        "--repo", str(root),
                        "--providers", "claude",
                        "--skill-health",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertIn("skill_health", payload)
        self.assertIn("skill_drift", payload)
        self.assertTrue(payload["skill_health"]["enabled"])
        self.assertEqual(
            Path(str(payload["skill_health"]["reference"]["path"])).resolve(),
            (skill_dir / "SKILL.md").resolve(),
        )

    def test_doctor_skill_health_human_output_is_concise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill-body\n", encoding="utf-8")

            output = io.StringIO()
            with patch("runtime.cli._doctor_provider_presence", return_value={}):
                with redirect_stdout(output):
                    exit_code = main([
                        "doctor",
                        "--repo", str(root),
                        "--providers", "claude",
                        "--skill-health",
                    ])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("Skill Check", text)
        self.assertIn("status: ok", text)
        self.assertIn("reference:", text)


if __name__ == "__main__":
    unittest.main()
