from __future__ import annotations

from typing import Any


def chunk_text(text: str, max_chars: int = 6000) -> dict[str, str]:
    """Split text into numbered string chunks for JSON responses."""
    if not text:
        return {}
    chunks: dict[str, str] = {}
    idx = 0
    pos = 0
    while pos < len(text):
        chunk = text[pos : pos + max_chars]
        chunks[str(idx)] = chunk
        idx += 1
        pos += max_chars
    return chunks


def collect_streams(outputs: list[dict[str, Any]]) -> tuple[str, str]:
    out_parts: list[str] = []
    err_parts: list[str] = []
    for o in outputs:
        if o.get("output_type") != "stream":
            continue
        name = o.get("name", "")
        txt = o.get("text", "")
        if isinstance(txt, list):
            txt = "".join(txt)
        if name == "stdout":
            out_parts.append(txt)
        elif name == "stderr":
            err_parts.append(txt)
    return "".join(out_parts), "".join(err_parts)
