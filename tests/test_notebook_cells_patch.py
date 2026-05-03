from __future__ import annotations

from pathlib import Path

import nbformat.v4 as nbf
import pytest

from llm_jupyter.notebook import load_notebook
from llm_jupyter.notebook_cells_patch import normalize_patch_operations
from llm_jupyter.session import KernelSession


def test_normalize_insert_requires_exactly_one_anchor() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        normalize_patch_operations(
            [{"op": "insert", "cell_type": "code", "source": "", "some": "noise"}],
        )


def test_normalize_insert_rejects_conflicting_anchors() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        normalize_patch_operations(
            [
                {
                    "op": "insert",
                    "cell_type": "code",
                    "source": "",
                    "after_cell_id": "a",
                    "at_index": 0,
                },
            ],
        )


def test_notebook_cells_patch_insert_and_delete(tmp_path: Path) -> None:
    nb_path = tmp_path / "p.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("x = 1\n")])
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        nb0 = load_notebook(nb_path)
        code_id = nb0.cells[0].metadata.setdefault("cell_id", "preset")
        nb0.cells[0].metadata["cell_id"] = code_id
        nbfmt.write(nb0, open(nb_path, "w", encoding="utf-8"))

        rep = sess.notebook_cells_patch(
            operations=[
                {
                    "op": "insert",
                    "cell_type": "markdown",
                    "source": "# Title\n",
                    "before_cell_id": str(code_id),
                },
            ],
        )
        assert rep["status"] == "ok"
        nb1 = load_notebook(nb_path)
        assert len(nb1.cells) == 2
        assert nb1.cells[0].cell_type == "markdown"
        assert nb1.cells[1].cell_type == "code"

        md_id = str(nb1.cells[0].metadata["cell_id"])

        rep2 = sess.notebook_cells_patch(
            operations=[{"op": "delete", "cell_id": md_id}],
        )
        assert rep2["status"] == "ok"
        nb2 = load_notebook(nb_path)
        assert len(nb2.cells) == 1
        assert nb2.cells[0].cell_type == "code"
    finally:
        sess.close()


def test_notebook_cells_patch_move_wraps(tmp_path: Path) -> None:
    nb_path = tmp_path / "mv.ipynb"
    nb = nbf.new_notebook(
        cells=[
            nbf.new_code_cell("a=1"),
            nbf.new_code_cell("b=2"),
            nbf.new_code_cell("c=3"),
        ],
    )
    import nbformat as nbfmt

    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        nbl = load_notebook(nb_path)
        ids = []
        for c in nbl.cells:
            meta = c.setdefault("metadata", {})
            if not meta.get("cell_id"):
                import uuid

                meta["cell_id"] = str(uuid.uuid4())
            ids.append(str(meta["cell_id"]))
        nbfmt.write(nbl, open(nb_path, "w", encoding="utf-8"))

        rep = sess.notebook_cells_patch(
            operations=[
                {"op": "move", "cell_id": ids[0], "after_cell_id": ids[2]},
            ],
        )
        assert rep["status"] == "ok"
        nf = load_notebook(nb_path)
        assert [nf.cells[i].metadata["cell_id"] for i in range(3)] == [
            ids[1],
            ids[2],
            ids[0],
        ]
    finally:
        sess.close()
