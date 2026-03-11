from __future__ import annotations

import tempfile
from pathlib import Path

from runtime.bridge.stack_detector import detect_stack


def test_python_from_pyproject() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "pyproject.toml").touch()
        assert detect_stack(d) == "python"


def test_python_from_requirements() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "requirements.txt").touch()
        assert detect_stack(d) == "python"


def test_go_from_gomod() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "go.mod").touch()
        assert detect_stack(d) == "go"


def test_typescript_from_tsconfig() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "package.json").touch()
        (Path(d) / "tsconfig.json").touch()
        assert detect_stack(d) == "typescript"


def test_javascript_from_package_json() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "package.json").touch()
        assert detect_stack(d) == "javascript"


def test_rust_from_cargo() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "Cargo.toml").touch()
        assert detect_stack(d) == "rust"


def test_java_from_pom() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "pom.xml").touch()
        assert detect_stack(d) == "java"


def test_java_from_gradle() -> None:
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "build.gradle").touch()
        assert detect_stack(d) == "java"


def test_unknown_fallback() -> None:
    with tempfile.TemporaryDirectory() as d:
        assert detect_stack(d) == "unknown"
