from __future__ import annotations

from .answer_transport import decode_codex_events, decode_json_text_events, decode_pi_events


def extract_final_text_from_output(text: str) -> str:
    """Return a provider answer for session display without semantic parsing."""
    raw = text.strip()
    if not raw:
        return ""
    for decoder in (decode_codex_events, decode_pi_events, decode_json_text_events):
        try:
            transport = decoder(text)
        except Exception:
            continue
        if transport.status != "failed" and transport.final_answer:
            return transport.final_answer.strip()
    return raw
