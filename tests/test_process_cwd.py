"""LLM_JUPYTER_PROCESS_CWD / --process-cwd chdir helper (Cursor cwd footgun)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llm_jupyter.cli import apply_process_cwd


def test_apply_process_cwd_none_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_JUPYTER_PROCESS_CWD", raising=False)
    assert apply_process_cwd(None) is None
    assert Path.cwd() == tmp_path.resolve()


def test_apply_process_cwd_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = tmp_path / "start"
    target = tmp_path / "target"
    start.mkdir()
    target.mkdir()
    monkeypatch.chdir(start)
    monkeypatch.setenv("LLM_JUPYTER_PROCESS_CWD", str(target))
    got = apply_process_cwd()
    assert got == target.resolve()
    assert Path.cwd() == target.resolve()


def test_apply_process_cwd_explicit_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_JUPYTER_PROCESS_CWD", str(a))
    got = apply_process_cwd(str(b))
    assert got == b.resolve()
    assert Path.cwd() == b.resolve()


def test_apply_process_cwd_missing_dir_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        apply_process_cwd(str(tmp_path / "nope"))
    assert ei.value.code == 1
