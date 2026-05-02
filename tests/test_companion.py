from __future__ import annotations

import json
from pathlib import Path

import nbformat.v4 as nbf
import pytest

from llm_jupyter.companion import validate_companion_file
from llm_jupyter.notebook import load_notebook, validate_notebook_node
from llm_jupyter.session import KernelSession


def _write_nb(path: Path, cells: list) -> None:
    import nbformat as nbfmt

    nb = nbf.new_notebook(cells=cells)
    nbfmt.write(nb, open(path, "w", encoding="utf-8"))


def test_companion_ok_when_matches(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("a = 1\n")
    c1.metadata["cell_id"] = "cid-1"
    _write_nb(nb_path, [c1])
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "notebook": "n.ipynb",
                "cells": [{"cell_id": "cid-1", "source": "a = 1\n"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    r = validate_companion_file(notebook_path=nb_path, notebook=nb, companion_file=side)
    assert r["ok"] is True
    assert r["companion_code_cells_checked"] == 1


def test_companion_source_mismatch_raises(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("a = 1\n")
    c1.metadata["cell_id"] = "cid-1"
    _write_nb(nb_path, [c1])
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "cells": [{"cell_id": "cid-1", "source": "a = 2\n"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="mismatch"):
        validate_companion_file(notebook_path=nb_path, notebook=nb, companion_file=side)


def test_companion_cell_id_mismatch_raises(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("a = 1\n")
    c1.metadata["cell_id"] = "cid-1"
    _write_nb(nb_path, [c1])
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "cells": [{"cell_id": "other", "source": "a = 1\n"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cell_id"):
        validate_companion_file(notebook_path=nb_path, notebook=nb, companion_file=side)


def test_companion_count_mismatch_raises(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("a = 1\n")
    c1.metadata["cell_id"] = "cid-1"
    c2 = nbf.new_code_cell("b = 2\n")
    c2.metadata["cell_id"] = "cid-2"
    _write_nb(nb_path, [c1, c2])
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "cells": [{"cell_id": "cid-1", "source": "a = 1\n"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="code cell entries"):
        validate_companion_file(notebook_path=nb_path, notebook=nb, companion_file=side)


def test_companion_notebook_basename_mismatch_raises(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("a = 1\n")
    c1.metadata["cell_id"] = "cid-1"
    _write_nb(nb_path, [c1])
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "notebook": "other.ipynb",
                "cells": [{"cell_id": "cid-1", "source": "a = 1\n"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="targets notebook"):
        validate_companion_file(notebook_path=nb_path, notebook=nb, companion_file=side)


def test_inspect_companion_strict_missing_sidecar_raises(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("1\n")
    _write_nb(nb_path, [c1])
    sess = KernelSession(nb_path, [], "explore")
    try:
        with pytest.raises(FileNotFoundError, match="companion_strict"):
            sess.inspect_companion(notebook_path=str(nb_path), companion_strict=True)
    finally:
        sess.close()


@pytest.mark.kernel
def test_run_response_includes_companion_when_sidecar_present(tmp_path: Path):
    nb_path = tmp_path / "n.ipynb"
    c1 = nbf.new_code_cell("1\n")
    c1.metadata["cell_id"] = "cid-1"
    _write_nb(nb_path, [c1])
    side = tmp_path / "n.apynb"
    side.write_text(
        json.dumps(
            {
                "companion_version": 1,
                "notebook": "n.ipynb",
                "cells": [{"cell_id": "cid-1", "source": "1\n"}],
            }
        ),
        encoding="utf-8",
    )
    sess = KernelSession(nb_path, [], "explore")
    try:
        out = sess.run(run_all=True, mode="explore")
        assert out["status"] == "ok"
        assert out["companion"]["status"] == "ok"
        assert out["companion"]["code_cells_checked"] == 1
        assert str(side) in out["companion"]["companion_file"]
    finally:
        sess.close()
