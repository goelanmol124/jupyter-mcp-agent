from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest

from llm_jupyter.notebook import cell_index_for_id, ensure_cell_ids, indices_of_code_cells, load_notebook


def test_ensure_cell_ids_persists(tmp_path: Path):
    p = tmp_path / "x.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1+1"), nbf.new_markdown_cell("# t")])
    nbformat = __import__("nbformat")
    nbformat.write(nb, open(p, "w", encoding="utf-8"))
    nb2 = load_notebook(p)
    assert ensure_cell_ids(nb2, persist_path=p)
    nb3 = load_notebook(p)
    idx = indices_of_code_cells(nb3)
    assert len(idx) == 1
    cid = nb3.cells[idx[0]].metadata["cell_id"]
    assert isinstance(cid, str)
    assert cell_index_for_id(nb3, cid) == idx[0]


def test_cell_missing_errors(tmp_path: Path):
    p = tmp_path / "x.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    nb2 = load_notebook(p)
    ensure_cell_ids(nb2, persist_path=p)
    nb3 = load_notebook(p)
    with pytest.raises(LookupError):
        cell_index_for_id(nb3, "not-a-real-id")
