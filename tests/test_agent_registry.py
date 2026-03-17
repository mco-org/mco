from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.adapters import adapter_registry
from runtime.adapters.custom import CommandShimAdapter
from runtime.adapters.ollama import OllamaAdapter
from runtime.cli import _load_available_agents, main
from runtime.config import load_agent_registrations, load_config_files


class TestAgentConfigLoading(unittest.TestCase):
    def test_load_agents_from_project_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / ".mco"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "agents.yaml").write_text(
                """
agents:
  - name: ollama-codellama
    transport: shim
    command: "mco-ollama-shim codellama"
    timeout: 300
    model: codellama
    permission_keys: [sandbox]
""".strip(),
                encoding="utf-8",
            )
            agents = load_agent_registrations(tmp)
            self.assertEqual(len(agents), 1)
            self.assertEqual(agents[0]["name"], "ollama-codellama")
            self.assertEqual(agents[0]["transport"], "shim")
            self.assertEqual(agents[0]["model"], "codellama")
            self.assertEqual(agents[0]["timeout"], 300)

    def test_project_yaml_overrides_mcorc_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".mcorc.yaml").write_text(
                """
agents:
  - name: from-root
    command: "root-agent"
    transport: shim
""".strip(),
                encoding="utf-8",
            )
            agents_dir = Path(tmp) / ".mco"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "agents.yaml").write_text(
                """
agents:
  - name: from-dot-mco
    command: "dot-mco-agent"
    transport: acp
""".strip(),
                encoding="utf-8",
            )
            agents = load_agent_registrations(tmp)
            self.assertEqual([item["name"] for item in agents], ["from-dot-mco"])

    @patch("runtime.config._warn")
    def test_invalid_yaml_warns_and_returns_empty(self, mock_warn) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".mcorc.yaml").write_text("agents: [", encoding="utf-8")
            agents = load_agent_registrations(tmp)
            self.assertEqual(agents, [])
            self.assertTrue(mock_warn.called)

    @patch("runtime.config._warn")
    def test_missing_yaml_dependency_warns(self, mock_warn) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / ".mco"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "agents.yaml").write_text("agents: []", encoding="utf-8")
            with patch("runtime.config._load_yaml_text", return_value=None):
                agents = load_agent_registrations(tmp)
            self.assertEqual(agents, [])
            self.assertTrue(mock_warn.called)

    def test_load_config_files_includes_yaml_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".mcorc.yaml").write_text(
                """
providers:
  - claude
agents:
  - name: my-lint-bot
    command: "my-lint-bot --acp"
    transport: acp
""".strip(),
                encoding="utf-8",
            )
            config = load_config_files(tmp)
            self.assertEqual(config["providers"], ["claude"])
            self.assertEqual(config["agents"][0]["name"], "my-lint-bot")


class TestAgentRegistry(unittest.TestCase):
    def test_registry_merges_builtin_cli_and_config_agents(self) -> None:
        registrations = [
            {"name": "my-lint-bot", "command": "my-lint-bot --acp", "transport": "acp"},
            {"name": "ollama-codellama", "transport": "shim", "model": "codellama"},
        ]
        reg = adapter_registry(
            transport="acp",
            extra_agents={"cli-bot": ["cli-bot", "--acp"]},
            configured_agents=registrations,
        )
        self.assertIn("claude", reg)
        self.assertIn("cli-bot", reg)
        self.assertIn("my-lint-bot", reg)
        self.assertIn("ollama-codellama", reg)

    def test_command_takes_priority_over_model_in_shim_registry(self) -> None:
        reg = adapter_registry(
            transport="shim",
            configured_agents=[
                {
                    "name": "hybrid-bot",
                    "transport": "shim",
                    "command": "hybrid-bot --stdio",
                    "model": "llama3",
                }
            ],
        )
        self.assertIsInstance(reg["hybrid-bot"], CommandShimAdapter)

    def test_command_takes_priority_over_model_in_acp_registry_for_shim_agent(self) -> None:
        reg = adapter_registry(
            transport="acp",
            configured_agents=[
                {
                    "name": "hybrid-bot",
                    "transport": "shim",
                    "command": "hybrid-bot --stdio",
                    "model": "llama3",
                }
            ],
        )
        self.assertIsInstance(reg["hybrid-bot"], CommandShimAdapter)

    def test_model_only_agent_uses_ollama_adapter(self) -> None:
        reg = adapter_registry(
            transport="shim",
            configured_agents=[
                {
                    "name": "ollama-only",
                    "transport": "shim",
                    "model": "codellama",
                }
            ],
        )
        self.assertIsInstance(reg["ollama-only"], OllamaAdapter)

    def test_incomplete_agent_registration_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / ".mco"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "agents.yaml").write_text(
                """
agents:
  - name: broken-agent
    transport: shim
""".strip(),
                encoding="utf-8",
            )
            agents = load_agent_registrations(tmp)
            self.assertEqual(agents, [])
            available = _load_available_agents(tmp)
            self.assertNotIn("broken-agent", [item["name"] for item in available])


class TestAgentCliSubcommands(unittest.TestCase):
    @patch("runtime.cli._load_available_agents")
    def test_agent_list_outputs_builtin_and_custom(self, mock_load) -> None:
        mock_load.return_value = [
            {"name": "claude", "source": "builtin", "transport": "shim"},
            {"name": "ollama-codellama", "source": "config", "transport": "shim"},
        ]
        stdout_buf = io.StringIO()
        with contextlib.redirect_stdout(stdout_buf):
            exit_code = main(["agent", "list", "--repo", ".", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout_buf.getvalue())
        self.assertEqual(payload[0]["name"], "claude")
        self.assertEqual(payload[1]["name"], "ollama-codellama")

    @patch("runtime.cli._check_agent")
    def test_agent_check_outputs_presence(self, mock_check) -> None:
        mock_check.return_value = {
            "name": "ollama-codellama",
            "ready": True,
            "detected": True,
            "binary_path": "/usr/local/bin/ollama",
            "transport": "shim",
        }
        stdout_buf = io.StringIO()
        with contextlib.redirect_stdout(stdout_buf):
            exit_code = main(["agent", "check", "ollama-codellama", "--repo", ".", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout_buf.getvalue())
        self.assertEqual(payload["name"], "ollama-codellama")
        self.assertTrue(payload["ready"])
