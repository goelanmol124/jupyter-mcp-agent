from __future__ import annotations

import hashlib
import os
from pathlib import Path


def notebook_file_stamp(path: str | os.PathLike[str]) -> dict[str, str | int]:
    p = Path(path)
    data = p.read_bytes()
    st = p.stat()
    h = hashlib.sha256(data).hexdigest()
    return {
        "mtime_ns": str(st.st_mtime_ns),
        "bytes": len(data),
        "sha256_prefix": h[:16],
    }
