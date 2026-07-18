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


def test_run_lookuperror_includes_resolved_notebook_path(tmp_path: Path):
    import nbformat as nbfmt
    import nbformat.v4 as nbf

    from llm_jupyter.session import KernelSession

    p = tmp_path / "pathhint.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook

    ensure_cell_ids(load_notebook(p), persist_path=p)

    sess = KernelSession(p, [], "explore")
    try:
        with pytest.raises(LookupError, match="resolved notebook"):
            sess.run(cell_id="00000000-0000-0000-0000-000000000001")
    finally:
        sess.close()


def test_resolve_run_targets_without_kernel(tmp_path: Path) -> None:
    import nbformat as nbfmt
    import nbformat.v4 as nbf

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook
    from llm_jupyter.session import KernelSession

    p = tmp_path / "plan.ipynb"
    nb = nbf.new_notebook(
        cells=[nbf.new_code_cell("1"), nbf.new_markdown_cell("# x"), nbf.new_code_cell("2")],
    )
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(p), persist_path=p)
    nb2 = load_notebook(p)
    cid0 = str(nb2.cells[0].metadata["cell_id"])

    sess = KernelSession(p, [], "explore")
    try:
        plan = sess.resolve_run_targets(cell_id=cid0)
        assert plan["status"] == "ok"
        assert plan["selector_kind"] == "cell"
        assert plan["execution_cell_indices"] == [0]
        assert plan["cells_planned_n"] == 1
        assert plan["cells_planned"][0]["cell_index"] == 0
        ks = plan["kernel_status_preview"]
        assert ks["kernel_alive"] is False
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


def test_bulk_exclude_skips_probe_in_run_all_plan(tmp_path: Path) -> None:
    import nbformat as nbfmt

    from llm_jupyter.notebook import ensure_cell_ids, load_notebook
    from llm_jupyter.session import KernelSession

    probe = nbf.new_code_cell("probe")
    probe.metadata["llm_jupyter"] = {"exclude_from_bulk": True}
    p = tmp_path / "bulk.ipynb"
    nb = nbf.new_notebook(
        cells=[probe, nbf.new_markdown_cell("# m"), nbf.new_code_cell("x = 2")],
    )
    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(p), persist_path=p)

    sess = KernelSession(p, [], "explore")
    try:
        plan = sess.notebook_execution_plan(run_all=True)
        assert plan["execution_cell_indices"] == [2]
        cid0 = str(load_notebook(p).cells[0].metadata["cell_id"])
        one = sess.notebook_execution_plan(cell_id=cid0)
        assert one["execution_cell_indices"] == [0]
    finally:
        sess.close()
