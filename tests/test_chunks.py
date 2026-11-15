from __future__ import annotations

from jupyter_mcp_agent.chunks import (
    append_kernel_traceback_stderr,
    cell_stream_row,
    chunk_text,
    collect_streams,
    kernel_error_digest_from_outputs,
    stream_summary_for_tool,
    strip_ansi_text,
    trim_streams_by_cell,
)


def test_strip_ansi_text_removes_color_codes():
    raw = "\x1b[31mERR\x1b[0m plain"
    assert strip_ansi_text(raw) == "ERR plain"


def test_chunk_roundtrip():
    s = "x" * 12500
    c = chunk_text(s, max_chars=4000)
    assert len(c) == 4
    assert "".join(c.values()) == s


def test_collect_streams_merges_stdout_stderr():
    stdout, stderr = collect_streams(
        [
            {"output_type": "stream", "name": "stdout", "text": "hi\n"},
            {"output_type": "stream", "name": "stderr", "text": "oops\n"},
            {"output_type": "stream", "name": "stdout", "text": "there"},
        ]
    )
    assert stdout == "hi\nthere"
    assert stderr == "oops\n"


def test_stream_summary_chunk_counts_and_tails():
    big = ("a" * 8000) + "\nTAIL_MARKER"
    out_chunks = chunk_text(big, max_chars=6000)
    sm = stream_summary_for_tool(
        big,
        "err!",
        stdout_chunks=out_chunks,
        stderr_chunks={"0": "err!"},
        tail_chars=100,
    )
    assert sm["stdout_chunk_count"] == 2
    assert sm["stderr_chunk_count"] == 1
    assert sm["stdout_chars"] == len(big)
    assert "TAIL_MARKER" in sm["stdout_tail"]
    assert sm["stderr_tail"] == "err!"


def test_stream_summary_empty_streams():
    sm = stream_summary_for_tool("", "", stdout_chunks={}, stderr_chunks={})
    assert sm["stdout_chars"] == 0
    assert sm["stderr_chars"] == 0
    assert sm["stdout_chunk_count"] == 0
    assert sm["stdout_tail"] == ""


def test_kernel_error_digest_returns_last_error():
    diag = kernel_error_digest_from_outputs(
        [
            {"output_type": "stream", "name": "stderr", "text": "warm"},
            {
                "output_type": "error",
                "ename": "FooError",
                "evalue": "first",
                "traceback": ["line first"],
            },
            {
                "output_type": "error",
                "ename": "BarError",
                "evalue": "last",
                "traceback": ["line last"],
            },
        ]
    )
    assert diag is not None
    assert diag["ename"] == "BarError"
    assert "line last" in diag["traceback_text"]


def test_append_kernel_traceback_stderr_keeps_stderr_nonempty():
    se = append_kernel_traceback_stderr("", "Trace:\nboom")
    assert "boom" in se


def test_trim_streams_by_cell_truncates_prefix():
    rows = [{"cell_index": i} for i in range(70)]
    kept, truncated = trim_streams_by_cell(rows, max_entries=64)
    assert truncated is True
    assert len(kept) == 64
    assert kept[0]["cell_index"] == 6


def test_cell_stream_row_tails_bounded():
    r = cell_stream_row(
        cell_id="abc",
        cell_index=3,
        stdout_full=("x" * 500),
        stderr_full=("e" * 500),
        tail_chars=120,
    )
    assert len(r["stdout_tail"]) == 120
    assert len(r["stderr_tail"]) == 120
