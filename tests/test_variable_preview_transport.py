from __future__ import annotations

from llm_jupyter.session import (
    _PREVIEW_JSON_END,
    _PREVIEW_JSON_START,
    _variable_preview_stdout_blob,
)


def test_variable_preview_extracts_marker_wrapped_json_with_noise_stdout() -> None:
    messy = (
        'some kernel noise\n repr junk\n{\n"b": 2}\n'
        f"{_PREVIEW_JSON_START}\n"
        '{"a": 1}\n'
        f"{_PREVIEW_JSON_END}\nfooter\n"
    )
    blob = _variable_preview_stdout_blob(messy)
    assert blob == '{"a": 1}'


def test_variable_preview_falls_back_to_last_line_when_no_markers() -> None:
    assert _variable_preview_stdout_blob('x\n{"k": "v"}') == '{"k": "v"}'
