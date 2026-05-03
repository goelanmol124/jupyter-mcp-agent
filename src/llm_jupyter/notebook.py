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


def strip_cell_outputs_matching_type(nb: nbformat.NotebookNode, cell_indices: list[int], *, output_type: str) -> None:
    """Remove outputs with ``output_type`` (e.g. ``stream``) from selected cells; keep errors/other MIME."""

    ot = output_type.strip()
    for idx in cell_indices:
        if idx < 0 or idx >= len(nb.cells):
            continue
        cell = nb.cells[idx]
        outs = list(getattr(cell, "outputs", []) or [])
        cell.outputs = [
            o for o in outs if isinstance(o, dict) and str(o.get("output_type", "")).strip() != ot
        ]


def ensure_cell_ids(nb: nbformat.NotebookNode, persist_path: str | Any | None = None) -> bool:
    """Assign metadata.cell_id to every cell (code, markdown, raw); return True if modified."""
    changed = False
    for cell in nb.cells:
        meta = cell.setdefault("metadata", {})
        if not meta.get("cell_id"):
            meta["cell_id"] = str(uuid.uuid4())
            changed = True
    if changed and persist_path is not None:
        save_notebook(nb, persist_path)
    return changed


def load_notebook_ensuring_cell_ids(path: str | Any) -> tuple[nbformat.NotebookNode, bool]:
    """Read once from disk, assign persisted ``cell_id`` when missing, return ``(nb, changed_on_disk)``."""

    nb = load_notebook(path)
    changed = ensure_cell_ids(nb, persist_path=path)
    return nb, changed


def indices_of_code_cells(nb: nbformat.NotebookNode) -> list[int]:
    return [i for i, c in enumerate(nb.cells) if c.cell_type == "code"]


def cell_index_for_stable_id(nb: nbformat.NotebookNode, cell_id: str) -> int:
    for i, cell in enumerate(nb.cells):
        cid = cell.get("metadata", {}).get("cell_id") if isinstance(cell.get("metadata"), dict) else None
        if cid == cell_id:
            return i
    raise LookupError(f"Unknown cell_id: {cell_id}")


def cell_index_for_id(nb: nbformat.NotebookNode, cell_id: str) -> int:
    """Resolve a **code** cell index by ``metadata.cell_id`` (used by ``run`` selectors)."""

    i = cell_index_for_stable_id(nb, cell_id)
    if getattr(nb.cells[i], "cell_type", None) != "code":
        raise LookupError(f"cell_id {cell_id!r} is not a code cell")
    return i


def validate_notebook_node(nb: nbformat.NotebookNode) -> None:
    nbformat.validate(nb)


def try_validate_notebook_file(path: str | Any) -> None:
    nb = load_notebook(path)
    try:
        validate_notebook_node(nb)
    except NotebookValidationError as e:
        raise ValueError(f"Notebook validation failed for {path}: {e}") from e
