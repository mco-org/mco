from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_skill_format import validate_skill_dir


class SkillFormatTests(unittest.TestCase):
    def _write_skill(self, root: Path, body: str) -> Path:
        skill_dir = root / "skills" / "mco-cli"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
        return skill_dir

    def test_valid_skill_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = self._write_skill(
                root,
                "---\nname: mco-cli\ndescription: test skill\n---\n"
                "See [installation](references/installation.md).\n",
            )
            (skill_dir / "references").mkdir()
            (skill_dir / "references" / "installation.md").write_text("# install\n", encoding="utf-8")
            self.assertEqual(validate_skill_dir(skill_dir), [])

    def test_bundled_skill_passes(self) -> None:
        skill_dir = Path(__file__).resolve().parents[1] / "skills" / "mco-cli"
        self.assertEqual(validate_skill_dir(skill_dir), [])

    def test_missing_frontmatter_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = self._write_skill(root, "# no frontmatter\n")
            errors = validate_skill_dir(skill_dir)
            self.assertTrue(any("frontmatter" in item for item in errors))

    def test_missing_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = self._write_skill(
                root,
                "---\nname: mco-cli\ndescription: test\n---\n"
                "[missing](references/missing.md)\n",
            )
            errors = validate_skill_dir(skill_dir)
            self.assertTrue(any("missing referenced file" in item for item in errors))

    def test_invalid_execution_mode_example_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = self._write_skill(
                root,
                "---\nname: mco-cli\ndescription: test\n---\n"
                "```bash\nmco run --execution-mode unsafe --providers codex\n```\n",
            )
            errors = validate_skill_dir(skill_dir)
            self.assertTrue(any("invalid --execution-mode" in item for item in errors))

    def test_model_qualified_agent_example_is_explicit_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = self._write_skill(
                root,
                "---\nname: mco-cli\ndescription: test\n---\n"
                "```bash\nmco run --agent fast=pi:model --prompt \"task\"\n```\n",
            )
            self.assertEqual(validate_skill_dir(skill_dir), [])


if __name__ == "__main__":
    unittest.main()
