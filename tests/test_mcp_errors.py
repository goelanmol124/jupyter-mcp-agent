"""Tests for MCP error payloads."""
from __future__ import annotations

from jupyter_mcp_agent.server import _mcp_tool_error


def _raise_val() -> None:
    raise ValueError("needle-trace-marker")


def test_mcp_tool_error_traceback_contains_frame_and_exception() -> None:
    try:
        _raise_val()
    except ValueError as e:
        p = _mcp_tool_error("probe", e)
    assert p["status"] == "error"
    assert p["tool"] == "probe"
    assert p["exc_type"] == "ValueError"
    assert p["exc_message"] == p["tool_error"]
    assert "needle-trace-marker" in str(p["tool_error"])
    tb = str(p["traceback"])
    assert "ValueError" in tb
    assert "_raise_val" in tb
    lowered = tb.lower()
    assert "unexpected keyword" not in lowered


def test_mcp_tool_error_traceback_has_no_handler_typeerror_from_chained_exc() -> None:
    try:
        raise RuntimeError("inner-cause")
    except RuntimeError as inner:
        try:
            raise ValueError("wrapper") from inner
        except ValueError as e:
            p = _mcp_tool_error("probe", e)

    tb = str(p["traceback"])
    lowered = tb.lower()
    assert "unexpected keyword" not in lowered
    assert p["exc_type"] == "ValueError"
    assert "wrapper" in tb
    assert "inner-cause" in tb
