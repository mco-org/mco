from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional


@dataclass(frozen=True)
class AnswerDelta:
    text: str


@dataclass(frozen=True)
class AnswerTransport:
    deltas: tuple[AnswerDelta, ...]
    final_answer: str
    status: str
    usage: Optional[dict[str, int]]


def _json_lines(raw: str) -> Iterable[dict[str, Any]]:
    for line in raw.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def _normalize_usage(value: object) -> Optional[dict[str, int]]:
    if not isinstance(value, Mapping):
        return None

    def integer(*keys: str) -> Optional[int]:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, bool):
                continue
            if isinstance(candidate, int) and candidate >= 0:
                return candidate
        return None

    prompt = integer("prompt_tokens", "input_tokens")
    completion = integer("completion_tokens", "output_tokens")
    total = integer("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    result: dict[str, int] = {}
    if prompt is not None:
        result["prompt_tokens"] = prompt
    if completion is not None:
        result["completion_tokens"] = completion
    if total is not None:
        result["total_tokens"] = total
    return result or None


def _event_usage(payload: Mapping[str, Any]) -> Optional[dict[str, int]]:
    usage = payload.get("usage")
    return _normalize_usage(usage)


def decode_plain_text(raw: str) -> AnswerTransport:
    deltas = (AnswerDelta(raw),) if raw else ()
    return AnswerTransport(deltas, raw, "succeeded", None)


def decode_codex_events(raw: str) -> AnswerTransport:
    deltas: list[AnswerDelta] = []
    final_answer: Optional[str] = None
    usage: Optional[dict[str, int]] = None
    status = "running"

    for payload in _json_lines(raw):
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            continue
        normalized_type = event_type.lower()
        item = payload.get("item")
        item = item if isinstance(item, Mapping) else payload
        item_type = item.get("type")

        if normalized_type in {"item.delta", "response.output_text.delta", "output_text.delta"}:
            if item_type in (None, "agent_message", "assistant_message", "message"):
                delta = payload.get("delta")
                if not isinstance(delta, str):
                    delta = item.get("delta")
                if isinstance(delta, str):
                    deltas.append(AnswerDelta(delta))
        elif normalized_type == "item.completed" and item_type in ("agent_message", "assistant_message", "message"):
            text = item.get("text")
            if isinstance(text, str):
                final_answer = text
        elif normalized_type in {"response.completed", "response.done"}:
            response = payload.get("response")
            if isinstance(response, Mapping):
                response_text = response.get("output_text")
                if isinstance(response_text, str):
                    final_answer = response_text
                usage = _normalize_usage(response.get("usage")) or usage
            usage = _event_usage(payload) or usage
            status = "succeeded"
        elif normalized_type == "turn.completed":
            usage = _event_usage(payload) or usage
            status = "succeeded"
        elif normalized_type in {"error", "turn.failed", "response.failed"}:
            status = "failed"

    if final_answer is None:
        final_answer = "".join(delta.text for delta in deltas)
    if not deltas and final_answer:
        deltas.append(AnswerDelta(final_answer))
    return AnswerTransport(tuple(deltas), final_answer, status, usage)


def decode_pi_events(raw: str) -> AnswerTransport:
    deltas: list[AnswerDelta] = []
    final_answer: Optional[str] = None
    usage: Optional[dict[str, int]] = None
    status = "running"

    for payload in _json_lines(raw):
        event_type = payload.get("type")
        if event_type == "message_update":
            assistant_event = payload.get("assistantMessageEvent")
            if isinstance(assistant_event, Mapping) and assistant_event.get("type") == "text_delta":
                delta = assistant_event.get("delta")
                if isinstance(delta, str):
                    deltas.append(AnswerDelta(delta))
        elif event_type == "agent_end":
            messages = payload.get("messages")
            if isinstance(messages, list):
                for message in reversed(messages):
                    if not isinstance(message, Mapping) or message.get("role") != "assistant":
                        continue
                    content = message.get("content")
                    if not isinstance(content, list):
                        continue
                    parts = [
                        block.get("text", "")
                        for block in content
                        if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str)
                    ]
                    if parts:
                        final_answer = "".join(parts)
                        break
            usage = _event_usage(payload) or usage
            status = "succeeded"
        elif event_type in {"error", "agent_error"}:
            status = "failed"

    if final_answer is None:
        final_answer = "".join(delta.text for delta in deltas)
    if not deltas and final_answer:
        deltas.append(AnswerDelta(final_answer))
    return AnswerTransport(tuple(deltas), final_answer, status, usage)


def decode_acp_events(updates: Iterable[Mapping[str, Any]]) -> AnswerTransport:
    deltas: list[AnswerDelta] = []
    final_answer: Optional[str] = None
    usage: Optional[dict[str, int]] = None
    status = "running"

    for update in updates:
        params = update.get("params") if update.get("method") == "session/update" else update
        if not isinstance(params, Mapping):
            continue
        state = params.get("state")
        if state == "idle":
            status = "succeeded"
        elif state == "error":
            status = "failed"
        content = params.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, Mapping) or block.get("type") not in ("text", "text_delta"):
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    deltas.append(AnswerDelta(text))
        usage = _event_usage(params) or usage
        explicit_final = params.get("final_answer")
        if isinstance(explicit_final, str):
            final_answer = explicit_final

    if final_answer is None:
        final_answer = "".join(delta.text for delta in deltas)
    if not deltas and final_answer:
        deltas.append(AnswerDelta(final_answer))
    return AnswerTransport(tuple(deltas), final_answer, status, usage)
