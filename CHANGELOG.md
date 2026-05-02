## Unreleased

### Added

- **`run` response `stream_summary`:** character totals, stdout/stderr chunk counts, and trailing stream text (~1.5k chars each) surfaced at top level alongside **`stdout_chunks`**.
- **`run` payload `execution_error`:** **`ename`** and **`evalue`** from the kernel after **`CellExecutionError`** (read before **`stderr_chunks`** when triaging).
- **`notebook_outline` MCP tool:** cell **`index`** / **`cell_id`** plus short **`source_preview`** without starting a kernel — reduces malformed **`cell_id`** and avoids agents ingesting huge notebook JSON (where **attention** often favors beginnings and endings over the middle).
- **`Per-notebook ipykernels`**: Cursor shares one MCP process across chats/tools; kernels are keyed by resolved **`notebook_path`** so **`run`** on **`nb1.ipynb`** vs **`nb2.ipynb`** no longer bleeds variables. LRU cap via **`LLM_JUPYTER_MAX_NOTEBOOK_KERNELS`** (default **32**, **0** = uncapped).

### Added (demos)

- **`demos/agent_mcp_lab.ipynb`** — exercises multi-chunk stdout for MCP/agent tooling checks.

### Fixed

- **`run` on cell errors:** **`CellExecutionError`** from **nbclient** does not expose `.cell`; the handler now uses the notebook node from the execution loop. Previously this raised **`AttributeError`**, cluttered **`stderr_chunks`** with llm-jupyter’s own traceback, and left **`cells_executed`** empty and **`error_cell_id`** unset.
- **`suggested_figure_prefix`:** Prefix slug now derives from the **first cell executed in this `run`** (the first index of the selected sweep), not always the notebook’s **first code cell**.

### Changed

- **`.cursor/mcp.json`:** Default **`llm-jupyter`** args no longer include **`serve --watch`** (fewer transient MCP errors while Cursor holds a long-lived stdio session).
- **`kernel_*` MCP tools:** pass **`notebook_path`** for the notebook whose kernel you mean (omit only when **`serve -n`** is that notebook); responses include **`notebook_path`** plus **`notebook_kernel_active`** (**`kernel_status`** only) until **`run`** or **`kernel_restart`** touches that notebook.
- Documentation pass: README tool list + Cursor MCP snippet; PRD / IMPLEMENTATION aligned with shipped **`.apynb`** companions and CLI (`export-apynb`, `manifest-tail`).


## [0.1.1] — publish polish

PyPI **keywords** / **classifiers**, optional **`[release]`** extras (**`build`**, **`twine`**), **GitHub Actions** **`pytest`** on Python 3.10 and 3.12, packaging classifier fix for **`python -m build`**.

## [0.1.0] — initial beta

MCP tools: `run`, `kernel_restart`, `kernel_interrupt`, `kernel_status`, `clear_outputs`, `notebook_validate`, `companion_validate`. Companion JSON **`.apynb`**, `manifest.jsonl`, chunked stdout/stderr, previews, explore/record modes.
