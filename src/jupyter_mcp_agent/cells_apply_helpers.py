"""Shared validation for MCP ``cells_apply`` edits (keeps FastMCP + session slim)."""

from __future__ import annotations

from typing import Any, TypedDict


class CellsApplyEditItem(TypedDict):
    """One MCP ``cells_apply`` edit (**code cells** only via ``notebook_cells_patch``)."""

    cell_id: str
    source: str


def normalize_edits(edits: Any) -> list[tuple[str, str]]:
    if not isinstance(edits, list) or len(edits) == 0:
        raise ValueError("edits must be a non-empty list of {\"cell_id\": str, \"source\": str} objects.")
    out: list[tuple[str, str]] = []
    for i, raw in enumerate(edits):
        if not isinstance(raw, dict):
            raise ValueError(f"edits[{i}] must be an object with cell_id and source.")
        cid = raw.get("cell_id")
        src_f = raw.get("source")
        if cid is None or str(cid).strip() == "":
            raise ValueError(f"edits[{i}].cell_id is required.")
        if src_f is None:
            raise ValueError(f"edits[{i}].source is required (use empty string to clear code).")
        if not isinstance(src_f, str):
            src_f = str(src_f)
        out.append((str(cid).strip(), src_f))
    return out
