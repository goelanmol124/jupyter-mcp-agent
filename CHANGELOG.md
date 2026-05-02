## Unreleased

### Changed

- **`.cursor/mcp.json` (and README example):** Set **`env.PYTHONPATH`** to **`${workspaceFolder}/src`** so **`python -m llm_jupyter`** in Cursor loads the **workspace** package. Without this, a globally installed older **`llm-jupyter`** can shadow the repo and make MCP responses look “stuck” on old behavior.
- **`notebook_outline`:** Response now includes **`notebook_filename`** and **`code_cell_indices`** near the top (after **`status`**) for faster planning and less dependence on long absolute paths.
- **`run` response shape (agent ergonomics):** First key **`assistant_quick`** summarizes status, staleness hint, **`error_one_liner`**, and stream bulk in one skim object. **`execution_error`** appears immediately after **`status`**. **`companion`** is omitted when the sidecar gate was **`skipped`** (no same-stem **`.apynb`**), reducing repetitive noise. **`stream_summary`** and metadata stay above **`stdout_chunks`** / **`stderr_chunks`**; file stamp and **`python_env_snapshot`** remain near the tail.
- **`.cursor/mcp.json`:** Default **`llm-jupyter`** args no longer include **`serve --watch`** (fewer transient MCP errors while Cursor holds a long-lived stdio session).
- **`kernel_*` MCP tools:** pass **`notebook_path`** for the notebook whose kernel you mean (omit only when **`serve -n`** is that notebook); responses include **`notebook_path`** plus **`notebook_kernel_active`** (**`kernel_status`** only) until **`run`** or **`kernel_restart`** touches that notebook.
- Documentation pass: README tool list + Cursor MCP snippet; PRD / IMPLEMENTATION aligned with shipped **`.apynb`** companions and CLI (`export-apynb`, `manifest-tail`).
- **Version echo on MCP payloads:** **`llm_jupyter_version`** is included in **`run.assistant_quick`**, **`kernel_*`** responses, and **`notebook_outline`** so agents can spot a stale global install or wrong venv before trusting tool shape.
- **`status: error` MCP payloads:** **`run`**, **`notebook_outline`**, **`notebook_validate`**, **`clear_outputs`**, **`companion_validate`**, and **`kernel_*`** handler failures include **`llm_jupyter_version`**, **`tool`**, **`tool_error`**, and **`traceback`**. Success responses for **`clear_outputs`**, **`notebook_validate`**, and **`companion_validate`** also echo **`llm_jupyter_version`**.

### Added

- **`run` response `stream_summary`:** character totals, stdout/stderr chunk counts, and trailing stream text (~1.5k chars each) surfaced at top level alongside **`stdout_chunks`**.
- **`run` payload `execution_error`:** **`ename`** and **`evalue`** from the kernel after **`CellExecutionError`** (read before **`stderr_chunks`** when triaging).
- **`notebook_outline` MCP tool:** cell **`index`** / **`cell_id`** plus short **`source_preview`** without starting a kernel — reduces malformed **`cell_id`** and avoids agents ingesting huge notebook JSON (where **attention** often favors beginnings and endings over the middle).
- **`server_info` MCP tool:** No kernel — returns **`llm_jupyter_version`**, process **`cwd`**, resolved **`serve -n`** default path (when set), extra roots, **`default_mode`**, and **`tool_names`** (runtime tool register from FastMCP) for wiring checks before **`run`**.
- **`Per-notebook ipykernels`**: Cursor shares one MCP process across chats/tools; kernels are keyed by resolved **`notebook_path`** so **`run`** on **`nb1.ipynb`** vs **`nb2.ipynb`** no longer bleeds variables. LRU cap via **`LLM_JUPYTER_MAX_NOTEBOOK_KERNELS`** (default **32**, **0** = uncapped).

### Added (demos)

- **`demos/agent_mcp_lab.ipynb`** — exercises multi-chunk stdout for MCP/agent tooling checks.

### Fixed

- **`run` on cell errors:** **`CellExecutionError`** from **nbclient** does not expose `.cell`; the handler now uses the notebook node from the execution loop. Previously this raised **`AttributeError`**, cluttered **`stderr_chunks`** with llm-jupyter’s own traceback, and left **`cells_executed`** empty and **`error_cell_id`** unset.
- **`suggested_figure_prefix`:** Prefix slug now derives from the **first cell executed in this `run`** (the first index of the selected sweep), not always the notebook’s **first code cell**.

## [0.1.1] — publish polish

PyPI **keywords** / **classifiers**, optional **`[release]`** extras (**`build`**, **`twine`**), **GitHub Actions** **`pytest`** on Python 3.10 and 3.12, packaging classifier fix for **`python -m build`**.

## [0.1.0] — initial beta

MCP tools: `run`, `kernel_restart`, `kernel_interrupt`, `kernel_status`, `clear_outputs`, `notebook_validate`, `companion_validate`. Companion JSON **`.apynb`**, `manifest.jsonl`, chunked stdout/stderr, previews, explore/record modes.
