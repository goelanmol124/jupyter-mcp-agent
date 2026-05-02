# Changelog

## Unreleased


## [0.1.2] — 2026-05-03

Agent-focused MCP ergonomics and multi-notebook kernel hygiene.

### Added

- **`notebook_outline`:** Structural map (indexes, **`code_cell_indices`**, code **`cell_id`**, previews) without starting a kernel.
- **`server_info`:** No-kernel wiring check (`llm_jupyter_version`, **`tools_n`**, **`tool_names`**, **`python_executable`**, **`cursor_mcp_registry_key_hint`**, **`cwd`**, resolved **`serve -n`** default, roots, **`default_mode`**).
- **`run` helpers:** **`stream_summary`** (stream tails + chunk/char totals), **`execution_error`** (**`ename`**, **`evalue`**) after failed cells, top **`assistant_quick`** skim (`llm_jupyter_version`, status, staleness, error/stream hints).
- **Per-notebook kernels** in one MCP process; optional LRU cap **`LLM_JUPYTER_MAX_NOTEBOOK_KERNELS`**.
- **`demos/agent_mcp_lab.ipynb`** for multi-chunk stdout exercises.

### Changed

- **Payload layout:** actionable fields first (`execution_error` near **`status`**); **`companion`** omitted when gate **`skipped`**; stamps/env toward the tail.
- **Unified tool failures:** Structured **`status: error`** with **`llm_jupyter_version`**, **`tool`**, **`tool_error`**, **`traceback`** for **`run`**, **`notebook_outline`**, **`notebook_validate`**, **`clear_outputs`**, **`companion_validate`**, and **`kernel_*`**.
- **`llm_jupyter_version`** echoed on success paths where useful (`notebook_outline`, **`clear_outputs`**, **`notebook_validate`**, **`companion_validate`**, **`kernel_*`**, **`run.assistant_quick`**).
- **`.cursor/mcp.json` example / README:** no default **`serve --watch`**; **`PYTHONPATH`** = **`${workspaceFolder}/src`** so workspace **`src`** wins over an older installed package.
- **MCP docs:** **`research-notebook-mcp-agent`** rule + **`research-notebook-mcp-workflow`** skill (MCP visibility, **`server_info`** first-call habit, Cursor [MCP integrations](https://cursor.com/help/customization/mcp) link).

### Fixed

- **`run` on errors:** **`CellExecutionError`** handler uses loop notebook cell (nbclient lacks **`.cell`**); avoids agent-swallowing tracebacks and empty **`cells_executed`**.
- **`suggested_figure_prefix`:** Slug derives from **first executed cell this run**, not always the notebook’s first code cell.

## [0.1.1] — publish polish

PyPI **keywords** / **classifiers**, optional **`[release]`** extras (**`build`**, **`twine`**), **GitHub Actions** **`pytest`** on Python 3.10 and 3.12, packaging classifier fix for **`python -m build`**.

## [0.1.0] — initial beta

MCP tools: `run`, `kernel_restart`, `kernel_interrupt`, `kernel_status`, `clear_outputs`, `notebook_validate`, `companion_validate`. Companion JSON **`.apynb`**, `manifest.jsonl`, chunked stdout/stderr, previews, explore/record modes.
