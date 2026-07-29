#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path


class ReleaseRefError(ValueError):
    pass


def validate_release_ref(root: Path, github_ref: str) -> str:
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    if not github_ref.startswith("refs/tags/"):
        raise ReleaseRefError(
            "release ref must be a tag ref: {}".format(github_ref or "<unset>")
        )
    expected_ref = "refs/tags/v{}".format(version)
    if github_ref != expected_ref:
        raise ReleaseRefError(
            "release tag mismatch: expected {}, got {}".format(expected_ref, github_ref)
        )
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    dated_heading = re.search(
        r"^## \[{}\] - (\d{{4}}-\d{{2}}-\d{{2}})\s*$".format(re.escape(version)),
        changelog,
        re.MULTILINE,
    )
    if not dated_heading:
        raise ReleaseRefError(
            "CHANGELOG.md must contain a dated [{}] release heading".format(version)
        )
    release_date = dated_heading.group(1)
    try:
        date.fromisoformat(release_date)
    except ValueError as exc:
        raise ReleaseRefError(
            "CHANGELOG.md release date is invalid: {}".format(release_date)
        ) from exc
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the npm release ref.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    try:
        version = validate_release_ref(args.root, os.environ.get("GITHUB_REF", ""))
    except ReleaseRefError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("release ref check: PASS (v{})".format(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
