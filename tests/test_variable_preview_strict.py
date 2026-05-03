"""variable_preview sanitization / strict mode (no kernel start)."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbfmt
import nbformat.v4 as nbf
import pytest

from llm_jupyter.session import KernelSession


def test_variable_preview_names_strict_rejects_bad_identifiers(tmp_path: Path) -> None:
    p = tmp_path / "vp.ipynb"
    nbfmt.write(nbf.new_notebook(cells=[nbf.new_code_cell("x=1")]), open(p, "w", encoding="utf-8"))
    sess = KernelSession(p, [], "explore")
    try:
        with pytest.raises(ValueError, match="names_strict"):
            sess.variable_preview(names=["bad.attr"], names_strict=True)
    finally:
        sess.close()
