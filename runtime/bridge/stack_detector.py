from __future__ import annotations

from pathlib import Path


def detect_stack(repo_path: str) -> str:
    """Detect the primary tech stack of a repository from marker files."""
    root = Path(repo_path)

    # 1. Python
    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        return "python"

    # 2. Go
    if (root / "go.mod").exists():
        return "go"

    # 3. TypeScript (package.json + tsconfig.json)
    if (root / "package.json").exists() and (root / "tsconfig.json").exists():
        return "typescript"

    # 4. JavaScript (package.json alone)
    if (root / "package.json").exists():
        return "javascript"

    # 5. Rust
    if (root / "Cargo.toml").exists():
        return "rust"

    # 6. Java
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        return "java"

    return "unknown"
