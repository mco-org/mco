from __future__ import annotations

import unittest

from runtime.config import DEFAULT_PROVIDER_TIMEOUTS, ReviewConfig


class ConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        cfg = ReviewConfig()
        self.assertEqual(cfg.providers, ["claude", "codex"])
        self.assertEqual(cfg.artifact_base, "reports/review")
        self.assertEqual(cfg.policy.max_provider_parallelism, 0)
        self.assertEqual(cfg.policy.provider_timeouts, DEFAULT_PROVIDER_TIMEOUTS)
        self.assertEqual(cfg.policy.stall_timeout_seconds, 900)
        self.assertEqual(cfg.policy.poll_interval_seconds, 1.0)
        self.assertEqual(cfg.policy.review_hard_timeout_seconds, 1800)
        self.assertFalse(cfg.policy.enforce_findings_contract)
        self.assertEqual(cfg.policy.allow_paths, ["."])
        self.assertEqual(cfg.policy.provider_permissions, {})
        self.assertEqual(cfg.policy.enforcement_mode, "strict")

    def test_default_mutable_fields_are_isolated(self) -> None:
        first = ReviewConfig()
        second = ReviewConfig()
        first.providers.append("qwen")
        first.policy.provider_timeouts["qwen"] = 900
        self.assertEqual(second.providers, ["claude", "codex"])
        self.assertEqual(second.policy.provider_timeouts, DEFAULT_PROVIDER_TIMEOUTS)


if __name__ == "__main__":
    unittest.main()
