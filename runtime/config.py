from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_PROVIDER_TIMEOUTS: Dict[str, int] = {
}
DIVISION_DIMENSIONS = (
    "security",
    "performance",
    "maintainability",
    "correctness",
    "error-handling",
)


@dataclass(frozen=True)
class ReviewPolicy:
    timeout_seconds: int = 180
    stall_timeout_seconds: int = 900
    poll_interval_seconds: float = 1.0
    review_hard_timeout_seconds: int = 1800
    enforce_findings_contract: bool = False
    max_retries: int = 1
    high_escalation_threshold: int = 1
    require_non_empty_findings: bool = True
    max_provider_parallelism: int = 0
    provider_timeouts: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PROVIDER_TIMEOUTS))
    allow_paths: List[str] = field(default_factory=lambda: ["."])
    provider_permissions: Dict[str, Dict[str, str]] = field(default_factory=dict)
    enforcement_mode: str = "strict"
    perspectives: Dict[str, str] = field(default_factory=dict)
    chain: bool = False
    debate: bool = False
    divide: str = ""


@dataclass(frozen=True)
class ReviewConfig:
    providers: List[str] = field(default_factory=lambda: ["claude", "codex", "gemini", "opencode", "qwen"])
    artifact_base: str = "reports/review"
    policy: ReviewPolicy = field(default_factory=ReviewPolicy)


_DEFAULT_GLOBAL_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mco")


def _warn(message: str) -> None:
    print(f"[mco] warning: {message}", file=sys.stderr)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge override into base. Nested dicts are merged, not replaced."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _strip_yaml_comments(line: str) -> str:
    if "#" not in line:
        return line
    in_single = False
    in_double = False
    result_chars: List[str] = []
    for char in line:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            break
        result_chars.append(char)
    return "".join(result_chars)


def _parse_yaml_scalar(raw_value: str) -> Any:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in ("'", '"') and value[-1] == value[0]:
        return ast.literal_eval(value)
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_yaml_scalar(part.strip()) for part in inner.split(",") if part.strip()]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def _fallback_yaml_load(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        cleaned = _strip_yaml_comments(raw).rstrip()
        if cleaned.strip():
            lines.append(cleaned)

    def _indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _parse_node(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return None, index
        line = lines[index]
        if line.lstrip().startswith("- "):
            return _parse_list(index, indent)
        return _parse_dict(index, indent)

    def _parse_dict(index: int, indent: int) -> tuple[Dict[str, Any], int]:
        result: Dict[str, Any] = {}
        while index < len(lines):
            line = lines[index]
            current_indent = _indent_of(line)
            if current_indent < indent or line.lstrip().startswith("- "):
                break
            if current_indent != indent:
                raise ValueError(f"invalid indentation near: {line.strip()}")
            stripped = line.strip()
            if ":" not in stripped:
                raise ValueError(f"invalid mapping entry: {stripped}")
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            index += 1
            if rest:
                result[key] = _parse_yaml_scalar(rest)
                continue
            if index < len(lines) and _indent_of(lines[index]) > current_indent:
                value, index = _parse_node(index, current_indent + 2)
                result[key] = value
            else:
                result[key] = None
        return result, index

    def _parse_list(index: int, indent: int) -> tuple[List[Any], int]:
        items: List[Any] = []
        while index < len(lines):
            line = lines[index]
            current_indent = _indent_of(line)
            stripped = line.strip()
            if current_indent < indent or not stripped.startswith("- "):
                break
            if current_indent != indent:
                raise ValueError(f"invalid list indentation near: {stripped}")
            content = stripped[2:].strip()
            index += 1
            if not content:
                value, index = _parse_node(index, current_indent + 2)
                items.append(value)
                continue
            if ":" not in content:
                items.append(_parse_yaml_scalar(content))
                continue

            item: Dict[str, Any] = {}
            key, rest = content.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            if rest:
                item[key] = _parse_yaml_scalar(rest)
            else:
                item[key] = None
            last_key = key

            while index < len(lines):
                next_line = lines[index]
                next_indent = _indent_of(next_line)
                next_stripped = next_line.strip()
                if next_indent < current_indent + 2:
                    break
                if next_indent > current_indent + 2:
                    if last_key is None:
                        raise ValueError(f"invalid nested block near: {next_stripped}")
                    value, index = _parse_node(index, current_indent + 4)
                    item[last_key] = value
                    last_key = None
                    continue
                if next_stripped.startswith("- "):
                    break
                if ":" not in next_stripped:
                    raise ValueError(f"invalid mapping entry: {next_stripped}")
                sub_key, sub_rest = next_stripped.split(":", 1)
                sub_key = sub_key.strip()
                sub_rest = sub_rest.strip()
                index += 1
                if sub_rest:
                    item[sub_key] = _parse_yaml_scalar(sub_rest)
                    last_key = None
                else:
                    item[sub_key] = None
                    last_key = sub_key
            items.append(item)
        return items, index

    if not lines:
        return {}
    parsed, final_index = _parse_node(0, _indent_of(lines[0]))
    if final_index != len(lines):
        raise ValueError("unexpected trailing YAML content")
    return parsed


def _load_yaml_text(text: str) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        try:
            return _fallback_yaml_load(text)
        except Exception:
            return None
    try:
        return yaml.safe_load(text)
    except Exception:
        return None


def _load_json_file(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _load_yaml_file(path: str) -> Dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    data = _load_yaml_text(text)
    if data is None:
        raise ValueError("yaml_parse_error")
    return data if isinstance(data, dict) else {}


def _normalize_agent_registration(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    transport = str(raw.get("transport", "shim")).strip().lower() or "shim"
    if transport not in ("shim", "acp"):
        return None
    entry: Dict[str, Any] = {"name": name, "transport": transport}
    command = raw.get("command")
    if isinstance(command, str) and command.strip():
        entry["command"] = command.strip()
    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        entry["model"] = model.strip()
    permission_keys = raw.get("permission_keys")
    if isinstance(permission_keys, list):
        entry["permission_keys"] = [str(item).strip() for item in permission_keys if str(item).strip()]
    timeout = raw.get("timeout")
    if isinstance(timeout, int) and timeout > 0:
        entry["timeout"] = timeout
    if "command" not in entry and "model" not in entry:
        return None
    return entry


def load_agent_registrations(
    repo_root: str,
    global_config_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    global_dir = global_config_dir or _DEFAULT_GLOBAL_CONFIG_DIR
    candidates = [
        (os.path.join(repo_root, ".mco", "agents.yaml"), "agents"),
        (os.path.join(repo_root, ".mcorc.yaml"), "config"),
        (os.path.join(global_dir, "agents.yaml"), "agents"),
    ]

    for path, mode in candidates:
        if not os.path.isfile(path):
            continue
        try:
            payload = _load_yaml_file(path)
        except Exception as exc:
            _warn(f"failed to parse YAML config '{path}': {exc}")
            continue
        agents_value = payload.get("agents", []) if mode == "config" else payload.get("agents", payload)
        if not isinstance(agents_value, list):
            _warn(f"ignored invalid agents payload in '{path}'")
            continue
        normalized = []
        for item in agents_value:
            agent = _normalize_agent_registration(item)
            if agent is not None:
                normalized.append(agent)
        if normalized or "agents" in payload:
            return normalized
    return []


def load_config_files(
    repo_root: str,
    global_config_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and merge config from global (~/.mco/config.json) and project (.mcorc.json).

    Merge order: global < project. Nested dicts (e.g. policy) are deep-merged.
    Returns empty dict if no config files found.
    """
    global_dir = global_config_dir or _DEFAULT_GLOBAL_CONFIG_DIR
    merged: Dict[str, Any] = {}

    # Global JSON config
    global_path = os.path.join(global_dir, "config.json")
    if os.path.isfile(global_path):
        try:
            data = _load_json_file(global_path)
            if data:
                merged = _deep_merge(merged, data)
        except (json.JSONDecodeError, OSError):
            pass

    # Project JSON config
    project_path = os.path.join(repo_root, ".mcorc.json")
    if os.path.isfile(project_path):
        try:
            data = _load_json_file(project_path)
            if data:
                merged = _deep_merge(merged, data)
        except (json.JSONDecodeError, OSError):
            pass

    # Project YAML config
    project_yaml_path = os.path.join(repo_root, ".mcorc.yaml")
    if os.path.isfile(project_yaml_path):
        try:
            data = _load_yaml_file(project_yaml_path)
            if data:
                merged = _deep_merge(merged, data)
        except Exception as exc:
            _warn(f"failed to parse YAML config '{project_yaml_path}': {exc}")

    agent_candidate_paths = [
        os.path.join(repo_root, ".mco", "agents.yaml"),
        os.path.join(repo_root, ".mcorc.yaml"),
        os.path.join(global_dir, "agents.yaml"),
    ]
    if any(os.path.isfile(path) for path in agent_candidate_paths):
        merged["agents"] = load_agent_registrations(repo_root, global_config_dir=global_dir)

    return merged
