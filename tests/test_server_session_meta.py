"""KernelSession wiring helpers surfaced via ``server_info``."""
from __future__ import annotations

import nbformat as nbfmt
import nbformat.v4 as nbf

from llm_jupyter.session import KernelSession, ansi_streams_strip_requested, assistant_quick_compact_requested


def test_effective_allowed_roots_with_default_notebook(tmp_path) -> None:
    nb_path = tmp_path / "n.ipynb"
    nb = nbf.new_notebook(cells=[])
    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    roots = sess.effective_allowed_roots_resolved_strings()
    assert str(nb_path.resolve()) in roots
    assert str(nb_path.parent.resolve()) in roots


def test_effective_allowed_roots_no_default_extra_only(tmp_path) -> None:
    extra = tmp_path / "extra_root"
    extra.mkdir()
    sess = KernelSession(None, [extra], "explore")
    assert sess.effective_allowed_roots_resolved_strings() == [str(extra.resolve())]


def test_ansi_streams_strip_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_JUPYTER_STRIP_ANSI_STREAMS", raising=False)
    assert ansi_streams_strip_requested(False) is False
    monkeypatch.setenv("LLM_JUPYTER_STRIP_ANSI_STREAMS", "1")
    assert ansi_streams_strip_requested(False) is True


def test_assistant_quick_compact_env(monkeypatch) -> None:
    monkeypatch.delenv("LLM_JUPYTER_COMPACT_ASSISTANT_QUICK", raising=False)
    assert assistant_quick_compact_requested(False) is False
    monkeypatch.setenv("LLM_JUPYTER_COMPACT_ASSISTANT_QUICK", "1")
    assert assistant_quick_compact_requested(False) is True


def test_assistant_quick_compact_explicit_wins(monkeypatch) -> None:
    monkeypatch.delenv("LLM_JUPYTER_COMPACT_ASSISTANT_QUICK", raising=False)
    assert assistant_quick_compact_requested(True) is True


def test_notebook_kernel_pool_paths_starts_empty(tmp_path) -> None:
    nb_path = tmp_path / "n.ipynb"
    nb = nbf.new_notebook(cells=[])
    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))
    sess = KernelSession(nb_path, [], "explore")
    try:
        assert sess.notebook_kernel_pool_paths_resolved() == []
    finally:
        sess.close()
