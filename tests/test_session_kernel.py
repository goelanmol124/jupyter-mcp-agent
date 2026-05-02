from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest

from llm_jupyter.session import KernelSession


@pytest.mark.kernel
def test_run_all_writes_output_and_manifest(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell('import sys\nprint("out", file=sys.stdout)\nprint("err", file=sys.stderr)')])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, mode="explore")
        assert out["status"] == "ok"
        assert "run_id" in out and len(out["run_id"]) >= 8
        assert out["kernel_generation"] >= 1
        assert not out["outputs_might_be_stale"]
        assert "out" in "".join(out["stdout_chunks"].values())
        assert "err" in "".join(out["stderr_chunks"].values())
        mf = tmp_path / "manifest.jsonl"
        assert mf.exists()
        line0 = mf.read_text(encoding="utf-8").strip().splitlines()[0]
        import json

        assert json.loads(line0)["run_id"] == out["run_id"]
    finally:
        sess.close()


@pytest.mark.kernel
def test_partial_run_reports_stale(tmp_path: Path):
    nb_path = tmp_path / "p.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("x=1"),
            nbf.new_code_cell("x+=1"),
        ]
    )
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))

    sess = KernelSession(nb_path, [], "explore")
    try:
        sess.run(run_all=True, mode="explore")
        nb2 = nbfmt.read(open(nb_path, encoding="utf-8"), as_version=4)
        cid0 = nb2.cells[0]["metadata"]["cell_id"]
        out = sess.run(cell_id=str(cid0), mode="explore")
        assert out["status"] == "ok"
        assert out["outputs_might_be_stale"]
        assert any("partial" in n.lower() or "partial" in n for n in out["stale_notes"])
    finally:
        sess.close()


@pytest.mark.kernel
def test_kernel_restart_increments_generation(tmp_path: Path):
    nb_path = tmp_path / "r.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        sess.run(run_all=True)
        g = sess.kernel_generation
        sess.kernel_restart()
        assert sess.kernel_generation == g + 1
        out = sess.run(run_all=True)
        assert out["restart_since_previous_tool_call"] is True
    finally:
        sess.close()
