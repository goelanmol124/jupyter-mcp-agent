from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest


def test_contradictory_run_modes_raises(tmp_path: Path):
    import nbformat as nbfmt

    from llm_jupyter.session import KernelSession

    p = tmp_path / "x.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1"), nbf.new_code_cell("2")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(p), persist_path=p)
    nb3 = nbfmt.read(open(p, encoding="utf-8"), as_version=4)
    cid = nb3.cells[0]["metadata"]["cell_id"]

    sess = KernelSession(p, [], "explore")
    try:
        with pytest.raises(ValueError, match="Conflicting run targets"):
            sess.run(run_all=True, cell_id=str(cid))
        with pytest.raises(ValueError, match="exactly one"):
            sess.run(run_all=False)
    finally:
        sess.close()


def test_notebook_without_code_cells_allows_no_selector(tmp_path: Path):
    import nbformat as nbfmt

    from llm_jupyter.session import KernelSession

    p = tmp_path / "only_md.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_markdown_cell("# hi")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    sess = KernelSession(p, [], "explore")
    try:
        out = sess.run(run_all=False)
        assert out["cells_executed"] == []
        assert "run_id" in out and len(out["run_id"]) >= 8
    finally:
        sess.close()
