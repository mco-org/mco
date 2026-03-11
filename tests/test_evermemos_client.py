from __future__ import annotations

import json
import unittest

from runtime.bridge.evermemos_client import EverMemosClient, MCO_FINDING_PREFIX, MCO_AGENT_SCORE_PREFIX


class TestEverMemosClientInit(unittest.TestCase):
    def test_instantiation(self):
        client = EverMemosClient(api_key="test-key")
        self.assertEqual(client.api_key, "test-key")

    def test_missing_api_key_raises(self):
        import os
        env_backup = os.environ.pop("EVERMEMOS_API_KEY", None)
        try:
            with self.assertRaises(ValueError) as ctx:
                EverMemosClient(api_key="")
            self.assertIn("EVERMEMOS_API_KEY", str(ctx.exception))
        finally:
            if env_backup is not None:
                os.environ["EVERMEMOS_API_KEY"] = env_backup


class TestSerializationHelpers(unittest.TestCase):
    """These are static methods — no MCP connection needed."""

    def test_serialize_finding_roundtrip(self):
        original = {"finding_hash": "sha256:abc", "title": "test", "severity": "high"}
        serialized = EverMemosClient.serialize_finding(original)
        self.assertTrue(serialized.startswith(MCO_FINDING_PREFIX))
        deserialized = EverMemosClient.deserialize_finding(serialized)
        self.assertEqual(deserialized, original)

    def test_deserialize_non_finding_raises(self):
        with self.assertRaises(ValueError):
            EverMemosClient.deserialize_finding("some random text")

    def test_is_finding_entry(self):
        self.assertTrue(EverMemosClient.is_finding_entry("[MCO-FINDING] {}"))
        self.assertFalse(EverMemosClient.is_finding_entry("[MCO-AGENT-SCORE] {}"))
        self.assertFalse(EverMemosClient.is_finding_entry("random text"))

    def test_serialize_agent_score_roundtrip(self):
        original = {"agent": "claude", "rate": 0.8}
        serialized = EverMemosClient.serialize_agent_score(original)
        self.assertTrue(serialized.startswith(MCO_AGENT_SCORE_PREFIX))
        deserialized = EverMemosClient.deserialize_agent_score(serialized)
        self.assertEqual(deserialized, original)

    def test_is_agent_score_entry(self):
        self.assertTrue(EverMemosClient.is_agent_score_entry("[MCO-AGENT-SCORE] {}"))
        self.assertFalse(EverMemosClient.is_agent_score_entry("[MCO-FINDING] {}"))

    def test_serialize_finding_preserves_unicode(self):
        original = {"title": "SQL注入漏洞"}
        serialized = EverMemosClient.serialize_finding(original)
        deserialized = EverMemosClient.deserialize_finding(serialized)
        self.assertEqual(deserialized["title"], "SQL注入漏洞")


if __name__ == "__main__":
    unittest.main()
