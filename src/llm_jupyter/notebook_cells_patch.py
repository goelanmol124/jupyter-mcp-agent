"""Batch notebook cell mutations for MCP ``notebook_cells_patch`` (reject-all validation + apply)."""

from __future__ import annotations

import uuid
from typing import Any

import nbformat.v4 as nbf


def _strip_opt(s: Any) -> str | None:
    if s is None:
        return None
    t = str(s).strip()
    return t if t else None


def _count_position_keys(
    *,
    after_cell_id: str | None,
    before_cell_id: str | None,
    has_at_index: bool,
) -> int:
    return int(after_cell_id is not None) + int(before_cell_id is not None) + int(has_at_index)


def normalize_patch_operations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) == 0:
        raise ValueError(
            "operations must be a non-empty list of {\"op\": ...} objects.",
        )
    normalized: list[dict[str, Any]] = []
    for i, obj in enumerate(raw):
        if not isinstance(obj, dict):
            raise ValueError(f"operations[{i}] must be an object.")
        op_raw = obj.get("op")
        if op_raw is None:
            raise ValueError(f"operations[{i}].op is required.")
        op = str(op_raw).strip().lower()
        if op == "set_source":
            cid = _strip_opt(obj.get("cell_id"))
            if not cid:
                raise ValueError(f"operations[{i}].cell_id is required for set_source.")
            src = obj.get("source")
            if src is None:
                raise ValueError(f"operations[{i}].source is required for set_source.")
            if not isinstance(src, str):
                src = str(src)
            normalized.append({"op": "set_source", "cell_id": cid, "source": src})
        elif op == "delete":
            cid = _strip_opt(obj.get("cell_id"))
            at_idx = obj.get("at_index")
            has_at = at_idx is not None
            if cid is None and not has_at:
                raise ValueError(
                    f"operations[{i}] delete requires cell_id or at_index (exactly one).",
                )
            if cid is not None and has_at:
                raise ValueError(
                    f"operations[{i}] delete: pass only one of cell_id or at_index.",
                )
            if has_at:
                if not isinstance(at_idx, int) or isinstance(at_idx, bool):
                    raise ValueError(f"operations[{i}] at_index must be an int.")
                row: dict[str, Any] = {"op": "delete", "at_index": at_idx}
                normalized.append(row)
            else:
                normalized.append({"op": "delete", "cell_id": cid})
        elif op == "insert":
            ctype = _strip_opt(obj.get("cell_type"))
            if ctype not in ("code", "markdown", "raw"):
                raise ValueError(
                    f"operations[{i}] insert.cell_type must be code, markdown, or raw.",
                )
            src = obj.get("source")
            if src is None:
                src = ""
            if not isinstance(src, str):
                src = str(src)
            ac = _strip_opt(obj.get("after_cell_id"))
            bc = _strip_opt(obj.get("before_cell_id"))
            at_idx = obj.get("at_index")
            has_at = at_idx is not None
            nk = _count_position_keys(
                after_cell_id=ac, before_cell_id=bc, has_at_index=has_at,
            )
            if nk != 1:
                raise ValueError(
                    f"operations[{i}] insert: use exactly one of after_cell_id, before_cell_id, at_index.",
                )
            row_i: dict[str, Any] = {"op": "insert", "cell_type": ctype, "source": src}
            if ac:
                row_i["after_cell_id"] = ac
            elif bc:
                row_i["before_cell_id"] = bc
            else:
                if not isinstance(at_idx, int) or isinstance(at_idx, bool):
                    raise ValueError(f"operations[{i}] at_index must be an int.")
                row_i["at_index"] = at_idx
            normalized.append(row_i)
        elif op == "move":
            cid = _strip_opt(obj.get("cell_id"))
            if not cid:
                raise ValueError(f"operations[{i}] move.cell_id is required.")
            ac = _strip_opt(obj.get("after_cell_id"))
            bc = _strip_opt(obj.get("before_cell_id"))
            at_idx = obj.get("at_index")
            has_at = at_idx is not None
            nk = _count_position_keys(
                after_cell_id=ac, before_cell_id=bc, has_at_index=has_at,
            )
            if nk != 1:
                raise ValueError(
                    f"operations[{i}] move: use exactly one of after_cell_id, before_cell_id, at_index.",
                )
            row_m: dict[str, Any] = {"op": "move", "cell_id": cid}
            if ac:
                row_m["after_cell_id"] = ac
            elif bc:
                row_m["before_cell_id"] = bc
            else:
                if not isinstance(at_idx, int) or isinstance(at_idx, bool):
                    raise ValueError(f"operations[{i}] at_index must be an int.")
                row_m["at_index"] = at_idx
            normalized.append(row_m)
        else:
            raise ValueError(
                f"operations[{i}] unknown op {op_raw!r}; expected "
                "insert, delete, move, or set_source.",
            )
    return normalized


def notebook_cells_summary(nb: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, cell in enumerate(nb.cells):
        ctype = str(getattr(cell, "cell_type", "") or "")
        meta = cell.get("metadata") if isinstance(cell.get("metadata"), dict) else {}
        cid = meta.get("cell_id")
        out.append({"cell_index": i, "cell_type": ctype, "cell_id": str(cid) if cid else None})
    return out


def _insert_index_for(
    nb: Any,
    *,
    after_cell_id: str | None,
    before_cell_id: str | None,
    at_index: int | None,
) -> int:
    from llm_jupyter.notebook import cell_index_for_stable_id

    n = len(nb.cells)
    if at_index is not None:
        if at_index < 0 or at_index > n:
            raise ValueError(f"at_index {at_index} out of range for insert (0..{n}).")
        return at_index
    if after_cell_id is not None:
        j = cell_index_for_stable_id(nb, after_cell_id)
        return j + 1
    if before_cell_id is not None:
        j = cell_index_for_stable_id(nb, before_cell_id)
        return j
    raise AssertionError("insert position unresolved")


def _desired_insert_position_pre_pop(nb: Any, op: dict[str, Any]) -> int:
    from llm_jupyter.notebook import cell_index_for_stable_id

    """Return insert index into ``nb.cells`` BEFORE removing the moved row (range 0..len(nb.cells))."""

    n = len(nb.cells)
    if "at_index" in op:
        ix = op["at_index"]
        if not isinstance(ix, int) or isinstance(ix, bool):
            raise ValueError("move at_index must be int.")
        if ix < 0 or ix > n:
            raise ValueError(f"move at_index {ix} out of range (0..{n}).")
        return ix
    if "after_cell_id" in op:
        j = cell_index_for_stable_id(nb, op["after_cell_id"])
        return j + 1
    if "before_cell_id" in op:
        return cell_index_for_stable_id(nb, op["before_cell_id"])
    raise AssertionError("move positioning missing")


def _insert_index_after_removal(desired_pre: int, src: int, post_len: int) -> int:
    """Target index after removing ``src`` from a notebook of ``post_len+1`` cells (insert 0..post_len inclusive)."""

    want = desired_pre
    if src < want:
        want -= 1
    return max(0, min(want, post_len))


def apply_notebook_cells_patch(nb: Any, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mutate ``nb`` in place. Returns a log of coarse effects (for debugging / agents). Raises on any failure."""

    from llm_jupyter.notebook import cell_index_for_stable_id

    log: list[dict[str, Any]] = []
    for opi, op in enumerate(operations):
        kind = op["op"]
        if kind == "set_source":
            idx = cell_index_for_stable_id(nb, op["cell_id"])
            nb.cells[idx].source = op["source"]
            log.append(
                {
                    "op": "set_source",
                    "cell_id": op["cell_id"],
                    "cell_index": idx,
                },
            )
        elif kind == "delete":
            if "at_index" in op:
                ix = op["at_index"]
                n = len(nb.cells)
                if ix < 0 or ix >= n:
                    raise ValueError(f"operations[{opi}] delete at_index {ix} out of range (0..{n - 1}).")
                del nb.cells[ix]
                log.append({"op": "delete", "at_index": ix})
            else:
                cid = op["cell_id"]
                idx = cell_index_for_stable_id(nb, cid)
                del nb.cells[idx]
                log.append({"op": "delete", "cell_id": cid, "cell_index": idx})
        elif kind == "insert":
            ctype = op["cell_type"]
            if ctype == "code":
                cell = nbf.new_code_cell(op["source"])
            elif ctype == "markdown":
                cell = nbf.new_markdown_cell(op["source"])
            else:
                cell = nbf.new_raw_cell(op["source"])
            meta = cell.setdefault("metadata", {})
            new_id = str(uuid.uuid4())
            meta["cell_id"] = new_id
            ix = _insert_index_for(
                nb,
                after_cell_id=op.get("after_cell_id"),
                before_cell_id=op.get("before_cell_id"),
                at_index=op.get("at_index"),
            )
            nb.cells.insert(ix, cell)
            log.append(
                {
                    "op": "insert",
                    "cell_id": new_id,
                    "cell_index": ix,
                    "cell_type": ctype,
                },
            )
        elif kind == "move":
            cid = op["cell_id"]
            src = cell_index_for_stable_id(nb, cid)
            desired_pre = _desired_insert_position_pre_pop(nb, op)
            popped = nb.cells.pop(src)
            try:
                post_len = len(nb.cells)
                tgt = _insert_index_after_removal(desired_pre, src, post_len)
                nb.cells.insert(tgt, popped)
            except BaseException:
                nb.cells.insert(min(src, len(nb.cells)), popped)
                raise
            log.append({"op": "move", "cell_id": cid, "from_index": src, "to_index": tgt})
        else:
            raise AssertionError(f"bad op {kind}")
    return log
