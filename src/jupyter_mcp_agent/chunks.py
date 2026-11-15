from __future__ import annotations

import re
from typing import Any

# Strip common ANSI/VT escape sequences from captured kernel streams (readability for LLMs).
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[-/]*[@-~])")


def strip_ansi_text(text: str) -> str:
    if not text:
        return ""
    return ANSI_ESCAPE_RE.sub("", text)

# How many trailing characters to duplicate at top level for LLM tool JSON: long streams are
# split across stdout_chunks; models often overweight early keys and under-read later chunks
# ("lost in the middle" in long contexts). Surfacing the tail improves odds the final prints matter.
STREAM_SUMMARY_TAIL_CHARS = 1536

# Per-cell tails for ``streams_by_cell_executed``; keep payloads bounded.
CELL_STREAM_TAIL_CHARS = 384

# Max ordered entries in ``streams_by_cell_executed`` (drops overflow from head).
MAX_STREAMS_BY_CELL_ENTRIES = 64

# Structured kernel errors mirrored with ``halt_on_error`` false (beyond ``execution_error``).
MAX_KERNEL_ERROR_LOG_ENTRIES = 5


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


def kernel_error_digest_from_outputs(outputs: list[dict[str, Any]]) -> dict[str, str] | None:
    """Return the notebook's **last** ``output_type=="error"`` block (nbformat shape).

    When multiple failures occur in one cell output list, trailing errors are authoritative.
    """
    last_err: dict[str, Any] | None = None
    for o in outputs or []:
        if isinstance(o, dict) and o.get("output_type") == "error":
            last_err = o
    if last_err is None:
        return None
    tb = last_err.get("traceback")
    if isinstance(tb, list):
        traceback_text = "\n".join(str(x) for x in tb)
    elif tb:
        traceback_text = str(tb)
    else:
        traceback_text = ""
    return {
        "ename": str(last_err.get("ename", "")),
        "evalue": str(last_err.get("evalue", "")),
        "traceback_text": traceback_text,
    }


def append_kernel_traceback_stderr(stderr_so_far: str, traceback_text: str) -> str:
    """Concatenate traceback into stderr accumulator so chunked stderr is not falsely empty."""
    tb = traceback_text.strip()
    if not tb:
        return stderr_so_far
    sep = "\n" if stderr_so_far.strip() else ""
    return stderr_so_far + sep + tb


STREAM_SUFFIX_DESCRIPTOR: dict[str, Any] = {
    "strategy": "literal_suffix_chars",
    "from_end": True,
    "note": (
        "stdout_tail/stderr_tail and *_suffix mirror the **last N characters** of captured stream text, "
        "not POSIX “tail -n lines”. Mid-string fragments may look “corrupted” when N truncates earlier context."
    ),
    "summary_suffix_n_chars": STREAM_SUMMARY_TAIL_CHARS,
    "per_cell_suffix_n_chars": CELL_STREAM_TAIL_CHARS,
}


def cell_stream_row(
    *,
    cell_id: str,
    cell_index: int,
    stdout_full: str,
    stderr_full: str,
    tail_chars: int = CELL_STREAM_TAIL_CHARS,
) -> dict[str, Any]:
    """One executed cell's stream sizing + capped tails."""
    uc, ec = stdout_full[-tail_chars:] if stdout_full else "", stderr_full[-tail_chars:] if stderr_full else ""
    return {
        "cell_id": cell_id,
        "cell_index": cell_index,
        "stdout_chars": len(stdout_full),
        "stderr_chars": len(stderr_full),
        # Explicit suffix semantics (duplicate keys for readability with stream_truncation_semantics).
        "stdout_suffix": uc,
        "stderr_suffix": ec,
        "stdout_tail": uc,
        "stderr_tail": ec,
    }


def trim_streams_by_cell(
    rows: list[dict[str, Any]],
    *,
    max_entries: int = MAX_STREAMS_BY_CELL_ENTRIES,
) -> tuple[list[dict[str, Any]], bool]:
    """Drop overflow from the start; set truncated True when shortened."""
    if len(rows) <= max_entries:
        return rows, False
    return rows[-max_entries:], True


def stream_summary_for_tool(
    stdout_full: str,
    stderr_full: str,
    *,
    stdout_chunks: dict[str, str],
    stderr_chunks: dict[str, str],
    tail_chars: int = STREAM_SUMMARY_TAIL_CHARS,
) -> dict[str, Any]:
    """Compact stream metadata plus trailing text for MCP / agent consumers."""

    suf_out = stdout_full[-tail_chars:] if stdout_full else ""
    suf_err = stderr_full[-tail_chars:] if stderr_full else ""
    return {
        "stdout_chars": len(stdout_full),
        "stderr_chars": len(stderr_full),
        "stdout_chunk_count": len(stdout_chunks),
        "stderr_chunk_count": len(stderr_chunks),
        "stdout_suffix": suf_out,
        "stderr_suffix": suf_err,
        "stdout_tail": suf_out,
        "stderr_tail": suf_err,
    }
