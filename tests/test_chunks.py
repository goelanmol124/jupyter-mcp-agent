from __future__ import annotations

from llm_jupyter.chunks import chunk_text, collect_streams


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
