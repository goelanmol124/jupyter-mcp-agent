from __future__ import annotations

from typing import Any

# How many trailing characters to duplicate at top level for LLM tool JSON: long streams are
# split across stdout_chunks; models often overweight early keys and under-read later chunks
# ("lost in the middle" in long contexts). Surfacing the tail improves odds the final prints matter.
STREAM_SUMMARY_TAIL_CHARS = 1536


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


def stream_summary_for_tool(
    stdout_full: str,
    stderr_full: str,
    *,
    stdout_chunks: dict[str, str],
    stderr_chunks: dict[str, str],
    tail_chars: int = STREAM_SUMMARY_TAIL_CHARS,
) -> dict[str, Any]:
    """Compact stream metadata plus trailing text for MCP / agent consumers."""

    return {
        "stdout_chars": len(stdout_full),
        "stderr_chars": len(stderr_full),
        "stdout_chunk_count": len(stdout_chunks),
        "stderr_chunk_count": len(stderr_chunks),
        "stdout_tail": stdout_full[-tail_chars:] if stdout_full else "",
        "stderr_tail": stderr_full[-tail_chars:] if stderr_full else "",
    }
