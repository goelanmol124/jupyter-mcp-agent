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
from llm_jupyter.session import KernelSession

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
        "traceback": traceback.format_exc(),
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
            "Tool replies include llm_jupyter_version; if it disagrees with the repo you are editing, "
            "the MCP Python env is probably not loading workspace src (see mcp.json PYTHONPATH). "
            "On failures, status:error payloads include \"tool\" (which handler failed) plus tool_error/traceback "
            "(including kernel_* path/permission errors)."
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
    ) -> dict[str, object]:
        """Execute with exactly one of cell_id / run_all / run_until_cell_id (see MCP instructions).

        Returns assistant_quick + stream payloads + run_id; checks same-stem .apynb when present.
        Cell failure → execution_error; pre-run Python errors → status:error JSON (tool, version, traceback).
        notebook_path is relative to the MCP process cwd."""
        try:
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
            )
        except Exception as e:
            return _mcp_tool_error("run", e)

    @mcp.tool(name="kernel_restart")
    def kernel_restart(
        notebook_path: str | None = None,
        art_prefix_hint: str | None = None,
    ) -> dict[str, object]:
        """Restart ipykernel for this notebook; bumps kernel_generation for that path only."""
        try:
            return sess.kernel_restart(notebook_path=notebook_path, art_prefix=art_prefix_hint)
        except Exception as e:
            return _mcp_tool_error("kernel_restart", e)

    @mcp.tool(name="kernel_interrupt")
    def kernel_interrupt(notebook_path: str | None = None) -> dict[str, object]:
        """Interrupt the ipykernel tied to notebook_path."""
        try:
            return sess.kernel_interrupt(notebook_path=notebook_path)
        except Exception as e:
            return _mcp_tool_error("kernel_interrupt", e)

    @mcp.tool(name="kernel_status")
    def kernel_status(notebook_path: str | None = None) -> dict[str, object]:
        """Inspect kernel_generation / alive for notebook_path (omit if -n default matches)."""
        try:
            return sess.kernel_status(notebook_path=notebook_path)
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
        except Exception as e:
            return _mcp_tool_error("clear_outputs", e)

    @mcp.tool(name="notebook_validate")
    def notebook_validate(notebook_path: str | None = None) -> dict[str, object]:
        """Structural nbformat validation (no execution)."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            try_validate_notebook_file(nb_path)
            return {
                "status": "ok",
                "llm_jupyter_version": _LMJ_VERSION,
                "notebook_path": str(nb_path),
            }
        except Exception as e:
            return _mcp_tool_error("notebook_validate", e)

    @mcp.tool(name="notebook_outline")
    def notebook_outline(
        notebook_path: str | None = None,
        persist_cell_ids: bool = True,
        preview_chars: int = 200,
    ) -> dict[str, object]:
        """Map cells (index, type, code cell_id, preview) without a kernel. Includes version, filename, code_cell_indices."""
        try:
            nb_path = _notebook_arg(notebook_default, notebook_path)
            sess.check_allowed_notebook(nb_path)
            try_validate_notebook_file(nb_path)
            nb = load_notebook(nb_path)
            if persist_cell_ids:
                ensure_cell_ids(nb, persist_path=nb_path)
            cap = max(48, min(int(preview_chars), 2000))

            def _src_text(cell_src: str | list[str]) -> str:
                if isinstance(cell_src, list):
                    return "".join(cell_src)
                return str(cell_src)

            rows: list[dict[str, object]] = []
            code_n = 0
            code_indices: list[int] = []
            for i, cell in enumerate(nb.cells):
                ctype = str(cell.get("cell_type", ""))
                meta = cell.get("metadata") if isinstance(cell.get("metadata"), dict) else {}
                cid = meta.get("cell_id") if ctype == "code" else None
                raw = _src_text(cell.source)
                snippet = raw.strip("\n")
                if len(snippet) > cap:
                    snippet = snippet[: max(1, cap - 3)] + "..."
                row: dict[str, object] = {
                    "index": i,
                    "cell_type": ctype,
                    "cell_id": cid if ctype == "code" else None,
                    "source_preview": snippet,
                }
                rows.append(row)
                if ctype == "code":
                    code_n += 1
                    code_indices.append(i)

            return {
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
        except Exception as e:
            return _mcp_tool_error("notebook_outline", e)

    @mcp.tool(name="companion_validate")
    def companion_validate(
        notebook_path: str | None = None,
        companion_path: str | None = None,
        companion_strict: bool = False,
    ) -> dict[str, object]:
        """Cross-check `.apynb` vs code cells. Call after exporting the sidecar; paths resolve vs server cwd."""
        try:
            rep = sess.inspect_companion(
                notebook_path=notebook_path,
                companion_path=companion_path,
                companion_strict=companion_strict,
            )
            return {"status": "ok", "llm_jupyter_version": _LMJ_VERSION, "report": rep}
        except Exception as e:
            return _mcp_tool_error("companion_validate", e)

    @mcp.tool(name="server_info")
    def server_info() -> dict[str, object]:
        """No-kernel smoke: version, tools_n, tool_names, python path, cwd, serve default, registry key (see MCP instructions)."""
        nb_def = str(notebook_default.expanduser().resolve()) if notebook_default else None
        tool_names: list[str] = []
        tm = getattr(mcp, "_tool_manager", None)
        if tm is not None:
            try:
                tool_names = sorted(t.name for t in tm.list_tools())
            except Exception:
                tool_names = []
        return {
            "status": "ok",
            "llm_jupyter_version": _LMJ_VERSION,
            "tools_n": len(tool_names),
            "cursor_mcp_registry_key_hint": _CURSOR_MCP_REGISTRY_KEY,
            "python_executable": sys.executable,
            "process_cwd": os.getcwd(),
            "default_notebook_path": nb_def,
            "extra_roots_resolved": [str(p.expanduser().resolve()) for p in roots],
            "default_mode": default_mode,
            "tool_names": tool_names,
        }

    # Let local tooling (e.g. scripts/agent_mcp_selftest.py) shut down kernels cleanly between calls.
    mcp._llm_kernel_session = sess  # noqa: SLF001
    return mcp
