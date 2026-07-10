import unittest
from importlib.resources import files

from runtime.skill_agents import calling_agent_binaries, known_skill_agents


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


if __name__ == "__main__":
    unittest.main()
