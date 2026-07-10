#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALID_EXECUTION_MODES = {"read_only", "write", "yolo"}
IMPLICIT_PROVIDER_PATTERNS = (
    re.compile(r"mco\s+(run|review)(?!.*--providers)", re.IGNORECASE),
    re.compile(r"--providers\s+\$?\{?default", re.IGNORECASE),
)


def _parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        raise ValueError("frontmatter must open with ---")
    end = content.find("\n---", 3)
    if end == -1:
        raise ValueError("frontmatter must close with ---")
    block = content[3:end].strip("\n")
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def _code_blocks(content: str) -> list[str]:
    return re.findall(r"```(?:bash|text)?\n(.*?)```", content, re.DOTALL)


def _collect_reference_links(content: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\((references/[^)]+)\)", content)


def _validate_examples(content: str) -> list[str]:
    errors: list[str] = []
    blocks = _code_blocks(content)
    if not blocks:
        return errors
    for block in blocks:
        for pattern in IMPLICIT_PROVIDER_PATTERNS:
            if pattern.search(block):
                errors.append("examples must not use implicit provider selection")
                break
        for match in re.finditer(r"--execution-mode\s+([^\s`]+)", block):
            raw = match.group(1).strip("`'\".,;")
            for mode in raw.split("|"):
                cleaned = mode.strip(" `'\".,;")
                if cleaned and cleaned not in VALID_EXECUTION_MODES:
                    errors.append("invalid --execution-mode example: {}".format(cleaned))
    return errors


def validate_skill_dir(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        return ["missing SKILL.md"]

    content = skill_path.read_text(encoding="utf-8")
    try:
        frontmatter = _parse_frontmatter(content)
    except ValueError as exc:
        return [str(exc)]

    if frontmatter.get("name") != "mco-cli":
        errors.append('frontmatter name must be "mco-cli"')
    if not frontmatter.get("description"):
        errors.append("frontmatter description must be non-empty")

    for reference in _collect_reference_links(content):
        if not (skill_dir / reference).is_file():
            errors.append("missing referenced file: {}".format(reference))

    errors.extend(_validate_examples(content))

    reference_dir = skill_dir / "references"
    if reference_dir.is_dir():
        for reference_path in sorted(reference_dir.glob("*.md")):
            errors.extend(_validate_examples(reference_path.read_text(encoding="utf-8")))

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate bundled mco-cli Skill format")
    parser.add_argument("skill_dir", nargs="?", default="skills/mco-cli")
    args = parser.parse_args(argv)
    errors = validate_skill_dir(Path(args.skill_dir))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Skill format check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
