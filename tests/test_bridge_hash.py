from __future__ import annotations

import unittest

from runtime.bridge.finding_hash import compute_finding_hash, normalize_title


class TestNormalizeTitle(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize_title("SQL Injection"), "sql injection")

    def test_collapses_whitespace(self):
        self.assertEqual(normalize_title("  SQL   injection  "), "sql injection")

    def test_strips(self):
        self.assertEqual(normalize_title("  hello  "), "hello")


class TestComputeFindingHash(unittest.TestCase):
    def test_basic_hash(self):
        h = compute_finding_hash(
            repo="my-repo",
            file_path="src/api/user.py",
            category="security",
            title="SQL injection in query builder",
        )
        self.assertTrue(h.startswith("sha256:"))
        self.assertEqual(len(h), len("sha256:") + 64)

    def test_deterministic(self):
        args = dict(repo="r", file_path="f.py", category="bug", title="Title")
        self.assertEqual(compute_finding_hash(**args), compute_finding_hash(**args))

    def test_title_normalization_makes_hash_stable(self):
        h1 = compute_finding_hash(repo="r", file_path="f", category="c", title="SQL Injection")
        h2 = compute_finding_hash(repo="r", file_path="f", category="c", title="  sql   injection  ")
        self.assertEqual(h1, h2)

    def test_different_file_different_hash(self):
        h1 = compute_finding_hash(repo="r", file_path="a.py", category="c", title="t")
        h2 = compute_finding_hash(repo="r", file_path="b.py", category="c", title="t")
        self.assertNotEqual(h1, h2)

    def test_different_category_different_hash(self):
        h1 = compute_finding_hash(repo="r", file_path="f", category="security", title="t")
        h2 = compute_finding_hash(repo="r", file_path="f", category="bug", title="t")
        self.assertNotEqual(h1, h2)

    def test_backslash_normalized(self):
        """Windows paths should hash identically to Unix paths."""
        h1 = compute_finding_hash(repo="r", file_path="src\\api\\user.py", category="c", title="t")
        h2 = compute_finding_hash(repo="r", file_path="src/api/user.py", category="c", title="t")
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
