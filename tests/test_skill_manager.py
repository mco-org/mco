from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from runtime.skill_manager import (
    build_skill_sync_argv,
    normalize_skill_agents,
    read_bundled_skill,
    skill_status,
    sync_bundled_skill,
)


class SkillManagerContractTests(unittest.TestCase):
    def test_build_sync_command_uses_local_source_copy_and_explicit_agents(self) -> None:
        argv = build_skill_sync_argv(
            package_root=Path("/pkg/mco"),
            agents=["claude-code", "codex"],
        )
        self.assertEqual(
            argv,
            [
                "npx",
                "-y",
                "skills@1.5.15",
                "add",
                "/pkg/mco",
                "--skill",
                "mco-cli",
                "--copy",
                "--global",
                "--yes",
                "--agent",
                "claude-code",
                "--agent",
                "codex",
            ],
        )

    def test_sync_requires_explicit_agent_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "agent_selection_required"):
            build_skill_sync_argv(Path("/pkg/mco"), [])

    def test_sync_rejects_unsafe_agent_name(self) -> None:
        with self.assertRaises(ValueError):
            build_skill_sync_argv(Path("/pkg/mco"), ["--all"])

    def test_sync_rejects_unknown_agent_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown skill agent"):
            build_skill_sync_argv(Path("/pkg/mco"), ["gemini"])

    def test_sync_accepts_supported_calling_agents(self) -> None:
        argv = build_skill_sync_argv(
            Path("/pkg/mco"),
            ["pi", "hermes-agent", "github-copilot", "qwen-code"],
        )
        self.assertIn("--agent", argv)
        self.assertIn("pi", argv)
        self.assertIn("hermes-agent", argv)

    def test_duplicate_agent_removal_preserves_order(self) -> None:
        agents = normalize_skill_agents(["codex", "claude-code", "codex", "claude-code"])
        self.assertEqual(agents, ["codex", "claude-code"])

    def test_control_character_rejection(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid skill agent"):
            normalize_skill_agents(["codex\u0000"])

    def test_read_bundled_skill_returns_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("---\nname: mco-cli\n---\nbody\n", encoding="utf-8")
            content = read_bundled_skill(root)
            self.assertIn("name: mco-cli", content)

    def test_skill_status_delegates_to_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "mco-cli"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("skill\n", encoding="utf-8")
            payload = skill_status(root, cwd=root)
            self.assertIn("skill_health", payload)
            self.assertIn("skill_drift", payload)

    def test_skill_status_uses_bundled_reference_over_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "package"
            bundled_dir = package_root / "skills" / "mco-cli"
            bundled_dir.mkdir(parents=True)
            (bundled_dir / "SKILL.md").write_text("bundled-reference\n", encoding="utf-8")

            repo_skill = root / "skills" / "mco-cli"
            repo_skill.mkdir(parents=True)
            (repo_skill / "SKILL.md").write_text("repo-reference\n", encoding="utf-8")

            payload = skill_status(package_root, cwd=root)
            reference_path = payload["skill_health"]["reference"]["path"]
            self.assertEqual(Path(reference_path).resolve(), (bundled_dir / "SKILL.md").resolve())

    def test_sync_dry_run_does_not_invoke_runner(self) -> None:
        runner = MagicMock()
        result = sync_bundled_skill(
            Path("/pkg/mco"),
            ["codex"],
            dry_run=True,
            runner=runner,
        )
        runner.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["status"], "planned")

    def test_sync_invokes_runner_without_shell(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        runner = MagicMock(return_value=completed)
        sync_bundled_skill(
            Path("/pkg/mco"),
            ["codex"],
            dry_run=False,
            runner=runner,
        )
        runner.assert_called_once()
        call_kwargs = runner.call_args.kwargs
        self.assertNotIn("shell", call_kwargs)
        self.assertFalse(call_kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
