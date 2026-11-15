from __future__ import annotations

from jupyter_mcp_agent.session import KernelSession, NotebookKernelHandle


def _handle(
    *,
    kernel_generation: int = 1,
    full_top_to_bottom_at_generation: int | None = None,
) -> NotebookKernelHandle:
    h = NotebookKernelHandle(execute_timeout_sec=600)
    h.kernel_generation = kernel_generation
    h.full_top_to_bottom_at_generation = full_top_to_bottom_at_generation
    return h


def test_stale_notes_full_run_ok():
    sess = KernelSession(None, [], "explore")
    h = _handle(kernel_generation=2, full_top_to_bottom_at_generation=2)
    stale, notes = sess._compute_stale_notes_after_run(True, "ok", h, restart_since_previous=False)
    assert not stale
    assert notes == []


def test_stale_notes_interrupted():
    sess = KernelSession(None, [], "explore")
    h = _handle()
    stale, notes = sess._compute_stale_notes_after_run(False, "interrupted", h, restart_since_previous=False)
    assert stale
    assert len(notes) == 1
    assert "Interrupted" in notes[0]


def test_stale_notes_error_with_generation_mismatch():
    sess = KernelSession(None, [], "explore")
    h = _handle(kernel_generation=2, full_top_to_bottom_at_generation=1)
    stale, notes = sess._compute_stale_notes_after_run(False, "error", h, restart_since_previous=True)
    assert stale
    assert any("errors" in n.lower() for n in notes)
    assert any("kernel_generation" in n for n in notes)


def test_stale_notes_partial_no_restart_no_blame():
    sess = KernelSession(None, [], "explore")
    h = _handle(kernel_generation=1, full_top_to_bottom_at_generation=None)
    stale, notes = sess._compute_stale_notes_after_run(False, "ok", h, restart_since_previous=False)
    assert stale
    assert any("Partial run" in n for n in notes)
    assert any("No successful full-notebook rerun" in n for n in notes)
    assert not any("kernel_generation changed since the previous MCP tool" in n for n in notes)


def test_stale_notes_partial_restart_adds_explicit_note():
    sess = KernelSession(None, [], "explore")
    h = _handle(kernel_generation=2, full_top_to_bottom_at_generation=1)
    stale, notes = sess._compute_stale_notes_after_run(False, "ok", h, restart_since_previous=True)
    assert stale
    assert any("Partial run" in n for n in notes)
    assert any("kernel_generation changed since the previous MCP tool" in n for n in notes)


def test_stale_notes_partial_after_full_same_generation_only_partial_line():
    """Full rerun already stamped for this kernel_generation → no mismatch prose."""
    sess = KernelSession(None, [], "explore")
    h = _handle(kernel_generation=2, full_top_to_bottom_at_generation=2)
    stale, notes = sess._compute_stale_notes_after_run(False, "ok", h, restart_since_previous=False)
    assert stale
    assert len(notes) == 1
    assert notes[0].startswith("Partial run:")
