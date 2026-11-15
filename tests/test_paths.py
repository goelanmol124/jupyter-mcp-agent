from __future__ import annotations

from pathlib import Path

import pytest

from jupyter_mcp_agent.paths import allowed_roots_for_notebook, is_under_roots, normalize_allowed_path
from jupyter_mcp_agent.session import KernelSession


def test_is_under_roots_basic(tmp_path: Path):
    nb_dir = tmp_path / "allowed_pkg"
    nb_dir.mkdir()
    nb = nb_dir / "a.ipynb"
    nb.write_text("{}", encoding="utf-8")
    roots = allowed_roots_for_notebook(nb, [])
    assert is_under_roots(nb, roots)
    outside = tmp_path / "outside_pkg" / "b.ipynb"
    outside.parent.mkdir()
    outside.write_text("{}", encoding="utf-8")
    assert not is_under_roots(outside, roots)


def test_forbidden_notebook_path(tmp_path: Path):
    good_parent = tmp_path / "proj_a"
    good_parent.mkdir()
    good = good_parent / "ok.ipynb"
    good.write_text("{}", encoding="utf-8")
    evil_parent = tmp_path / "proj_b"
    evil_parent.mkdir()
    bad = evil_parent / "nope.ipynb"
    bad.write_text("{}", encoding="utf-8")
    s = KernelSession(good, [], "explore")
    try:
        with pytest.raises(PermissionError):
            s.check_allowed_notebook(normalize_allowed_path(str(bad)))
    finally:
        s.close()
