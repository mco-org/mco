import unittest
from importlib.resources import files

from runtime.skill_agents import (
    calling_agent_binaries,
    calling_agent_skill_directories,
    known_skill_agents,
    skills_cli_package,
)


class SkillAgentsTests(unittest.TestCase):
    def test_manifest_file_is_packaged_under_runtime_data(self) -> None:
        path = files("runtime").joinpath("data", "skill_calling_agents.json")
        self.assertTrue(path.is_file())

    def test_known_agents_include_mco_calling_agents(self) -> None:
        agents = known_skill_agents()
        for agent_id in ("codex", "pi", "hermes-agent", "github-copilot", "qwen-code", "cursor"):
            self.assertIn(agent_id, agents)

    def test_cursor_maps_agent_binary(self) -> None:
        pairs = dict(calling_agent_binaries())
        self.assertEqual(pairs.get("agent"), "cursor")

    def test_skill_directories_match_pinned_skills_cli_contract(self) -> None:
        self.assertEqual(skills_cli_package(), "skills@1.5.15")
        locations = set(calling_agent_skill_directories())
        self.assertIn(("codex", "global", ".agents/skills", None), locations)
        self.assertIn(("codex", "legacy-global", ".codex/skills", None), locations)
        self.assertIn(("pi", "global", ".pi/agent/skills", None), locations)
        self.assertIn(("hermes-agent", "global", ".hermes/skills", "HERMES_HOME"), locations)
        self.assertIn(("github-copilot", "global", ".agents/skills", None), locations)
        self.assertIn(
            ("github-copilot", "legacy-global", ".copilot/skills", None),
            locations,
        )
        self.assertIn(("qwen-code", "global", ".qwen/skills", None), locations)


if __name__ == "__main__":
    unittest.main()
