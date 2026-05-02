"""FastMCP stdio server wiring."""

from __future__ import annotations

import traceback
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from llm_jupyter.notebook import (
    load_notebook,
    save_notebook,
    try_validate_notebook_file,
)
from llm_jupyter.paths import normalize_allowed_path
from llm_jupyter.session import KernelSession


def _notebook_arg(notebook_default: Path | None, notebook_path: str | None) -> Path:
    raw = notebook_path or (str(notebook_default) if notebook_default else "")
    if not str(raw).strip():
        raise ValueError(
            "notebook_path is required unless the MCP server was started with --notebook / -n.",
        )
    return normalize_allowed_path(raw)


def build_mcp(notebook_default: Path | None, roots: list[Path], default_mode: str) -> FastMCP:
    mcp = FastMCP(
        name="llm-jupyter",
        instructions="Thin ipykernel notebook runner: use run(cell_id/run_all/run_until), kernel_* helpers, clears/validation as needed.",
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
    ) -> dict[str, object]:
        """Execute code cells: pass exactly ONE of cell_id, run_all=true, or run_until_cell_id. Response includes run_id (duplicate in manifest.jsonl)."""
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
            )
        except Exception as e:
            return {"status": "error", "tool_error": str(e), "traceback": traceback.format_exc()}

    @mcp.tool(name="kernel_restart")
    def kernel_restart(art_prefix_hint: str | None = None) -> dict[str, object]:
        """Restart kernel process; increments kernel_generation."""
        return sess.kernel_restart(art_prefix=art_prefix_hint)

    @mcp.tool(name="kernel_interrupt")
    def kernel_interrupt() -> dict[str, object]:
        """Send interrupt signal to live kernel."""
        return sess.kernel_interrupt()

    @mcp.tool(name="kernel_status")
    def kernel_status() -> dict[str, object]:
        """Inspect kernel_generation and liveness."""
        return sess.kernel_status()

    @mcp.tool(name="clear_outputs")
    def clear_outputs(
        notebook_path: str | None = None,
        clear_execution_counts: bool = True,
        validate_before: bool = True,
        validate_after: bool = True,
    ) -> dict[str, object]:
        """Strip persisted outputs from code cells; optional execution_count reset."""
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
        return {"status": "ok", "notebook_path": str(nb_path), "note": "outputs_cleared"}

    @mcp.tool(name="notebook_validate")
    def notebook_validate(notebook_path: str | None = None) -> dict[str, object]:
        """Structural nbformat validation (no execution)."""
        nb_path = _notebook_arg(notebook_default, notebook_path)
        sess.check_allowed_notebook(nb_path)
        try_validate_notebook_file(nb_path)
        return {"status": "ok", "notebook_path": str(nb_path)}

    return mcp
