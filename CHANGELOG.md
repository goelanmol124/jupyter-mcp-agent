## Unreleased

### Added

- **`run` response `stream_summary`:** character totals, stdout/stderr chunk counts, and trailing stream text (~1.5k chars each) surfaced at top level alongside **`stdout_chunks`**.

### Added (demos)

- **`demos/agent_mcp_lab.ipynb`** — exercises multi-chunk stdout for MCP/agent tooling checks.

### Fixed

- **`run` on cell errors:** **`CellExecutionError`** from **nbclient** does not expose `.cell`; the handler now uses the notebook node from the execution loop. Previously this raised **`AttributeError`**, cluttered **`stderr_chunks`** with llm-jupyter’s own traceback, and left **`cells_executed`** empty and **`error_cell_id`** unset.

### Added

- PyPI-oriented **keywords** / **classifiers**, optional **`[release]`** extras (`build`, `twine`).
- **GitHub Actions CI** (`pytest`) on Python 3.10 and 3.12.

### Changed

- Documentation pass: README tool list + Cursor MCP snippet; PRD / IMPLEMENTATION aligned with shipped **`.apynb`** companions and CLI (`export-apynb`, `manifest-tail`).

### Fixed

- **Packaging:** Dropped obsolete **PyPI Trove license classifier** (`License :: …`) so **`python -m build`** succeeds on current **setuptools** with `license = "MIT"`.

## [0.1.0] — initial beta

MCP tools: `run`, `kernel_restart`, `kernel_interrupt`, `kernel_status`, `clear_outputs`, `notebook_validate`, `companion_validate`. Companion JSON **`.apynb`**, `manifest.jsonl`, chunked stdout/stderr, previews, explore/record modes.
