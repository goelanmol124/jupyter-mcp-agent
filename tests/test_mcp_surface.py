from __future__ import annotations

from llm_jupyter.server import build_mcp


def test_mcp_tool_surface_is_small():
    mcp = build_mcp(None, [], "explore")
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert names == {
            "run",
            "dry_run",
            "notebook_execution_plan",
            "kernel_restart",
            "kernel_interrupt",
            "kernel_status",
            "kernel_ping",
            "clear_outputs",
            "notebook_validate",
            "notebook_outline",
            "notebook_cells_patch",
            "companion_validate",
            "cells_apply",
            "variable_preview",
            "run_stream_read",
            "server_info",
        }
    for t in tools:
        desc = (t.description or "").strip()
        assert len(desc) < 500, f"{t.name} description too long for MCP ergonomics"
