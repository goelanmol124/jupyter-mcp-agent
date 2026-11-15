"""Canonical key ordering for MCP tool envelopes."""

from __future__ import annotations

from typing import Any

from jupyter_mcp_agent import __version__


def stable_tool_ok_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return ``{\"status\":\"ok\", **body}`` with status first."""

    out: dict[str, Any] = {"status": "ok"}
    for k, v in body.items():
        if k == "status":
            continue
        out[k] = v
    return out


def stable_tool_error(tool: str, exc: BaseException | str, traceback_text: str) -> dict[str, Any]:
    """Ordered error envelope; ``extras`` appended after core fields."""

    msg = str(exc) if isinstance(exc, BaseException) else str(exc)
    etype = type(exc).__name__ if isinstance(exc, BaseException) else "Error"

    ordered: dict[str, Any] = {
        "status": "error",
        "llm_jupyter_version": __version__,
        "tool": tool,
        "tool_error": msg,
        "exc_type": etype,
        "exc_message": msg,
        "traceback": traceback_text,
    }
    return ordered


def stable_tool_error_with_extras(tool: str, exc: BaseException | str, traceback_text: str, **extras: Any) -> dict[str, Any]:
    base = stable_tool_error(tool, exc, traceback_text)
    for k in sorted(extras.keys()):
        if k == "traceback":
            continue
        base[k] = extras[k]
    return base
