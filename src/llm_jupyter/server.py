"""FastMCP stdio server wiring."""

from __future__ import annotations

import os
import sys
import traceback
import uuid as _uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from llm_jupyter import __version__ as _LMJ_VERSION
from llm_jupyter.cells_apply_helpers import CellsApplyEditItem
from llm_jupyter.envelopes import stable_tool_error, stable_tool_error_with_extras
from llm_jupyter.notebook import (
    ensure_cell_ids,
    load_notebook,
    save_notebook,
    try_validate_notebook_file,
)
from llm_jupyter.paths import normalize_allowed_path
from llm_jupyter.session import (
    KernelSession,
    NotebookConcurrentBusy,
    notebook_exclusive_lock_timeout_seconds,
)
from llm_jupyter.stamp import notebook_file_stamp


def _tool_exception_traceback_text(exc: BaseException) -> str:
    try:
        # ``chain=True`` exists on TracebackException in newer Pythons only; chaining is reflected
        # by default via exception ``__cause__`` / ``__context__`` in ``.format()`` output here.
        return "".join(traceback.TracebackException.from_exception(exc).format())
    except Exception:
        try:
            return "".join(traceback.format_exception(exc))
        except TypeError:
            return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _kernel_tool_envelope(tool_result: dict[str, object]) -> dict[str, object]:
    """Unified success branch: always include ``status: ok`` alongside session fields."""

    return {"status": "ok", **tool_result}


# Canonical `mcpServers` key used in repo `.cursor/mcp.json` — matches Cursor MCP UI identifier.
_CURSOR_MCP_REGISTRY_KEY = "llm-jupyter"

PROCESS_SESSION_ID = str(_uuid.uuid4())

def _notebook_arg(notebook_default: Path | None, notebook_path: str | None) -> Path:
    raw = notebook_path or (str(notebook_default) if notebook_default else "")
    if not str(raw).strip():
        raise ValueError(
            "notebook_path is required unless the MCP server was started with --notebook / -n.",
        )
    return normalize_allowed_path(raw)


def _notebook_resolution_meta(notebook_default: Path | None, notebook_path: str | None, nb_path: Path) -> dict[str, object]:
    s = str(nb_path.expanduser().resolve())
    used = notebook_default is not None and (
        notebook_path is None or not str(notebook_path).strip()
    )
    return {"notebook_path": s, "resolved_notebook_path": s, "used_default_notebook": used}


def _mcp_tool_error(tool: str, exc: BaseException) -> dict[str, object]:
    """Consistent failure envelope so agents can attribute errors (and match server build)."""
    return stable_tool_error(tool, exc, _tool_exception_traceback_text(exc))


def _notebook_exclusive_busy(tool: str, exc: NotebookConcurrentBusy) -> dict[str, object]:
    """Busy when another notebook-scoped MCP tool already holds this .ipynb lock."""

    extras: dict[str, object] = {
        "notebook_exclusive_contended": True,
        "notebook_lock_hint": (
            "Notebook-scoped tools serialize per notebook path—avoid parallel MCP calls for the same .ipynb, "
            "or set LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC empty/inf for indefinite queueing vs the default timed wait "
            "(timed wait exhausted when notebook_exclusive_contention_kind=timeout; instant busy when nonblocking_busy)."
        ),
    }
    if exc.exclusive_notebook_resolved:
        extras["notebook_exclusive_lock_notebook_path"] = exc.exclusive_notebook_resolved
    if exc.lock_mode:
        extras["notebook_exclusive_lock_mode"] = exc.lock_mode
    if exc.timed_wait_seconds is not None:
        extras["notebook_exclusive_lock_timed_wait_seconds"] = exc.timed_wait_seconds
    if exc.contention_kind:
        extras["notebook_exclusive_contention_kind"] = exc.contention_kind
    if exc.contention_kind == "nonblocking_busy":
        extras["notebook_exclusive_busy_instant"] = True
    elif exc.contention_kind == "timeout":
        extras["notebook_exclusive_lock_timeout_hit"] = True
    return stable_tool_error_with_extras(
        tool,
        exc,
        _tool_exception_traceback_text(exc),
        **extras,
    )


def build_mcp(notebook_default: Path | None, roots: list[Path], default_mode: str) -> FastMCP:
    mcp = FastMCP(
        name="llm-jupyter",
        instructions=(
            "llm-jupyter MCP: pooled ipykernel per notebook_path; reuse the same path on run and kernel_*.\n\n"
            "- server_info lists tool_names and process_session_id (authoritative).\n"
            "- notebook_execution_plan with no selectors returns structural_probe; pass exactly one of cell_id, "
            "run_all=true, or run_until_cell_id to preview the same indices run would execute.\n"
            "- notebook_validate persists metadata.cell_ids when persist_cell_ids=true.\n"
            "- Companion mirrors (.apynb) are gated on run and execution_plan companion_strict/discovered paths.\n"
            "- Stream spill to .llm_jupyter/runs/<run_id>/ when persist_stream_outputs=external_only and large; "
            "read slices with read_run_stream_slice from stream_artifacts (filesystem).\n"
            "- halt_on_error=false still reports per-cell failures; statuses and streams explain partial runs.\n"
            "- Notebook locks: parallel same-path calls queue—notebook_exclusive_* fields on clashes.\n"
            "- Kernel pool LRU cap LLM_JUPYTER_MAX_NOTEBOOK_KERNELS (≤0 malformed ⇒ 32 default).\n"
            "- Structural edits notebook_cells_patch; cells_apply wraps code-only set_source.\n"
            "- record manifests add sources_concat_sha256_prefix; optional LLM_JUPYTER_RECORD_NOTEBOOK_SNAPSHOT copies notebook post-save.\n"
            "- Cells with metadata.llm_jupyter.exclude_from_bulk skip bulk run_all/run_until (not explicit cell_id runs).\n"
        ),
    )
    sess = KernelSession(notebook_default, roots, default_mode)

    @mcp.tool(name="run")
    def run(
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        halt_on_error: bool = True,
        mode: str | None = None,
        preview_rows: int = 8,
        max_image_side: int = 256,
        validate_first: bool = True,
        debug: bool = False,
        companion_path: str | None = None,
        companion_strict: bool = False,
        compact_assistant_quick: bool = False,
        strip_ansi_streams: bool = False,
        persist_stream_outputs: str = "full",
        omit_stream_chunks: bool | None = None,
    ) -> dict[str, object]:
        """Exactly one of cell_id / run_all / run_until_cell_id.
        Returns streams, staleness/companion summaries, and structured errors when cells fail.
        Use compact_assistant_quick or env LLM_JUPYTER_COMPACT_ASSISTANT_QUICK=1 for a slimmer assistant_quick block.
        strip_ansi_streams or env LLM_JUPYTER_STRIP_ANSI_STREAMS strips escape codes from streamed text.
        persist_stream_outputs external_only strips huge stream outputs into .llm_jupyter/run artifacts."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                return sess.run(
                    notebook_path=notebook_path,
                    cell_id=cell_id,
                    run_all=run_all,
                    run_until_cell_id=run_until_cell_id,
                    halt_on_error=halt_on_error,
                    mode=mode,
                    preview_rows=preview_rows,
                    max_image_side=max_image_side,
                    validate_first=validate_first,
                    debug=debug,
                    companion_path=companion_path,
                    companion_strict=companion_strict,
                    compact_assistant_quick=compact_assistant_quick,
                    strip_ansi_streams=strip_ansi_streams,
                    persist_stream_outputs=persist_stream_outputs,
                    omit_stream_chunks=omit_stream_chunks,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("run", e)
        except Exception as e:
            return _mcp_tool_error("run", e)

    @mcp.tool(name="notebook_execution_plan")
    def notebook_execution_plan(
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        validate_first: bool = True,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, object]:
        """Companion + structural notebook map without kernel (structural_probe if no selectors)."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                return sess.notebook_execution_plan(
                    notebook_path=notebook_path,
                    cell_id=cell_id,
                    run_all=run_all,
                    run_until_cell_id=run_until_cell_id,
                    validate_first=validate_first,
                    companion_path=companion_path,
                    companion_strict=companion_strict,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("notebook_execution_plan", e)
        except Exception as e:
            return _mcp_tool_error("notebook_execution_plan", e)

    @mcp.tool(name="kernel_restart")
    def kernel_restart(
        notebook_path: str | None = None,
        art_prefix_hint: str | None = None,
    ) -> dict[str, object]:
        """Restart ipykernel for this notebook; bumps kernel_generation for that path only."""
        try:
            path = sess.notebook_path_for_kernel_tool(notebook_path)
            with sess.notebook_exclusive(path):
                body = sess.kernel_restart(notebook_path=notebook_path, art_prefix=art_prefix_hint)
                return _kernel_tool_envelope(dict(body))
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("kernel_restart", e)
        except Exception as e:
            return _mcp_tool_error("kernel_restart", e)

    @mcp.tool(name="kernel_interrupt")
    def kernel_interrupt(notebook_path: str | None = None) -> dict[str, object]:
        """Interrupt the ipykernel tied to notebook_path."""
        try:
            path = sess.notebook_path_for_kernel_tool(notebook_path)
            with sess.notebook_exclusive(path):
                body = sess.kernel_interrupt(notebook_path=notebook_path)
                return _kernel_tool_envelope(dict(body))
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("kernel_interrupt", e)
        except Exception as e:
            return _mcp_tool_error("kernel_interrupt", e)

    @mcp.tool(name="kernel_status")
    def kernel_status(notebook_path: str | None = None) -> dict[str, object]:
        """kernel_alive=ipykernel subprocess alive; notebook_kernel_active=a pooled handle exists (subprocess may still be dead). See field_hints."""
        try:
            path = sess.notebook_path_for_kernel_tool(notebook_path)
            with sess.notebook_exclusive(path):
                body = sess.kernel_status(notebook_path=notebook_path)
                return _kernel_tool_envelope(dict(body))
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("kernel_status", e)
        except Exception as e:
            return _mcp_tool_error("kernel_status", e)



    @mcp.tool(name="clear_outputs")
    def clear_outputs(
        notebook_path: str | None = None,
        clear_execution_counts: bool = True,
        validate_before: bool = True,
        validate_after: bool = True,
    ) -> dict[str, object]:
        """Strip persisted outputs from code cells; optional execution_count reset."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                if validate_before:
                    try_validate_notebook_file(nb_path)
                nb = load_notebook(nb_path)
                for cell in nb.cells:
                    if cell.cell_type != "code":
                        continue
                    cell.outputs = []
                    if clear_execution_counts:
                        cell.execution_count = None
                save_notebook(nb, nb_path)
                if validate_after:
                    try_validate_notebook_file(nb_path)
                return {
                    "status": "ok",
                    "llm_jupyter_version": _LMJ_VERSION,
                    **_notebook_resolution_meta(notebook_default, notebook_path, nb_path),
                    "note": "outputs_cleared",
                }
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("clear_outputs", e)
        except Exception as e:
            return _mcp_tool_error("clear_outputs", e)

    @mcp.tool(name="notebook_validate")
    def notebook_validate(
        notebook_path: str | None = None,
        persist_cell_ids: bool = False,
    ) -> dict[str, object]:
        """Structural nbformat validation; optional persist of metadata.cell_id for every cell."""

        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                try_validate_notebook_file(nb_path)
                changed = False
                if persist_cell_ids:
                    nb = load_notebook(nb_path)
                    changed = ensure_cell_ids(nb, persist_path=nb_path)
                stamp = notebook_file_stamp(nb_path)
                return {
                    "status": "ok",
                    "llm_jupyter_version": _LMJ_VERSION,
                    **_notebook_resolution_meta(notebook_default, notebook_path, nb_path),
                    "persist_cell_ids_used": bool(persist_cell_ids),
                    "cell_ids_assigned_written": changed,
                    "notebook_file_stamp": stamp,
                }
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("notebook_validate", e)
        except Exception as e:
            return _mcp_tool_error("notebook_validate", e)
    @mcp.tool(name="cells_apply")
    def cells_apply(
        notebook_path: str | None = None,
        edits: list[CellsApplyEditItem] | None = None,
        validate_first: bool = True,
    ) -> dict[str, object]:
        """Code-cell only: each edit is {\"cell_id\": \"…\", \"source\": \"…\"} (set_source on code). For markdown/raw or insert/move/delete use notebook_cells_patch in one batch."""
        try:
            if edits is None:
                raise ValueError("edits is required — list like [{\"cell_id\": \"…\", \"source\": \"…\"}]")
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                return sess.cells_apply(notebook_path=notebook_path, edits=edits, validate_first=validate_first)
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("cells_apply", e)
        except Exception as e:
            return _mcp_tool_error("cells_apply", e)

    @mcp.tool(name="notebook_cells_patch")
    def notebook_cells_patch(
        notebook_path: str | None = None,
        operations: list[dict[str, object]] | None = None,
        validate_first: bool = True,
    ) -> dict[str, object]:
        """Structural notebook edits as ordered ops insert/delete/move/set_source; returns cells_summary + stamp."""
        try:
            if operations is None:
                raise ValueError(
                    'operations is required — e.g. [{"op":"insert","cell_type":"code","source":"...",'
                    '"at_index":0}, {"op":"set_source","cell_id":"…","source":"..."}]'
                )
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                return sess.notebook_cells_patch(
                    notebook_path=notebook_path,
                    operations=operations,
                    validate_first=validate_first,
                    set_source_must_be_code=False,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("notebook_cells_patch", e)
        except Exception as e:
            return _mcp_tool_error("notebook_cells_patch", e)

    @mcp.tool(name="variable_preview")
    def variable_preview(
        notebook_path: str | None = None,
        names: object | None = None,
        max_chars_each: int = 400,
        names_strict: bool = False,
    ) -> dict[str, object]:
        """Capped repr for dotted-free identifiers; names_omitted_invalid lists bad tokens; names_strict rejects them."""
        try:
            path = sess.notebook_path_for_kernel_tool(notebook_path)
            with sess.notebook_exclusive(path):
                return sess.variable_preview(
                    notebook_path=notebook_path,
                    names=names,
                    max_chars_each=max_chars_each,
                    names_strict=names_strict,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("variable_preview", e)
        except Exception as e:
            return _mcp_tool_error("variable_preview", e)



    @mcp.tool(name="server_info")
    def server_info() -> dict[str, object]:
        """No-kernel smoke: version, tools_n (see tools_n_deprecation_hint), tool_names, python path, cwd, serve default, registry key (see MCP instructions)."""
        nb_def = str(notebook_default.expanduser().resolve()) if notebook_default else None
        tool_names: list[str] = []
        tm = getattr(mcp, "_tool_manager", None)
        if tm is not None:
            try:
                tool_names = sorted(t.name for t in tm.list_tools())
            except Exception:
                tool_names = []
        lock_to = notebook_exclusive_lock_timeout_seconds()
        kernel_pool = sess.notebook_kernel_pool_paths_resolved()
        out_si: dict[str, object] = {
            "status": "ok",
            "llm_jupyter_version": _LMJ_VERSION,
            "process_session_id": PROCESS_SESSION_ID,
            "tools_n": len(tool_names),
            "tools_n_deprecation_hint": (
                "Strictly len(tool_names)—use tool_names as the authoritative tool list for this MCP process; "
                "pair with llm_jupyter_version (not repository README prose alone)."
            ),
            "python_executable": sys.executable,
            "process_pid": os.getpid(),
            "process_cwd": os.getcwd(),
            "default_notebook_path": nb_def,
            "extra_roots_resolved": [str(p.expanduser().resolve()) for p in roots],
            "effective_allowed_roots": sess.effective_allowed_roots_resolved_strings(),
            "default_mode": default_mode,
            "tool_names": tool_names,
            "notebook_exclusive_lock_acquire_timeout_sec": lock_to,
            "notebook_exclusive_lock_waits_forever": lock_to is None,
            "notebook_kernel_pool_n": len(kernel_pool),
            "notebook_kernel_pool_paths_resolved": kernel_pool,
        }
        hints = os.environ.get("LLM_JUPYTER_CURSOR_HINTS", "").strip().lower()
        if hints in ("1", "true", "yes", "on"):
            out_si["cursor_mcp_registry_key_hint"] = _CURSOR_MCP_REGISTRY_KEY
        return out_si

    # Let local tooling (e.g. scripts/agent_mcp_selftest.py) shut down kernels cleanly between calls.
    mcp._llm_kernel_session = sess  # noqa: SLF001
    return mcp
