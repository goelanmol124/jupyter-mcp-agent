"""MCP-layer tests for notebook_outline / dry_run (no live kernel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import nbformat as nbfmt
import nbformat.v4 as nbf


async def _call_tool(nb: Path, tool: str, args: dict[str, object]) -> dict[str, object]:
    from llm_jupyter.server import build_mcp

    mcp = build_mcp(nb, [], "explore")
    tm = mcp._tool_manager
    try:
        return await tm.call_tool(tool, args, context=None, convert_result=False)
    finally:
        ks = getattr(mcp, "_llm_kernel_session", None)
        if ks is not None:
            ks.close()


def test_notebook_outline_include_sources_respects_cell_cap(tmp_path: Path) -> None:
    p = tmp_path / "ol.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("print(1)"), nbf.new_markdown_cell("# hi")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    out = asyncio.run(
        _call_tool(
            p,
            "notebook_outline",
            {"include_sources": True, "max_cells_with_sources": 1, "max_source_chars": 500},
        ),
    )
    assert out["status"] == "ok"
    assert out["include_sources_used"] is True
    assert out["cells_with_source_emitted"] == 1
    c0 = next(c for c in out["cells"] if c["index"] == 0)
    assert "source_full" in c0
    c1 = next(c for c in out["cells"] if c["index"] == 1)
    assert c1.get("source_full_omitted") == "cell_cap"


def test_dry_run_tool_matches_kernelless_session(tmp_path: Path) -> None:
    p = tmp_path / "dr.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(p), persist_path=p)
    nb2 = load_notebook(p)
    cid = str(nb2.cells[0]["metadata"]["cell_id"])

    mcp_plan = asyncio.run(_call_tool(p, "dry_run", {"cell_id": cid}))

    from llm_jupyter.session import KernelSession

    sess = KernelSession(p, [], "explore")
    try:
        sess_plan = sess.resolve_run_targets(cell_id=cid)
    finally:
        sess.close()

    assert mcp_plan["status"] == sess_plan["status"] == "ok"
    assert mcp_plan["execution_cell_indices"] == sess_plan["execution_cell_indices"]
