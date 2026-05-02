from __future__ import annotations

from llm_jupyter.server import build_mcp


def test_mcp_tool_surface_is_small():
    mcp = build_mcp(None, [], "explore")
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "run",
        "kernel_restart",
        "kernel_interrupt",
        "kernel_status",
        "clear_outputs",
        "notebook_validate",
        "companion_validate",
    }
    for t in tools:
        desc = (t.description or "").strip()
        assert len(desc) < 500, f"{t.name} description too long for MCP ergonomics"
