"""MCP-layer kernelless tests: execution_plan, spilled stream reads, validate."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import nbformat as nbfmt
import nbformat.v4 as nbf

from llm_jupyter.stream_artifacts import read_run_stream_slice, write_run_stream_artifacts


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



def test_read_run_stream_slice_module_api(tmp_path: Path) -> None:
    """Contract: filesystem reader remains after MCP run_stream_read removal."""

    p = tmp_path / "x.ipynb"
    nbfmt.write(nbf.new_notebook(cells=[]), open(p, "w", encoding="utf-8"))
    rid = "runabc123456"
    write_run_stream_artifacts(p, rid, stdout_text="hello-stream\nsecond\n", stderr_text="y", extra_meta={})

    out = read_run_stream_slice(p, rid, "stdout", byte_offset=0, max_bytes=64)
    decoded = base64.standard_b64decode(str(out["data_base64"]))
    assert b"hello-stream" in decoded

    se = read_run_stream_slice(p, rid, "stderr")
    assert base64.standard_b64decode(se["data_base64"]) == b"y"





def test_notebook_validate_persist_cell_ids(tmp_path: Path) -> None:
    p = tmp_path / "v.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    for c in nb.cells:
        c.metadata.pop("cell_id", None)
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    out = asyncio.run(_call_tool(p, "notebook_validate", {"persist_cell_ids": True}))
    assert out["status"] == "ok"
    assert out["persist_cell_ids_used"] is True
    assert out["cell_ids_assigned_written"] is True
    stamp = out.get("notebook_file_stamp")
    assert isinstance(stamp, dict) and "sha256_prefix" in stamp
    nb2 = nbfmt.read(open(p, encoding="utf-8"), as_version=4)
    assert nb2.cells[0].metadata.get("cell_id")


def test_manifest_early_includes_sources_fingerprint(tmp_path: Path) -> None:
    from llm_jupyter.session import KernelSession

    p = tmp_path / "only_md.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_markdown_cell("# hi")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    sess = KernelSession(p, [], "explore")
    try:
        out = sess.run(run_all=False)
        assert out["cells_executed"] == []
    finally:
        sess.close()
    mf = p.parent / "manifest.jsonl"
    line0 = json.loads(mf.read_text(encoding="utf-8").strip().splitlines()[0])
    assert "sources_concat_sha256_prefix" in line0
    assert len(str(line0["sources_concat_sha256_prefix"])) == 16
