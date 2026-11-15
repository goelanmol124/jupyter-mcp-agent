from __future__ import annotations

import threading

import nbformat.v4 as nbf
import nbformat as nbfmt
import pytest

from jupyter_mcp_agent.session import KernelSession, NotebookConcurrentBusy


def test_notebook_exclusive_nonblocking_raises_when_busy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC", "0")
    nb_path = tmp_path / "a.ipynb"
    nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
    nbfmt.write(nb, open(nb_path, "w", encoding="utf-8"))

    sess = KernelSession(nb_path, [], "explore")
    try:
        hold = threading.Event()
        release = threading.Event()
        caught: list[NotebookConcurrentBusy] = []

        def holder() -> None:
            with sess.notebook_exclusive(nb_path):
                hold.set()
                release.wait(timeout=10)

        def contender() -> None:
            hold.wait(timeout=10)
            try:
                with sess.notebook_exclusive(nb_path):
                    pass
            except NotebookConcurrentBusy as e:
                caught.append(e)
                assert isinstance(e.exclusive_notebook_resolved, str)
                assert e.contention_kind == "nonblocking_busy"
                assert e.lock_mode == "nonblocking"

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=contender)
        t1.start()
        t2.start()
        t2.join(timeout=10)
        assert caught, "expected NotebookConcurrentBusy while lock held"
        release.set()
        t1.join(timeout=10)
    finally:
        sess.close()


def test_notebook_exclusive_different_notebooks_parallel(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC", "0")
    nb_a = tmp_path / "a.ipynb"
    nb_b = tmp_path / "b.ipynb"
    for p in (nb_a, nb_b):
        nb = nbf.new_notebook(cells=[nbf.new_code_cell("1")])
        nbfmt.write(nb, open(p, "w", encoding="utf-8"))

    sess = KernelSession(nb_a, [], "explore")
    try:
        hold = threading.Event()
        release = threading.Event()

        def holder_a() -> None:
            with sess.notebook_exclusive(nb_a):
                hold.set()
                release.wait(timeout=10)

        def enter_b() -> None:
            hold.wait(timeout=10)
            with sess.notebook_exclusive(nb_b):
                pass

        t1 = threading.Thread(target=holder_a)
        t2 = threading.Thread(target=enter_b)
        t1.start()
        t2.start()
        t2.join(timeout=10)
        release.set()
        t1.join(timeout=10)
    finally:
        sess.close()
