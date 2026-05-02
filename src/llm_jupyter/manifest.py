from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_manifest(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":"), sort_keys=False) + "\n")
