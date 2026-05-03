# Changelog

## [0.2.4] — 2026-05-03

### Added

- MCP **`notebook_cells_patch`**: ordered batch **`insert`** / **`delete`** / **`move`** / **`set_source`** (each **`insert`** or **`move`**: exactly one of **`after_cell_id`**, **`before_cell_id`**, **`at_index`**); transactional preview when **`validate_first=true`**; response includes **`cells_summary`**, **`patch_effect_log`**, stamp.
- **`KernelSession.notebook_cells_patch`** with **`cells_apply`** implemented as delegated **`set_source`** ops (**code cells only**).

### Changed

- **`ensure_cell_ids`**: writes **`metadata.cell_id`** on **markdown** and **raw** cells too (stable ids for MCP structural edits).
- **`cell_index_for_stable_id`** (new export on **`notebook`**) vs **`cell_index_for_id`** (**code**-only for **`run`** resolution).
- **`notebook_outline`** lists **`cell_id`** for markdown/raw when assigned.

### Documentation

- README tools section, MCP **`instructions`**, **research-notebook-mcp** skill/rule.

---

## [0.2.3] — 2026-05-03

### Added

- **`phase_timings_ms`** breakdown: **`notebook_save_after_execute_ms`** vs **`streams_previews_prepare_ms`** nested under **`post_execute_through_chunks_ms`** totals (helps separate fat `.ipynb` writes from preview/stream chunk assembly).

### Fixed

- **`kernel_runtime_ms`**: computed after the **`run`** response dict is fully assembled (`_payload` tail was previously omitted when **`python_env_snapshot`** ran early).

---

## [0.2.2] — 2026-05-03

### Fixed

- **`record` env snapshot**: scan installed distributions once and match **only** the fixed scientific whitelist (no alphabetical `[:200]` slice that could omit real installs or waste work on giant envs). **`packages_summary_or_hash`** in manifests may **differ from 0.2.1** for the same notebook when whitelisted packages are present—that reflects the corrected selection, not flaky hashing.

### Added

- **`LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC`**: optional short-lived process cache for **`record`** **python_env_snapshot** (fingerprint `sys.prefix` / `sys.executable` / policy revision; may lag mid-session **`pip install`** until TTL).
- **`server_info`:** **`notebook_kernel_pool_n`**, **`notebook_kernel_pool_paths_resolved`** — warm notebook paths (**MRU-last**) for correlating LRU evictions with **`LLM_JUPYTER_MAX_NOTEBOOK_KERNELS`**.
- **`load_notebook_ensuring_cell_ids`**: single disk read plus **`ensure_cell_ids`** before runs / edits (fewer redundant loads on active paths).

### Documentation

- MCP **`instructions`**, README env table, **research-notebook-mcp** skill/rule: LRU pool, **`phase_timings_ms`**, **`record`** snapshot cost vs optional cache, mega-stdout and **`notebook_execute_loop_ms`** (no silent truncation).

---

## [0.2.1] — 2026-05-03

### Added

- **`dry_run` MCP tool** and **`resolve_run_targets`** session helper: same selectors as **`run`**, no kernel start or execution.
- **`run`:** **`strip_ansi_streams`** plus env **`LLM_JUPYTER_STRIP_ANSI_STREAMS`** to strip ANSI escapes from captured streams.
- **`notebook_outline`:** optional **`include_sources`** with **`max_source_chars`**, **`max_cells_with_sources`**, **`max_total_source_chars`** caps.
- **MCP `status:error`:** **`exc_type`**, **`exc_message`** (alongside **`tool_error`** / **`traceback`**).
- **`server_info`:** **`tools_n_deprecation_hint`** (**`tools_n`** remains for older clients).

### Changed

- **`run` / `dry_run`:** **`LookupError`** for unknown **`cell_id`** / **`run_until_cell_id`** includes the **resolved notebook path** (footgun when **`-n`** default differs from the outline you used).
- **`variable_preview`:** **`cold_kernel_hint`** wording when every name is **`<not defined>`**.
- **`cells_apply`:** MCP description clarifies **`cell_id`** / **`source`** edit shape.

### Documentation

- **`research-notebook-mcp-workflow`** skill and **`research-notebook-mcp-agent`** rule: compact/ANSI/stream-index and **`server_info`** trust notes.

---

## [0.2.0] — 2026-05-03

Agent trust, payload hygiene, safer notebook introspection defaults.

### Breaking

- **`notebook_outline`:** **`persist_cell_ids` defaults to `false`** — outline is read-mostly unless **`persist_cell_ids=true`** (no automatic **`cell_id`** writes to disk).

### Added

- **`server_info`:** **`process_pid`**, **`effective_allowed_roots`**, **`notebook_exclusive_lock_acquire_timeout_sec`**, **`notebook_exclusive_lock_waits_forever`**.
- **`run`:** **`compact_assistant_quick`** plus env **`LLM_JUPYTER_COMPACT_ASSISTANT_QUICK`** to omit long static **`assistant_quick`** strings.
- **Kernel MCP tools:** success payloads include **`status: "ok"`** together with existing fields.

### Changed

- **Stale notes after `run`:** clearer distinction between “no full rerun at this **`kernel_generation`** yet” and “**`kernel_generation`** changed since the previous MCP tool ended.”
- **`variable_preview`:** **`cold_kernel_hint`** only when every requested name is **`<not defined>`**.
- **MCP `status:error`:** tracebacks prefer **`TracebackException`** formatting (exception chains).
- **`notebook_validate`:** docstring positions the tool vs **`run(..., validate_first=true)`** (tool kept).
- **`cells_apply`:** MCP parameter typing for **`edits`** as **`list[dict[str, str]]`**.
- **MCP `instructions`:** stream digest ladder, PID / **`kernel_generation`** lifecycle across process restarts, compact payload switch.

### Fixed

- **MCP `status:error`:** avoid passing unsupported **`chain=`** into **`TracebackException.from_exception`** on Python 3.12 (prevented malformed JSON tracebacks leaking a secondary **`TypeError`**).


### Documentation

- **`research-notebook-mcp-workflow`** / README remain the live agent workflow references.

---

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
