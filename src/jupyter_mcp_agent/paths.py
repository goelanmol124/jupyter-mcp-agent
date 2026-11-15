from __future__ import annotations

from pathlib import Path


def normalize_allowed_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def is_under_roots(candidate: Path, roots: list[Path]) -> bool:
    cand = candidate.resolve()
    try:
        return any(cand == r.resolve() or r.resolve() in cand.parents for r in roots)
    except OSError:
        return False


def allowed_roots_for_notebook(notebook_path: Path, extra_roots: list[Path] | None) -> list[Path]:
    nb = notebook_path.expanduser().resolve()
    roots = {nb.parent, nb}
    if extra_roots:
        roots.update(r.expanduser().resolve() for r in extra_roots)
    return list(roots)
