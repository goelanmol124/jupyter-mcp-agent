"""KernelSession wiring helpers surfaced via ``server_info``."""

from __future__ import annotations

import asyncio

import nbformat as nbfmt
import nbformat.v4 as nbf

from llm_jupyter.server import build_mcp
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


def test_kernel_field_hints_respect_verbosity_compact(monkeypatch, tmp_path) -> None:
    nb_path = tmp_path / "n.ipynb"
    nbfmt.write(nbf.new_notebook(cells=[]), open(nb_path, "w", encoding="utf-8"))

    monkeypatch.delenv("LLM_JUPYTER_VERBOSITY_COMPACT", raising=False)
    monkeypatch.delenv("LLM_JUPYTER_COMPACT_ASSISTANT_QUICK", raising=False)

    sess = KernelSession(nb_path, [], "explore")
    try:
        assert "field_hints" in sess.kernel_status()
        monkeypatch.setenv("LLM_JUPYTER_VERBOSITY_COMPACT", "1")
        assert "field_hints" not in sess.kernel_status()
    finally:
        sess.close()


def test_server_info_includes_process_session_id(tmp_path) -> None:
    nb_path = tmp_path / "n.ipynb"
    nbfmt.write(nbf.new_notebook(cells=[]), open(nb_path, "w", encoding="utf-8"))

    async def _call() -> dict:
        mcp = build_mcp(nb_path, [], "explore")
        tm = mcp._tool_manager
        try:
            body = await tm.call_tool("server_info", {}, context=None, convert_result=False)
        finally:
            getattr(mcp, "_llm_kernel_session").close()
        return dict(body)

    body = asyncio.run(_call())
    assert body.get("status") == "ok"
    sess_id = body.get("process_session_id")
    assert isinstance(sess_id, str) and len(sess_id) >= 8


def test_server_info_cursor_hints_env_gated(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LLM_JUPYTER_CURSOR_HINTS", raising=False)
    nb_path = tmp_path / "n.ipynb"
    nbfmt.write(nbf.new_notebook(cells=[]), open(nb_path, "w", encoding="utf-8"))

    async def _call() -> dict[str, object]:
        mcp = build_mcp(nb_path, [], "explore")
        tm = mcp._tool_manager
        try:
            body = await tm.call_tool("server_info", {}, context=None, convert_result=False)
        finally:
            getattr(mcp, "_llm_kernel_session").close()
        return dict(body)

    bare = asyncio.run(_call())
    assert "cursor_mcp_registry_key_hint" not in bare
    monkeypatch.setenv("LLM_JUPYTER_CURSOR_HINTS", "1")
    hinted = asyncio.run(_call())
    assert hinted.get("cursor_mcp_registry_key_hint") == "llm-jupyter"


def test_session_cap_zero_env_falls_back_to_default(monkeypatch) -> None:
    from llm_jupyter.session import _session_cap

    monkeypatch.setenv("LLM_JUPYTER_MAX_NOTEBOOK_KERNELS", "0")
    assert _session_cap() == 32
