from __future__ import annotations

import uuid
from typing import Any

import nbformat
from nbformat.validator import NotebookValidationError


def load_notebook(path: str | Any) -> nbformat.NotebookNode:
    with open(path, encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)
    return nb


def save_notebook(nb: nbformat.NotebookNode, path: str | Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)


def ensure_cell_ids(nb: nbformat.NotebookNode, persist_path: str | Any | None = None) -> bool:
    """Assign metadata.cell_id to every code cell; return True if notebook was modified."""
    changed = False
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        meta = cell.setdefault("metadata", {})
        if not meta.get("cell_id"):
            meta["cell_id"] = str(uuid.uuid4())
            changed = True
    if changed and persist_path is not None:
        save_notebook(nb, persist_path)
    return changed


def indices_of_code_cells(nb: nbformat.NotebookNode) -> list[int]:
    return [i for i, c in enumerate(nb.cells) if c.cell_type == "code"]


def cell_index_for_id(nb: nbformat.NotebookNode, cell_id: str) -> int:
    for i, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        cid = cell.get("metadata", {}).get("cell_id")
        if cid == cell_id:
            return i
    raise LookupError(f"Unknown code cell_id: {cell_id}")


def validate_notebook_node(nb: nbformat.NotebookNode) -> None:
    nbformat.validate(nb)


def try_validate_notebook_file(path: str | Any) -> None:
    nb = load_notebook(path)
    try:
        validate_notebook_node(nb)
    except NotebookValidationError as e:
        raise ValueError(f"Notebook validation failed for {path}: {e}") from e
