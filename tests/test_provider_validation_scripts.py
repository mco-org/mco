from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from runtime.adapters import adapter_registry
from runtime.contracts import PROVIDER_IDS
from runtime.contracts import TaskInput
from runtime.execution_modes import execution_permissions


ROOT = Path(__file__).resolve().parents[1]


class ProviderValidationScriptTests(unittest.TestCase):
    def _run_capability_probes(
        self,
        *,
        code_fenced_c2_provider: str | None = None,
        plain_text_c2_provider: str | None = None,
        prose_c2_providers: tuple[str, ...] = (),
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as tmp:
            test_root = Path(tmp)
            scripts_dir = test_root / "scripts"
            fake_bin_dir = test_root / "bin"
            scripts_dir.mkdir()
            fake_bin_dir.mkdir()

            script_path = scripts_dir / "run_capability_probes.sh"
            shutil.copy2(ROOT / "scripts" / "run_capability_probes.sh", script_path)

            fake_driver = fake_bin_dir / "fake-provider"
            fake_driver.write_text(
                textwrap.dedent(
                    r"""
                    #!/usr/bin/env bash
                    set -u

                    provider="$(basename "$0")"
                    if [ "$provider" = "agent" ]; then
                      provider="cursor"
                    fi

                    for arg in "$@"; do
                      if [ "$arg" = "--version" ] || [ "$arg" = "-v" ]; then
                        echo "$provider 1.2.3"
                        exit 0
                      fi
                    done

                    args="$*"
                    prose_c2=false
                    case ",${FAKE_PROSE_C2_PROVIDERS:-}," in
                      *",$provider,"*) prose_c2=true ;;
                    esac
                    if [[ "$args" == *"--output-format stream-json"* ]]; then
                      printf '%s\n%s\n' '{"type":"message"}' '{"type":"result"}'
                      exit 0
                    fi

                    if [[ "$args" == *"--output-last-message"* ]]; then
                      while [ "$#" -gt 0 ]; do
                        if [ "$1" = "--output-last-message" ]; then
                          printf '%s\n' '{"probe":"c2","ok":true}' > "$2"
                          break
                        fi
                        shift
                      done
                      printf '%s\n' '{"type":"result"}'
                      exit 0
                    fi

                    if [[ "$args" == *"Return JSON object"* ]]; then
                      if [ "${FAKE_PLAIN_TEXT_C2_PROVIDER:-}" = "$provider" ]; then
                        printf '%s\n' 'model said {"probe":"c2","ok":true}'
                      elif [ "${FAKE_CODE_FENCED_C2_PROVIDER:-}" = "$provider" ]; then
                        printf '%s\n' '{"type":"result","text":"```json\n{\"probe\":\"c2\",\"ok\":true}\n```"}'
                      elif [ "$prose_c2" = true ]; then
                        if [ "$provider" = "gemini" ] || [ "$provider" = "hermes" ]; then
                          printf '%s\n' 'model said {"probe":"c2","ok":true}'
                        else
                          printf '%s\n' '{"type":"result","text":"model said {\"probe\":\"c2\",\"ok\":true}"}'
                        fi
                      elif [ "$provider" = "grok" ]; then
                        if [[ "$args" == *"--json-schema"* ]]; then
                          printf '%s\n' '{"type":"result","structuredOutput":{"probe":"c2","ok":true}}'
                        else
                          printf '%s\n' '{"type":"result","text":"```json\n{\"probe\":\"c2\",\"ok\":true}\n```"}'
                        fi
                      elif [ "$provider" = "gemini" ] && [[ "$args" != *"--output-format json"* ]]; then
                        printf '%s\n' 'model said {"probe":"c2","ok":true}'
                      elif [ "$provider" = "copilot" ] || [ "$provider" = "cursor" ] || [ "$provider" = "gemini" ] || [ "$provider" = "opencode" ] || [ "$provider" = "qwen" ] || [ "$provider" = "pi" ]; then
                        printf '%s\n' '{"type":"result","response":"{\"probe\":\"c2\",\"ok\":true}"}'
                      else
                        printf '%s\n' '{"probe":"c2","ok":true}'
                      fi
                      exit 0
                    fi

                    echo "OK"
                    """,
                ).lstrip(),
                encoding="utf-8",
            )
            fake_driver.chmod(0o755)
            for binary in (
                "claude", "codex", "gemini", "opencode", "qwen", "hermes", "pi",
                "copilot", "grok", "agent",
            ):
                (fake_bin_dir / binary).symlink_to(fake_driver)

            env = os.environ.copy()
            env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env['PATH']}"
            env["HOME"] = str(test_root)
            env["PROBE_CWD"] = str(test_root)
            if code_fenced_c2_provider is not None:
                env["FAKE_CODE_FENCED_C2_PROVIDER"] = code_fenced_c2_provider
            if plain_text_c2_provider is not None:
                env["FAKE_PLAIN_TEXT_C2_PROVIDER"] = plain_text_c2_provider
            if prose_c2_providers:
                env["FAKE_PROSE_C2_PROVIDERS"] = ",".join(prose_c2_providers)

            completed = subprocess.run(
                ["bash", str(script_path)],
                cwd=test_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            probe_roots = list((test_root / "docs" / "probes").iterdir())
            self.assertEqual(len(probe_roots), 1)
            probe_root = probe_roots[0]
            artifacts: dict[str, object] = {
                "lock_summary": (probe_root / "lock-summary.yaml").read_text(encoding="utf-8"),
                "schema_c2": json.loads(
                    (probe_root / "schema_c2.json").read_text(encoding="utf-8"),
                ),
                "summary": (probe_root / "summary.md").read_text(encoding="utf-8"),
            }
            for provider in PROVIDER_IDS:
                artifacts[provider] = json.loads(
                    (probe_root / provider / "C2" / "result.json").read_text(encoding="utf-8"),
                )
            return completed, artifacts

    def test_capability_probe_provider_list_matches_builtin_contract(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        match = re.search(r"^providers=\(([^)]*)\)$", script, re.MULTILINE)

        self.assertIsNotNone(match)
        self.assertEqual(tuple(shlex.split(match.group(1))), tuple(PROVIDER_IDS))

    def test_capability_probe_covers_required_tiers_for_every_builtin_provider(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        probes = set(re.findall(r'run_probe\s+"([^"]+)"\s+"(C[0-6])"', script))

        for provider in PROVIDER_IDS:
            with self.subTest(provider=provider):
                self.assertTrue(
                    {(provider, "C0"), (provider, "C1"), (provider, "C2")} <= probes,
                )

    def test_c1_probe_commands_match_read_only_adapter_policy(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        commands = dict(
            re.findall(r'^run_probe "([^"]+)" "C1" "([^"]+)" "', script, re.MULTILINE),
        )

        for provider, adapter in adapter_registry().items():
            with self.subTest(provider=provider):
                actual = shlex.split(commands[provider])
                actual[0] = adapter.binary_name
                permissions = execution_permissions(provider, "read_only") or {}
                task = TaskInput(
                    task_id="capability-probe",
                    prompt="Reply with exactly OK",
                    repo_root="$PROBE_CWD",
                    target_paths=[],
                    metadata={"provider_permissions": permissions},
                )
                self.assertEqual(actual, adapter._build_command(task))

    def test_c2_probes_preserve_read_only_permission_flags(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        expected_fragments = {
            "claude": ("--permission-mode plan",),
            "codex": ("--ask-for-approval never", "--sandbox read-only"),
            "gemini": ("--approval-mode plan",),
            "opencode": ("--agent plan", "--dir '$PROBE_CWD'"),
            "qwen": ("--approval-mode plan",),
            "pi": ("--tools read,grep,find,ls",),
            "copilot": ("--deny-tool=write", "--deny-tool=shell"),
            "grok": ("--permission-mode plan",),
            "cursor": ("--mode ask", "--sandbox enabled"),
        }

        for provider, fragments in expected_fragments.items():
            with self.subTest(provider=provider):
                match = re.search(
                    rf'run_probe "{provider}" "C2"\s*(?:\\\s*)?"((?:\\.|[^"])*)"',
                    script,
                )
                self.assertIsNotNone(match)
                for fragment in fragments:
                    self.assertIn(fragment, match.group(1))

    def test_c2_probe_commands_request_native_json_output(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")

        for provider in ("gemini", "copilot", "grok", "cursor"):
            with self.subTest(provider=provider):
                match = re.search(
                    rf'run_probe "{provider}" "C2"\s*\\\s*\n\s*"((?:\\.|[^"])*)"',
                    script,
                )
                self.assertIsNotNone(match)
                self.assertIn("--output-format json", match.group(1))

    def test_c2_rejects_plain_text_pseudo_json(self) -> None:
        _, artifacts = self._run_capability_probes(plain_text_c2_provider="copilot")

        self.assertEqual(artifacts["copilot"]["status"], "FAIL")

    def test_c2_schema_constrains_expected_probe_values(self) -> None:
        _, artifacts = self._run_capability_probes()
        schema = artifacts["schema_c2"]

        self.assertEqual(
            {
                name: schema["properties"][name].get("const")
                for name in ("probe", "ok")
            },
            {"probe": "c2", "ok": True},
        )

    def test_grok_c2_uses_schema_backed_structured_output(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        match = re.search(
            r'run_probe "grok" "C2"\s*\\\s*\n\s*"((?:\\.|[^"])*)"',
            script,
        )

        self.assertIsNotNone(match)
        self.assertIn(
            r'''--json-schema \"\$(cat '$schema_file')\"''',
            match.group(1),
        )
        completed, artifacts = self._run_capability_probes()
        self.assertEqual((completed.returncode, artifacts["grok"]["status"]), (0, "PASS"))

    def test_grok_c2_rejects_code_fenced_text_in_json_envelope(self) -> None:
        _, artifacts = self._run_capability_probes(code_fenced_c2_provider="grok")

        self.assertEqual(artifacts["grok"]["status"], "FAIL")

    def test_c2_rejects_prose_pseudo_json_for_weak_providers(self) -> None:
        weak_providers = ("gemini", "opencode", "qwen", "hermes", "pi")
        _, artifacts = self._run_capability_probes(prose_c2_providers=weak_providers)

        self.assertEqual(
            {provider: artifacts[provider]["status"] for provider in weak_providers},
            {provider: "FAIL" for provider in weak_providers},
        )

    def test_aggregate_exit_code_requires_all_required_tiers_to_pass(self) -> None:
        passing_run, passing_artifacts = self._run_capability_probes()
        blocked_run, artifacts = self._run_capability_probes(
            plain_text_c2_provider="copilot",
        )

        self.assertEqual(passing_run.returncode, 0)
        self.assertEqual(
            {
                provider: passing_artifacts[provider]["status"]
                for provider in ("gemini", "opencode", "qwen", "hermes", "pi")
            },
            {provider: "PASS" for provider in ("gemini", "opencode", "qwen", "hermes", "pi")},
        )
        self.assertNotEqual(blocked_run.returncode, 0)
        lock_summary = str(artifacts["lock_summary"])
        for provider in PROVIDER_IDS:
            with self.subTest(provider=provider):
                self.assertIn(f"  {provider}:\n", lock_summary)
        self.assertRegex(
            lock_summary,
            r"(?s)  copilot:.*?C2: FAIL.*?gate_status: BLOCKED",
        )

    def test_copilot_c0_probe_denies_write_and_shell_tools(self) -> None:
        script = (ROOT / "scripts" / "run_capability_probes.sh").read_text(encoding="utf-8")
        match = re.search(
            r'^run_probe "copilot" "C0" "([^"]+)" ""$',
            script,
            re.MULTILINE,
        )

        self.assertIsNotNone(match)
        command = match.group(1)
        self.assertNotIn("--allow-all-tools", command)
        self.assertIn("--deny-tool=write", command)
        self.assertIn("--deny-tool=shell", command)

    def test_parallel_benchmark_defaults_to_read_only_builtin_providers(self) -> None:
        script = (ROOT / "scripts" / "run_step5_parallel_benchmark.sh").read_text(encoding="utf-8")
        match = re.search(r'^PROVIDERS="\$\{1:-([^}]*)\}"$', script, re.MULTILINE)

        self.assertIsNotNone(match)
        providers = tuple(match.group(1).split(","))
        expected = tuple(
            provider for provider in PROVIDER_IDS
            if execution_permissions(provider, "read_only") is not None
        )
        self.assertEqual(providers, expected)
        self.assertNotIn("hermes", providers)
        self.assertIn("Hermes is covered by capability probes", script)

    def test_benchmark_workflow_is_manual_only_until_self_hosted_macos_returns(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "benchmark.yml").read_text(encoding="utf-8")

        self.assertNotRegex(workflow, r"(?m)^\s+schedule:")
        self.assertRegex(workflow, r"(?m)^\s+workflow_dispatch:")
        self.assertRegex(workflow, r"(?m)^\s+- self-hosted$")
        self.assertRegex(workflow, r"(?m)^\s+- macOS$")
        self.assertIn("Manual-only until a self-hosted macOS runner is available.", workflow)
        self.assertIn("Hermes is excluded because review/read_only fails closed", workflow)


if __name__ == "__main__":
    unittest.main()
