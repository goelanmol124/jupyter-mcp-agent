from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest

from jupyter_mcp_agent.notebook import (
    cell_index_for_id,
    cell_index_for_stable_id,
    ensure_cell_ids,
    indices_of_code_cells,
    load_notebook,
    sources_concat_sha256_prefix,
)

def test_sources_concat_sha256_prefix_is_order_sensitive() -> None:
    a = nbf.new_notebook(cells=[nbf.new_code_cell("a"), nbf.new_code_cell("b")])
    b = nbf.new_notebook(cells=[nbf.new_code_cell("b"), nbf.new_code_cell("a")])
    assert sources_concat_sha256_prefix(a) != sources_concat_sha256_prefix(b)

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


def test_ensure_cell_ids_assigns_stable_ids_markdown(tmp_path: Path) -> None:
    p = tmp_path / "m.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1+1"), nbf.new_markdown_cell("# t")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(p, "w", encoding="utf-8"))
    nb2 = load_notebook(p)
    assert ensure_cell_ids(nb2, persist_path=p)
    nb3 = load_notebook(p)
    mid = nb3.cells[1].metadata.get("cell_id")
    assert isinstance(mid, str) and mid
    assert cell_index_for_stable_id(nb3, str(mid)) == 1
    with pytest.raises(LookupError, match="not a code cell"):
        cell_index_for_id(nb3, str(mid))


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
