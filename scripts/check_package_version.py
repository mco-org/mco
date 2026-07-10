#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _read_pyproject_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        raise ValueError("pyproject.toml version not found")
    return match.group(1)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    package_version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    pyproject_version = _read_pyproject_version(root)
    from runtime import __version__ as runtime_version

    versions = {
        "package.json": package_version,
        "runtime.__version__": runtime_version,
        "pyproject.toml": pyproject_version,
    }
    unique = set(versions.values())
    if len(unique) != 1:
        print("package version mismatch:", file=sys.stderr)
        for label, value in versions.items():
            print("  {} = {}".format(label, value), file=sys.stderr)
        return 1
    print("package version check: PASS ({})".format(package_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
