from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_manifest(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":"), sort_keys=False) + "\n")


def default_manifest_file_for_notebook(notebook_path: str | Path) -> Path:
    """``manifest.jsonl`` beside the notebook (same directory)."""
    return Path(notebook_path).expanduser().resolve().parent / "manifest.jsonl"


def manifest_records_for_notebook(
    notebook_path: str | Path,
    *,
    manifest_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Load manifest records whose ``notebook_path`` resolves to the same notebook (order preserved)."""
    nb = Path(notebook_path).expanduser().resolve()
    mf = manifest_file if manifest_file is not None else default_manifest_file_for_notebook(nb)
    if not mf.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in mf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw = rec.get("notebook_path")
        if raw is None:
            continue
        try:
            if Path(str(raw)).expanduser().resolve() != nb:
                continue
        except OSError:
            continue
        out.append(rec)
    return out


def tail_manifest_records(
    notebook_path: str | Path,
    *,
    last_n: int = 8,
    manifest_file: Path | None = None,
) -> list[dict[str, Any]]:
    rows = manifest_records_for_notebook(notebook_path, manifest_file=manifest_file)
    if last_n <= 0:
        return rows
    return rows[-last_n:]


def manifest_records_for_run(
    notebook_path: str | Path,
    run_id: str,
    *,
    manifest_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Manifest rows for this notebook with a matching ``run_id`` (stable cross-turn cite)."""

    needle = str(run_id).strip()
    if not needle:
        return []
    out: list[dict[str, Any]] = []
    for row in manifest_records_for_notebook(notebook_path, manifest_file=manifest_file):
        rid = row.get("run_id")
        if rid is not None and str(rid).strip() == needle:
            out.append(row)
    return out


def explain_manifest_miss_for_run_id(
    notebook_path: str | Path,
    run_id: str,
    *,
    manifest_file: Path | None = None,
) -> str:
    # WHY this helper exists (kept in library, not only CLI):
    # - `manifest-tail --run-id` legitimately returns `[]` for several different reasons,
    #   but JSON stdout cannot carry a prose explanation without breaking parsers.
    # - Centralizing wording here lets pytest lock the UX and avoids duplicating branching
    #   logic across future CLIs/tools.
    # We strip run_id uniformly with manifest_records_for_run so the hint matches lookup rules.
    nb = Path(notebook_path).expanduser().resolve()
    needle = str(run_id).strip()
    mf = manifest_file if manifest_file is not None else default_manifest_file_for_notebook(nb)

    if not mf.is_file():
        return (
            f"jupyter-mcp-agent manifest-tail: manifest file missing at {mf}. "
            f"Runs append manifest.jsonl beside the notebook; none recorded yet."
        )

    scoped = manifest_records_for_notebook(nb, manifest_file=mf)
    if not scoped:
        # WHY distinguish: avoids chasing a typo'ed run_id when the real issue is path/cwd mismatch.
        return (
            f"jupyter-mcp-agent manifest-tail: manifest exists ({mf}) but has no notebook_path matching "
            f"{nb}. Confirm you passed this notebook path and cwd matches how runs were logged."
        )

    ids_tail = []
    # WHY sample recent ids only: manifests can be long; surfacing dozens of IDs is unreadable noise.
    for row in scoped[-min(12, len(scoped)) :]:
        rid = row.get("run_id")
        if rid is None:
            continue
        ids_tail.append(str(rid).strip())
    sample = ", ".join(ids_tail) if ids_tail else "(no run_id fields on scoped rows)"

    return (
        f"jupyter-mcp-agent manifest-tail: run_id={needle!r} not found for this notebook ({len(scoped)} runs logged). "
        f"Recent run_id samples: {sample}. Retry without --run-id (adjust --last) or paste the exact id."
    )
