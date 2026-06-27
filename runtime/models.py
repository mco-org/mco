from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _run_model_probe(binary: str, args: List[str], timeout: int = 15) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [binary] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "binary_not_found", "stdout": "", "stderr": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "stdout": "", "stderr": ""}
    except OSError as exc:
        return {"ok": False, "error": "probe_failed", "stdout": "", "stderr": str(exc)}
    if result.returncode != 0:
        return {
            "ok": False,
            "error": "command_failed",
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
        }
    return {"ok": True, "stdout": result.stdout or "", "stderr": result.stderr or "", "returncode": 0}


def _parse_codex_models(stdout: str) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return models
    items = data.get("models", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return models
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = item.get("slug") or item.get("id") or item.get("name") or item.get("model")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        levels = item.get("supported_reasoning_levels", [])
        reasoning_levels = [
            str(level.get("effort"))
            for level in levels
            if isinstance(level, dict) and level.get("effort")
        ] if isinstance(levels, list) else []
        entry: Dict[str, Any] = {"id": model_id.strip()}
        display_name = item.get("display_name") or item.get("name")
        if isinstance(display_name, str) and display_name.strip():
            entry["display_name"] = display_name.strip()
        if item.get("default_reasoning_level"):
            entry["default_reasoning_level"] = item.get("default_reasoning_level")
        if reasoning_levels:
            entry["supported_reasoning_levels"] = reasoning_levels
        if item.get("visibility"):
            entry["visibility"] = item.get("visibility")
        models.append(entry)
    return models


def _parse_pi_models(stdout: str) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2 or parts[0].lower() == "provider":
            continue
        entry: Dict[str, Any] = {"id": parts[1], "provider": parts[0]}
        if len(parts) > 2:
            entry["context"] = parts[2]
        if len(parts) > 3:
            entry["max_output"] = parts[3]
        if len(parts) > 4:
            entry["thinking"] = parts[4]
        if len(parts) > 5:
            entry["images"] = parts[5]
        models.append(entry)
    return models


def _parse_hermes_catalog(payload: object) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []

    def add_model(model_id: object, provider: object = "") -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            return
        entry: Dict[str, Any] = {"id": model_id.strip()}
        if isinstance(provider, str) and provider.strip():
            entry["provider"] = provider.strip()
        models.append(entry)

    def walk(value: object, provider: str = "") -> None:
        if isinstance(value, dict):
            current_provider = value.get("provider") or value.get("provider_id") or value.get("providerId") or provider
            add_model(value.get("id") or value.get("model") or value.get("slug"), current_provider)
            for key, child in value.items():
                next_provider = str(key) if key in {
                    "anthropic",
                    "codewiz-anthropic",
                    "codewiz-gemini",
                    "openai",
                    "openrouter",
                    "seal",
                } else str(current_provider or "")
                walk(child, next_provider)
        elif isinstance(value, list):
            for child in value:
                walk(child, provider)

    walk(payload)
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in models:
        key = (str(item.get("provider", "")), str(item.get("id", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _codex_default_model() -> Dict[str, str]:
    text = _read_text(Path.home() / ".codex" / "config.toml")
    match = re.search(r'(?m)^\s*model\s*=\s*["\']([^"\']+)["\']', text)
    reasoning = re.search(r'(?m)^\s*model_reasoning_effort\s*=\s*["\']([^"\']+)["\']', text)
    result: Dict[str, str] = {}
    if match:
        result["model"] = match.group(1)
    if reasoning:
        result["reasoning"] = reasoning.group(1)
    return result


def _pi_default_model() -> Dict[str, str]:
    text = _read_text(Path.home() / ".pi" / "agent" / "settings.json")
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: Dict[str, str] = {}
    for source, target in (
        ("defaultProvider", "provider"),
        ("defaultModel", "model"),
        ("defaultThinkingLevel", "thinking"),
    ):
        value = payload.get(source) if isinstance(payload, dict) else None
        if isinstance(value, str) and value.strip():
            result[target] = value.strip()
    return result


def _hermes_default_model() -> Dict[str, str]:
    text = _read_text(Path.home() / ".hermes" / "config.yaml")
    result: Dict[str, str] = {}
    in_top_model = False
    for raw_line in text.splitlines():
        if re.match(r"^model:\s*$", raw_line):
            in_top_model = True
            continue
        if in_top_model and raw_line and not raw_line.startswith((" ", "\t")):
            in_top_model = False
        if not in_top_model:
            continue
        default_match = re.match(r'^\s+default:\s*["\']?([^"\'\n#]+)', raw_line)
        provider_match = re.match(r'^\s+provider:\s*["\']?([^"\'\n#]+)', raw_line)
        if default_match:
            result["model"] = default_match.group(1).strip()
        if provider_match:
            result["provider"] = provider_match.group(1).strip()
    if result:
        return result
    provider = re.search(r'(?m)^[ \t]*(?:default_)?provider[ \t]*:[ \t]*["\']?([^"\'\n#]+)', text)
    model = re.search(r'(?m)^[ \t]*(?:default_)?model[ \t]*:[ \t]*["\']?([^"\'\n#]+)', text)
    if provider:
        result["provider"] = provider.group(1).strip()
    if model:
        result["model"] = model.group(1).strip()
    return result


def discover_models(provider: str) -> Dict[str, Any]:
    provider_name = provider.strip()
    if provider_name == "codex":
        probe = _run_model_probe("codex", ["debug", "models"], timeout=20)
        if not probe.get("ok"):
            return {
                "ok": False,
                "provider": "codex",
                "error": probe.get("error", "probe_failed"),
                "models": [],
                "default": _codex_default_model(),
                "source": "codex debug models",
            }
        return {
            "ok": True,
            "provider": "codex",
            "models": _parse_codex_models(str(probe.get("stdout", ""))),
            "default": _codex_default_model(),
            "source": "codex debug models",
        }

    if provider_name == "pi":
        probe = _run_model_probe("pi", ["--list-models"], timeout=30)
        if not probe.get("ok"):
            return {
                "ok": False,
                "provider": "pi",
                "error": probe.get("error", "probe_failed"),
                "models": [],
                "default": _pi_default_model(),
                "source": "pi --list-models",
            }
        return {
            "ok": True,
            "provider": "pi",
            "models": _parse_pi_models(str(probe.get("stdout", ""))),
            "default": _pi_default_model(),
            "source": "pi --list-models",
        }

    if provider_name == "hermes":
        catalog_path = Path.home() / ".hermes" / "cache" / "model_catalog.json"
        text = _read_text(catalog_path)
        models: List[Dict[str, Any]] = []
        if text:
            try:
                models = _parse_hermes_catalog(json.loads(text))
            except json.JSONDecodeError:
                models = []
        if not models:
            return {
                "ok": False,
                "provider": "hermes",
                "error": "model_catalog_not_found",
                "models": [],
                "default": _hermes_default_model(),
                "source": str(catalog_path),
                "note": "Hermes has no stable non-interactive model-list command; refresh/use its catalog cache first.",
            }
        return {
            "ok": True,
            "provider": "hermes",
            "models": models,
            "default": _hermes_default_model(),
            "source": str(catalog_path),
        }

    return {"ok": False, "error": "model_discovery_not_supported", "provider": provider_name, "models": []}


__all__ = [
    "discover_models",
    "_parse_codex_models",
    "_parse_hermes_catalog",
    "_parse_pi_models",
    "_run_model_probe",
]
