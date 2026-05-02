"""Optional **.apynb** sidecar JSON: mirrors code-cell sources keyed by nbformat metadata.cell_id.

If `notebook.ipynb` and `notebook.apynb` disagree, validation fails loudly before kernel work.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def companion_path_for_notebook(notebook_path: Path) -> Path:
    return notebook_path.with_suffix(".apynb")


def _source_as_text(source: Any) -> str:
    if isinstance(source, list):
        return "".join(source)
    return "" if source is None else str(source)


def normalize_source(text: str) -> str:
    """Stable compare: LF endings, strip trailing spaces per line."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.strip("\n").split("\n")
    body = "\n".join(line.rstrip() for line in lines)
    return body


def _normalize_for_compare(agent_text: str) -> str:
    return normalize_source(_source_as_text(agent_text))


def load_companion(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Companion file must be a JSON object: {path}")
    ver = data.get("companion_version", 1)
    if ver != 1:
        raise ValueError(f"Unsupported companion_version {ver} in {path}")
    cells = data.get("cells")
    if cells is None or not isinstance(cells, list):
        raise ValueError(f"Companion missing 'cells' array: {path}")
    nb_name = data.get("notebook")
    if nb_name is not None and isinstance(nb_name, str) and nb_name.strip():
        bn = nb_name.strip()
        if bn != Path(bn).name or "/" in bn or "\\" in bn:
            raise ValueError("'notebook' in companion must be a basename (no slashes).")
    return data


def validate_companion_against_notebook(
    *,
    notebook_path: Path,
    notebook: Any,
    companion_data: dict[str, Any],
) -> dict[str, Any]:
    """Return a small diagnostic dict on success."""

    nb_name_expected = companion_data.get("notebook")
    if nb_name_expected and str(nb_name_expected).strip():
        if notebook_path.name != str(nb_name_expected).strip():
            raise ValueError(
                f"Companion targets notebook {str(nb_name_expected).strip()!r}, "
                f"but path is {notebook_path.name!r}.",
            )

    rows: list[Any] = companion_data["cells"]
    code_indices: list[int] = []
    for i, cell in enumerate(notebook.cells):
        if getattr(cell, "cell_type", None) == "code":
            code_indices.append(i)

    if len(rows) != len(code_indices):
        raise ValueError(
            f"Companion has {len(rows)} code cell entries but notebook has {len(code_indices)}.",
        )

    for j, nb_index in enumerate(code_indices):
        cell = notebook.cells[nb_index]
        cid = cell.get("metadata", {}).get("cell_id")
        nb_src = _normalize_for_compare(_source_as_text(cell.source))
        row = rows[j]
        if not isinstance(row, dict):
            raise ValueError(f"Companion.cells[{j}] must be an object.")
        cid_c = row.get("cell_id")
        src_c = row.get("source")
        if cid is None or str(cid_c) != str(cid):
            raise ValueError(
                f"Companion drift at code-sequence index {j}: cell_id notebook={cid!r} companion={cid_c!r}.",
            )
        cmp_src = _normalize_for_compare(src_c)
        if nb_src.strip() != cmp_src.strip():
            raise ValueError(
                f"Companion source mismatch for cell_id={cid}: reconcile .ipynb and .apynb.",
            )

    return {
        "ok": True,
        "companion_code_cells_checked": len(code_indices),
    }


def validate_companion_file(
    *,
    notebook_path: Path,
    notebook: Any,
    companion_file: Path,
) -> dict[str, Any]:
    data = load_companion(companion_file)
    return validate_companion_against_notebook(
        notebook_path=notebook_path,
        notebook=notebook,
        companion_data=data,
    )


def write_companion_from_notebook(
    notebook_path: str | Path,
    companion_out: str | Path | None = None,
) -> Path:
    """Write companion JSON from code cells in order.

    Persists ``metadata.cell_id`` for any code cell that was missing one.
    """
    from llm_jupyter.notebook import ensure_cell_ids, indices_of_code_cells, load_notebook, validate_notebook_node

    nb_path = Path(notebook_path).expanduser().resolve()
    if not nb_path.is_file():
        raise FileNotFoundError(f"Notebook not found: {nb_path}")

    nb = load_notebook(nb_path)
    ensure_cell_ids(nb, persist_path=nb_path)
    nb = load_notebook(nb_path)
    validate_notebook_node(nb)

    out = (
        Path(companion_out).expanduser().resolve()
        if companion_out is not None
        else companion_path_for_notebook(nb_path)
    )

    rows = []
    for i in indices_of_code_cells(nb):
        cell = nb.cells[i]
        cid = cell.get("metadata", {}).get("cell_id")
        if cid is None or not str(cid).strip():
            raise ValueError(f"Code cell index {i} has no metadata.cell_id after ensure_cell_ids")
        rows.append({"cell_id": str(cid).strip(), "source": _source_as_text(cell.source)})

    payload = {"companion_version": 1, "notebook": nb_path.name, "cells": rows}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
