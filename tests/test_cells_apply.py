from __future__ import annotations

import nbformat.v4 as nbf
import pytest

from llm_jupyter.cells_apply_helpers import normalize_edits
from llm_jupyter.notebook import ensure_cell_ids, load_notebook
from llm_jupyter.session import KernelSession


def test_normalize_edits_orders_and_requires_fields():
    out = normalize_edits([{"cell_id": "a", "source": "1"}, {"cell_id": " b ", "source": "two"}])
    assert out == [("a", "1"), ("b", "two")]
    with pytest.raises(ValueError, match="non-empty"):
        normalize_edits([])


def test_cells_apply_updates_code_source(tmp_path):
    nb_path = tmp_path / "e.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("x = 1\n"),
            nbf.new_code_cell("y = old\n"),
        ],
    )
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    ensure_cell_ids(load_notebook(nb_path), persist_path=nb_path)
    sess = KernelSession(nb_path, [], "explore")
    try:
        nb0 = load_notebook(nb_path)
        cid_first = nb0.cells[0].metadata["cell_id"]
        cid_second = nb0.cells[1].metadata["cell_id"]
        rep = sess.cells_apply(edits=[{"cell_id": str(cid_second), "source": "y = 'new'\n"}])
        assert rep["status"] == "ok"
        assert len(rep["cells_updated"]) == 1
        nb1 = load_notebook(nb_path)
        assert cid_first == nb1.cells[0].metadata["cell_id"]
        assert "new" in str(nb1.cells[1].source)
        # Duplicate cell_id → last wins
        rep2 = sess.cells_apply(
            edits=[
                {"cell_id": str(cid_second), "source": "y = 'a'\n"},
                {"cell_id": str(cid_second), "source": "y = 'final'\n"},
            ]
        )
        assert rep2["edits_applied_last_wins_duplicates"][-1] == str(cid_second)
        nb2 = load_notebook(nb_path)
        assert "final" in str(nb2.cells[1].source)
    finally:
        sess.close()
