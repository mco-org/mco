from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_package_version import _read_pyproject_version


class PackageVersionTests(unittest.TestCase):
    def test_pyproject_matches_package_and_runtime(self) -> None:
        root = Path(__file__).resolve().parent.parent
        package_version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
        pyproject_version = _read_pyproject_version(root)
        from runtime import __version__ as runtime_version

        self.assertEqual(package_version, pyproject_version)
        self.assertEqual(package_version, runtime_version)
        self.assertEqual(package_version, "0.11.0")


if __name__ == "__main__":
    unittest.main()
