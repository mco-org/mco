from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = ROOT / "scripts" / "check_release_ref.py"


class ReleaseRefTests(unittest.TestCase):
    def _write_release_files(self, root: Path, *, changelog: str) -> None:
        (root / "package.json").write_text(
            json.dumps({"name": "@example/package", "version": "1.2.3"}),
            encoding="utf-8",
        )
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")

    def _run_check(self, root: Path, github_ref: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GITHUB_REF"] = github_ref
        return subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--root", str(root)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_matching_tag_with_dated_changelog_entry_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_release_files(
                root,
                changelog="# Changelog\n\n## [1.2.3] - 2026-07-29\n",
            )
            result = self._run_check(root, "refs/tags/v1.2.3")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("release ref check: PASS (v1.2.3)", result.stdout)

    def test_branch_ref_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_release_files(
                root,
                changelog="# Changelog\n\n## [1.2.3] - 2026-07-29\n",
            )
            result = self._run_check(root, "refs/heads/main")

        self.assertEqual(result.returncode, 1)
        self.assertIn("release ref must be a tag ref", result.stderr)

    def test_tag_must_match_package_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_release_files(
                root,
                changelog="# Changelog\n\n## [1.2.3] - 2026-07-29\n",
            )
            result = self._run_check(root, "refs/tags/v1.2.4")

        self.assertEqual(result.returncode, 1)
        self.assertIn("release tag mismatch: expected refs/tags/v1.2.3", result.stderr)

    def test_version_mentioned_only_under_unreleased_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_release_files(
                root,
                changelog=(
                    "# Changelog\n\n"
                    "## [Unreleased]\n\n"
                    "- Prepare v1.2.3 for release.\n"
                ),
            )
            result = self._run_check(root, "refs/tags/v1.2.3")

        self.assertEqual(result.returncode, 1)
        self.assertIn("CHANGELOG.md must contain a dated [1.2.3] release heading", result.stderr)

    def test_invalid_changelog_date_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_release_files(
                root,
                changelog="# Changelog\n\n## [1.2.3] - 2026-02-30\n",
            )
            result = self._run_check(root, "refs/tags/v1.2.3")

        self.assertEqual(result.returncode, 1)
        self.assertIn("CHANGELOG.md release date is invalid: 2026-02-30", result.stderr)


class PublishWorkflowTests(unittest.TestCase):
    def _workflow(self) -> str:
        return (ROOT / ".github" / "workflows" / "publish-npm.yml").read_text(
            encoding="utf-8"
        )

    def _publish_script(self) -> str:
        lines = self._workflow().splitlines()
        step_start = lines.index("      - name: Publish package")
        step_end = next(
            (
                index
                for index in range(step_start + 1, len(lines))
                if lines[index].startswith("      - name: ")
            ),
            len(lines),
        )
        step = lines[step_start:step_end]
        self.assertIn("        run: |", step)
        run_start = step.index("        run: |") + 1
        return "\n".join(
            line[10:] if line.startswith("          ") else line
            for line in step[run_start:]
        )

    def _run_publish_script(
        self,
        *,
        view_result: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log_path = root / "npm.log"
            node = bin_dir / "node"
            npm = bin_dir / "npm"
            node.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *\".name\"* ]]; then\n"
                "  printf '%s\\n' '@example/package'\n"
                "else\n"
                "  printf '%s\\n' '1.2.3'\n"
                "fi\n",
                encoding="utf-8",
            )
            npm.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_NPM_LOG\"\n"
                "case \"$1\" in\n"
                "  view)\n"
                "    case \"$FAKE_NPM_VIEW_RESULT\" in\n"
                "      exists) printf '%s\\n' '1.2.3' ;;\n"
                "      mismatch) printf '%s\\n' '9.9.9' ;;\n"
                "      missing) printf '%s\\n' 'npm error code E404' >&2; exit 1 ;;\n"
                "      network) printf '%s\\n' 'npm error code EAI_AGAIN' >&2; exit 1 ;;\n"
                "    esac\n"
                "    ;;\n"
                "  publish) ;;\n"
                "  *) printf '%s\\n' \"unexpected npm command: $*\" >&2; exit 2 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            node.chmod(0o755)
            npm.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["FAKE_NPM_LOG"] = str(log_path)
            env["FAKE_NPM_VIEW_RESULT"] = view_result
            result = subprocess.run(
                ["bash", "-e", "-u", "-o", "pipefail", "-c", self._publish_script()],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            log = log_path.read_text(encoding="utf-8").splitlines()

        return result, log

    def test_already_published_exact_version_skips_publish(self) -> None:
        result, npm_commands = self._run_publish_script(view_result="exists")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            npm_commands,
            ["view @example/package@1.2.3 version --prefer-online"],
        )
        self.assertIn(
            "@example/package@1.2.3 is already published; skipping npm publish.",
            result.stdout,
        )

    def test_registry_query_failure_refuses_to_publish(self) -> None:
        result, npm_commands = self._run_publish_script(view_result="network")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            npm_commands,
            ["view @example/package@1.2.3 version --prefer-online"],
        )
        self.assertIn(
            "Unable to determine whether @example/package@1.2.3 is published; refusing to publish.",
            result.stdout,
        )
        self.assertNotIn("EAI_AGAIN", result.stdout + result.stderr)

    def test_unexpected_successful_registry_response_refuses_to_publish(self) -> None:
        result, npm_commands = self._run_publish_script(view_result="mismatch")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            npm_commands,
            ["view @example/package@1.2.3 version --prefer-online"],
        )
        self.assertIn(
            "Registry returned an unexpected version for @example/package@1.2.3; refusing to publish.",
            result.stdout,
        )

    def test_explicit_e404_publishes_missing_exact_version(self) -> None:
        result, npm_commands = self._run_publish_script(view_result="missing")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            npm_commands,
            [
                "view @example/package@1.2.3 version --prefer-online",
                "publish --access public",
            ],
        )
        self.assertIn(
            "@example/package@1.2.3 is not published; publishing it now.",
            result.stdout,
        )

    def test_publish_workflow_only_triggers_from_a_published_release(self) -> None:
        workflow = self._workflow()

        self.assertNotIn("  workflow_dispatch:", workflow)
        self.assertIn("  release:\n    types: [published]", workflow)

    def test_release_ref_check_runs_before_publish(self) -> None:
        workflow = self._workflow()

        check_command = "python3 scripts/check_release_ref.py"
        publish_command = "npm publish --access public"
        self.assertIn(check_command, workflow)
        self.assertLess(workflow.index(check_command), workflow.index(publish_command))

    def test_npm_latest_is_checked_after_publish(self) -> None:
        workflow = self._workflow()

        publish_command = "npm publish --access public"
        registry_command = 'npm view "${PACKAGE_NAME}@latest" version --prefer-online'
        self.assertIn(registry_command, workflow)
        self.assertLess(workflow.index(publish_command), workflow.index(registry_command))

    def test_published_package_gets_clean_install_smoke(self) -> None:
        workflow = self._workflow()

        registry_command = 'npm view "${PACKAGE_NAME}@latest" version --prefer-online'
        temp_command = 'INSTALL_DIR="$(mktemp -d)"'
        install_command = 'npm install "${PACKAGE_NAME}@${PACKAGE_VERSION}"'
        version_command = '"$MCO_BIN" --version'
        help_command = '"$MCO_BIN" --help'
        self.assertIn(temp_command, workflow)
        self.assertIn(install_command, workflow)
        self.assertIn(version_command, workflow)
        self.assertIn(help_command, workflow)
        self.assertLess(workflow.index(registry_command), workflow.index(temp_command))
        self.assertLess(workflow.index(temp_command), workflow.index(install_command))
        self.assertLess(workflow.index(install_command), workflow.index(version_command))


class ReleaseGuideTests(unittest.TestCase):
    def test_post_publish_failure_uses_same_workflow_run_retry(self) -> None:
        guide = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
        normalized_guide = " ".join(guide.split())

        self.assertIn("Re-run failed jobs on that same workflow run", normalized_guide)
        self.assertIn("registry confirms the exact version", normalized_guide)
        self.assertIn("skips `npm publish`", normalized_guide)
        self.assertIn(
            "continues with the `latest` and clean-install checks",
            normalized_guide,
        )
        self.assertNotIn("workflow_dispatch", guide)


if __name__ == "__main__":
    unittest.main()
