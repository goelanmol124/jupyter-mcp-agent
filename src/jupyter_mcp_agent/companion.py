"""Companion mirror files beside an ``.ipynb``.

Auto-discovery prefers same-stem **``.apynb``** (JSON), else **``{stem}.companion.yaml``**
or **``{stem}.companion.yml``**.

If sidecar disagree with notebook sources + ``metadata.cell_id``, validation fails loudly before kernel work.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def companion_path_for_notebook(notebook_path: Path) -> Path:
    return notebook_path.with_suffix(".apynb")


def companion_yaml_paths_for_notebook(notebook_path: Path) -> list[Path]:
    """Stable candidates (first existing wins after `.apynb`)."""
    stem = notebook_path.stem
    parent = notebook_path.parent
    return [
        parent / f"{stem}.companion.yaml",
        parent / f"{stem}.companion.yml",
    ]


def default_companion_path_for_notebook(notebook_path: Path) -> Path | None:
    """First existing companion among JSON then YAML neighbours, else None."""
    ap = companion_path_for_notebook(notebook_path)
    if ap.is_file():
        return ap
    for yp in companion_yaml_paths_for_notebook(notebook_path):
        if yp.is_file():
            return yp
    return None


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
    raw = path.read_text(encoding="utf-8").strip()
    suf = path.suffix.lower()
    if suf in (".yaml", ".yml"):
        parsed = yaml.safe_load(raw or "")
        if not isinstance(parsed, dict):
            raise ValueError(f"YAML companion root must be a mapping: {path}")
        data = parsed
    else:
        parsed = json.loads(raw or "{}")
        if not isinstance(parsed, dict):
            raise ValueError(f"Companion file must be a JSON object: {path}")
        data = parsed
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
                f"Companion source mismatch for cell_id={cid}: reconcile notebook and companion sidecar.",
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
    *,
    fmt: str = "json",
) -> Path:
    """Write companion JSON (**`.apynb`**) or YAML (**`.companion.yaml`**) from ordered code cells.

    Persists ``metadata.cell_id`` for any code cell that was missing one.
    Pass ``fmt="yaml"`` to emit YAML (default basename ``{stem}.companion.yaml`` when ``out`` is omitted).
    """
    from jupyter_mcp_agent.notebook import indices_of_code_cells, load_notebook_ensuring_cell_ids, validate_notebook_node

    nb_path = Path(notebook_path).expanduser().resolve()
    if not nb_path.is_file():
        raise FileNotFoundError(f"Notebook not found: {nb_path}")

    fm = fmt.lower().strip()
    if fm not in ("json", "yaml"):
        raise ValueError(f"Unsupported companion fmt={fmt!r} (expected 'json' or 'yaml').")

    nb, _ = load_notebook_ensuring_cell_ids(nb_path)
    validate_notebook_node(nb)

    if companion_out is not None:
        out = Path(companion_out).expanduser().resolve()
    elif fm == "json":
        out = companion_path_for_notebook(nb_path)
    else:
        out = nb_path.with_name(nb_path.stem + ".companion.yaml")

    rows = []
    for i in indices_of_code_cells(nb):
        cell = nb.cells[i]
        cid = cell.get("metadata", {}).get("cell_id")
        if cid is None or not str(cid).strip():
            raise ValueError(f"Code cell index {i} has no metadata.cell_id after ensure_cell_ids")
        rows.append({"cell_id": str(cid).strip(), "source": _source_as_text(cell.source)})

    payload = {"companion_version": 1, "notebook": nb_path.name, "cells": rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    if fm == "yaml":
        out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out
