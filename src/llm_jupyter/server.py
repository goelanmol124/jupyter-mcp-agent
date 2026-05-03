"""FastMCP stdio server wiring."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from llm_jupyter import __version__ as _LMJ_VERSION
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


def _notebook_arg(notebook_default: Path | None, notebook_path: str | None) -> Path:
    raw = notebook_path or (str(notebook_default) if notebook_default else "")
    if not str(raw).strip():
        raise ValueError(
            "notebook_path is required unless the MCP server was started with --notebook / -n.",
        )
    return normalize_allowed_path(raw)


def _mcp_tool_error(tool: str, exc: BaseException) -> dict[str, object]:
    """Consistent failure envelope so agents can attribute errors (and match server build)."""
    return {
        "status": "error",
        "llm_jupyter_version": _LMJ_VERSION,
        "tool": tool,
        "tool_error": str(exc),
        "exc_type": type(exc).__name__,
        "exc_message": str(exc),
        "traceback": _tool_exception_traceback_text(exc),
    }


def _notebook_exclusive_busy(tool: str, exc: NotebookConcurrentBusy) -> dict[str, object]:
    """Busy when another notebook-scoped MCP tool already holds this .ipynb lock."""

    return {
        "status": "error",
        "llm_jupyter_version": _LMJ_VERSION,
        "tool": tool,
        "tool_error": str(exc),
        "notebook_exclusive_contended": True,
        "notebook_lock_hint": (
            "Notebook-scoped tools serialize per notebook path—avoid parallel MCP calls for the same .ipynb, "
            "or set LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC empty/inf for a blocking queue vs the default timed wait."
        ),
    }


def build_mcp(notebook_default: Path | None, roots: list[Path], default_mode: str) -> FastMCP:
    mcp = FastMCP(
        name="llm-jupyter",
        instructions=(
            "llm-jupyter: notebook-keyed kernels (multiple .ipynb in one MCP process). "
            "Each notebook_path gets its own ipykernel; pass the same notebook_path on run and kernel_* for that artefact. "
            "Prefer server_info (no kernel) when sanity-checking version/cwd/serve -n wiring in a new session; "
            "it also lists tool_names from this process—prefer that over guessing tool sets from prose. "
            "This repo's .cursor/mcp.json registers the server under mcpServers key \"llm-jupyter\". "
            "kernel_restart / kernel_interrupt / kernel_status require notebook_path unless serve was started with -n "
            "(then omit for the default). Relative paths resolve vs server cwd. "
            "Call notebook_outline before run(..., cell_id=...) when you need cell ids. "
            "halt_on_error=false asks nbclient to keep executing yet failures still arrive as status:error, "
            "execution_error, traceback-bearing stderr payloads, kernel_errors_truncated—not silent ok. "
            "kernel_runtime_ms spans run() through the assembled run payload dict (excluding manifest append and MCP encoding); phase_timings_ms lists coarse splits. "
            "post_execute_through_chunks_ms rolls up persistence + previews + building stdout/stderr chunk maps for the reply; "
            "notebook_save_after_execute_ms isolates nbformat notebook save (large cell outputs ⇒ slow writes); "
            "streams_previews_prepare_ms covers preview extraction and stream join/chunk/summary. "
            "Tool replies include llm_jupyter_version; if it disagrees with the repo you are editing, "
            "the MCP Python env is probably not loading workspace src (see mcp.json PYTHONPATH). "
            "On failures, status:error payloads include \"tool\" (which handler failed), tool_error, traceback, "
            "exc_type/exc_message (stable fields for agents, including kernel_* path/permission errors). "
            "Notebook-scoped tools serialize per notebook path so parallel MCP calls for the **same file** queue "
            "instead of overlapping kernels/notebook saves; notebook_exclusive_contended errors mean a clash or timed wait—"
            "tune LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC (default 900s wait; empty / inf waits forever). "
            "kernel_generation and in-RAM kernel handles reset when the MCP stdio process restarts—use server_info "
            "process_pid to correlate reconnects; counters are not durable across process lifetimes. "
            "Stream payloads: streams_by_cell_executed is authoritative per executed code cell; stream_summary rolls up "
            "totals; stdout_chunks/stderr_chunks slice the concatenation of cell stdouts/stderrs (keys are chunk indices, "
            "not cell ids). "
            "run(..., strip_ansi_streams=true) or env LLM_JUPYTER_STRIP_ANSI_STREAMS=1 strips ANSI escapes from "
            "captured stdout/stderr (and per-cell stream tails) for readability. "
            "dry_run resolves the same selectors as run against the saved notebook without executing or starting a kernel; "
            "use it to confirm notebook_path + cell_id/run_all/run_until match before an expensive run. "
            "server_info includes notebook_kernel_pool_paths_resolved (warm .ipynb kernel slots, MRU last); "
            "LLM_JUPYTER_MAX_NOTEBOOK_KERNELS caps the pool and evicts LRU. "
            "Huge stdout/stderr mainly inflates notebook_execute_loop_ms (Jupyter stream IPC), not only JSON payload assembly. "
            "record mode hashes a fixed scientific stack whitelist (see changelog); env LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC "
            "may reuse that snapshot briefly (can lag mid-session pip installs). "
            "notebook_outline(include_sources=true, ...) returns capped full sources per cell — see response limits. "
            "notebook_outline defaults persist_cell_ids=false (read-mostly); pass persist_cell_ids=true to assign "
            "metadata.cell_id to code/markdown/raw cells missing one. notebook_cells_patch runs ordered ops "
            "insert|delete|move|set_source in one save (returns cells_summary); cells_apply is code-only source replace."
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
    ) -> dict[str, object]:
        """Exactly one of cell_id / run_all / run_until_cell_id.
        Returns streams, staleness/companion summaries, and structured errors when cells fail.
        Use compact_assistant_quick or env LLM_JUPYTER_COMPACT_ASSISTANT_QUICK=1 for a slimmer assistant_quick block.
        strip_ansi_streams or env LLM_JUPYTER_STRIP_ANSI_STREAMS strips escape codes from streamed text."""
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
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("run", e)
        except Exception as e:
            return _mcp_tool_error("run", e)

    @mcp.tool(name="dry_run")
    def dry_run(
        notebook_path: str | None = None,
        cell_id: str | None = None,
        run_all: bool = False,
        run_until_cell_id: str | None = None,
        validate_first: bool = True,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, object]:
        """Resolve the same run selector as run against the saved notebook—no kernel start or execute."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                return sess.resolve_run_targets(
                    notebook_path=notebook_path,
                    cell_id=cell_id,
                    run_all=run_all,
                    run_until_cell_id=run_until_cell_id,
                    validate_first=validate_first,
                    companion_path=companion_path,
                    companion_strict=companion_strict,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("dry_run", e)
        except Exception as e:
            return _mcp_tool_error("dry_run", e)

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
        """Inspect kernel_generation / alive for notebook_path (omit if -n default matches)."""
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
                    "notebook_path": str(nb_path),
                    "note": "outputs_cleared",
                }
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("clear_outputs", e)
        except Exception as e:
            return _mcp_tool_error("clear_outputs", e)

    @mcp.tool(name="notebook_validate")
    def notebook_validate(notebook_path: str | None = None) -> dict[str, object]:
        """Structural nbformat-only validation (cheap; no execution).
        Keep for explicit ``validate`` calls; on the hot execution path prefer ``run(..., validate_first=true)``."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                try_validate_notebook_file(nb_path)
                return {
                    "status": "ok",
                    "llm_jupyter_version": _LMJ_VERSION,
                    "notebook_path": str(nb_path),
                }
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("notebook_validate", e)
        except Exception as e:
            return _mcp_tool_error("notebook_validate", e)

    @mcp.tool(name="notebook_outline")
    def notebook_outline(
        notebook_path: str | None = None,
        persist_cell_ids: bool = False,
        preview_chars: int = 200,
        include_sources: bool = False,
        max_source_chars: int = 8000,
        max_cells_with_sources: int = 64,
        max_total_source_chars: int = 120000,
    ) -> dict[str, object]:
        """Map cells without a kernel; include_sources=true adds capped source_full fields per outline row."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                try_validate_notebook_file(nb_path)
                nb = load_notebook(nb_path)
                if persist_cell_ids:
                    ensure_cell_ids(nb, persist_path=nb_path)
                cap = max(48, min(int(preview_chars), 2000))

                include_src = bool(include_sources)
                per_cap = max(200, min(int(max_source_chars), 80_000)) if include_src else 0
                max_cells_eff = max(1, min(int(max_cells_with_sources), 512)) if include_src else 0
                total_budget = (
                    max(4096, min(int(max_total_source_chars), 512_000)) if include_src else 0
                )

                def _src_text(cell_src: str | list[str]) -> str:
                    if isinstance(cell_src, list):
                        return "".join(cell_src)
                    return str(cell_src)

                rows: list[dict[str, object]] = []
                code_n = 0
                code_indices: list[int] = []
                total_written = 0
                cells_with_source = 0
                include_sources_truncated = False

                for i, cell in enumerate(nb.cells):
                    ctype = str(cell.get("cell_type", ""))
                    meta = cell.get("metadata") if isinstance(cell.get("metadata"), dict) else {}
                    cid = meta.get("cell_id") if ctype in ("code", "markdown", "raw") else None
                    raw = _src_text(cell.source)
                    snippet = raw.strip("\n")
                    if len(snippet) > cap:
                        snippet = snippet[: max(1, cap - 3)] + "..."
                    row: dict[str, object] = {
                        "index": i,
                        "cell_type": ctype,
                        "cell_id": str(cid).strip() if cid else None,
                        "source_preview": snippet,
                    }
                    if include_src:
                        if cells_with_source >= max_cells_eff:
                            row["source_full_omitted"] = "cell_cap"
                        elif total_written >= total_budget:
                            row["source_full_omitted"] = "char_cap"
                        else:
                            full = raw
                            room_cell = per_cap
                            room_budget = total_budget - total_written
                            room = max(0, min(room_cell, room_budget))
                            if room == 0:
                                row["source_full_omitted"] = "char_cap"
                            else:
                                if len(full) > room:
                                    frag = full[: max(1, room - 3)] + "..."
                                    include_sources_truncated = True
                                else:
                                    frag = full
                                row["source_full"] = frag
                                total_written += len(frag)
                                cells_with_source += 1
                    rows.append(row)
                    if ctype == "code":
                        code_n += 1
                        code_indices.append(i)

                body: dict[str, object] = {
                    "status": "ok",
                    "llm_jupyter_version": _LMJ_VERSION,
                    "notebook_filename": nb_path.name,
                    "code_cell_count": code_n,
                    "code_cell_indices": code_indices,
                    "notebook_path": str(nb_path.resolve()),
                    "persist_cell_ids_used": bool(persist_cell_ids),
                    "preview_chars_used": cap,
                    "cells": rows,
                }
                if include_src:
                    body["include_sources_used"] = True
                    body["max_source_chars_used"] = per_cap
                    body["max_cells_with_sources_used"] = max_cells_eff
                    body["max_total_source_chars_used"] = total_budget
                    body["source_chars_emitted"] = total_written
                    body["cells_with_source_emitted"] = cells_with_source
                    body["include_sources_truncated"] = include_sources_truncated
                return body
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("notebook_outline", e)
        except Exception as e:
            return _mcp_tool_error("notebook_outline", e)

    @mcp.tool(name="cells_apply")
    def cells_apply(
        notebook_path: str | None = None,
        edits: list[dict[str, str]] | None = None,
        validate_first: bool = True,
    ) -> dict[str, object]:
        """Patch code cells: each edit is {\"cell_id\": \"…\", \"source\": \"…\"}. Saves .ipynb; duplicate ids last wins."""
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
    ) -> dict[str, object]:
        """Bounded repr previews for dotted-free identifiers in live kernel (cold ⇒ <not defined>)."""
        try:
            path = sess.notebook_path_for_kernel_tool(notebook_path)
            with sess.notebook_exclusive(path):
                return sess.variable_preview(
                    notebook_path=notebook_path,
                    names=names,
                    max_chars_each=max_chars_each,
                )
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("variable_preview", e)
        except Exception as e:
            return _mcp_tool_error("variable_preview", e)

    @mcp.tool(name="companion_validate")
    def companion_validate(
        notebook_path: str | None = None,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, object]:
        """Cross-check `.apynb` or `.companion.yaml` neighbours vs notebook code cells."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            with sess.notebook_exclusive(nb_path):
                rep = sess.inspect_companion(
                    notebook_path=notebook_path,
                    companion_path=companion_path,
                    companion_strict=companion_strict,
                )
            return {"status": "ok", "llm_jupyter_version": _LMJ_VERSION, "report": rep}
        except NotebookConcurrentBusy as e:
            return _notebook_exclusive_busy("companion_validate", e)
        except Exception as e:
            return _mcp_tool_error("companion_validate", e)

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
        return {
            "status": "ok",
            "llm_jupyter_version": _LMJ_VERSION,
            "tools_n": len(tool_names),
            "tools_n_deprecation_hint": "Same as len(tool_names); kept for older clients.",
            "cursor_mcp_registry_key_hint": _CURSOR_MCP_REGISTRY_KEY,
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

    # Let local tooling (e.g. scripts/agent_mcp_selftest.py) shut down kernels cleanly between calls.
    mcp._llm_kernel_session = sess  # noqa: SLF001
    return mcp
