from __future__ import annotations

import hashlib
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


def cell_exclude_from_bulk(cell: Any) -> bool:
    """True when metadata.llm_jupyter.exclude_from_bulk is truthy ([PRD conformance] probe cells).

    Applies to bulk selectors ``run_all`` / ``run_until`` only—not to single-cell ``run(..., cell_id=...)``.
    """

    md = getattr(cell, "metadata", {}) or {}
    if not isinstance(md, dict):
        return False
    lj = md.get("llm_jupyter")
    if isinstance(lj, dict) and bool(lj.get("exclude_from_bulk")):
        return True
    return False


def bulk_eligible_code_indices(nb: nbformat.NotebookNode) -> list[int]:
    """Code-cell indices participating in bulk ``run_all`` / ``run_until`` semantics."""
    out: list[int] = []
    for i in indices_of_code_cells(nb):
        if not cell_exclude_from_bulk(nb.cells[i]):
            out.append(i)
    return out


def sources_concat_sha256_prefix(nb: nbformat.NotebookNode, *, prefix_len: int = 16) -> str:
    """Stable manifest fingerprint over all code-cell sources ([PRD conformance]).

    Uses the same LF + trailing-whitespace normalization as companion drift checks.
    """
    # Local import avoids circular imports if companion pulls notebook helpers.
    from jupyter_mcp_agent.companion import normalize_source

    chunks: list[str] = []
    for cell in nb.cells:
        if getattr(cell, "cell_type", None) != "code":
            continue
        src_val = getattr(cell, "source", "") or ""
        if isinstance(src_val, list):
            src_val = "".join(src_val)
        chunks.append(normalize_source(str(src_val)))
    blob = "\n".join(chunks).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:prefix_len]


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
