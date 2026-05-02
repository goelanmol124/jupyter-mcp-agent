from __future__ import annotations

from llm_jupyter.chunks import chunk_text, collect_streams, stream_summary_for_tool


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
