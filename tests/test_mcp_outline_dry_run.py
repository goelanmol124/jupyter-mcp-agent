"""MCP-layer tests for notebook_outline / dry_run (no live kernel)."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import nbformat as nbfmt
import nbformat.v4 as nbf

from llm_jupyter.stream_artifacts import write_run_stream_artifacts


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
    summ = out["outline_sources_truncation_summary"]
    assert summ["cells_with_full_source_emitted"] == 1
    assert summ["source_full_omitted_cell_cap_count"] == 1
    assert summ["source_full_omitted_char_cap_count"] == 0
    c0 = next(c for c in out["cells"] if c["index"] == 0)
    assert "source_full" in c0
    c1 = next(c for c in out["cells"] if c["index"] == 1)
    assert c1.get("source_full_omitted") == "cell_cap"
    assert out["outline_caps_effective"]["preview_chars_floor"] == 48
    assert out["outline_caps_requested"]["preview_chars"] == 200


def test_notebook_execution_plan_structural_probe(tmp_path: Path) -> None:
    p = tmp_path / "pl.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    plan = asyncio.run(_call_tool(p, "notebook_execution_plan", {}))
    assert plan["status"] == "ok"
    assert plan["selector_kind"] == "structural_probe"
    assert plan["cells_planned_n"] == 0
    assert len(plan["code_cell_indices"]) == 1


def test_notebook_execution_plan_with_selector_matches_resolve(tmp_path: Path) -> None:
    p = tmp_path / "pl2.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(p), persist_path=p)
    nb2 = load_notebook(p)
    cid = str(nb2.cells[0]["metadata"]["cell_id"])

    from llm_jupyter.session import KernelSession

    mcp_plan = asyncio.run(_call_tool(p, "notebook_execution_plan", {"cell_id": cid}))
    sess = KernelSession(p, [], "explore")
    try:
        sess_plan = sess.resolve_run_targets(cell_id=cid)
    finally:
        sess.close()

    assert mcp_plan["execution_cell_indices"] == sess_plan["execution_cell_indices"]


def test_run_stream_read_mcp_tool_reads_artifact_slice(tmp_path: Path) -> None:
    p = tmp_path / "rs.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    rid = "runabc123456"
    write_run_stream_artifacts(p, rid, stdout_text="hello-stream\nsecond\n", stderr_text="", extra_meta={})

    out = asyncio.run(
        _call_tool(
            p,
            "run_stream_read",
            {"run_id": rid, "stream": "stdout", "byte_offset": 0, "max_bytes": 64},
        ),
    )
    assert out["status"] == "ok"
    decoded = base64.standard_b64decode(str(out["data_base64"]))
    assert b"hello-stream" in decoded


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
