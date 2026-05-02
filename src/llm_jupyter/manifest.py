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
