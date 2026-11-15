---
name: research-notebook-mcp-workflow
description: >-
  How to work with the Research Notebook MCP and notebook R&D in general:
  inspect real data and data flow, debug with kernel truth, residual
  forensics after structural wins, keep code small and exploratory—not
  production style. Use when this MCP is configured, when doing similar
  notebook research with an LLM, or when improving a model after a first
  plateau.
---

# Research Notebook MCP — agent workflow

## Current MCP server (package `jupyter_mcp_agent`): what exists today

- Tools include **`run`**, **`kernel_*`**, **`clear_outputs`**, **`notebook_validate`**, **`notebook_execution_plan`**, **`cells_apply`**, **`notebook_cells_patch`**, **`variable_preview`**, **`server_info`**. Optional **`.apynb`** sidecar (same stem as the `.ipynb`): when that file exists, **`run`** cross-checks code-cell sources and `metadata.cell_id` before executing; use **`companion_strict=true`** to require a sidecar.

- With the repo’s **project-level MCP file** `.cursor/mcp.json` (see README): project key may be **`jupyter-mcp-agent-project`** (avoids colliding with user-scope `jupyter-mcp-agent` → live catalog id **`user-jupyter-mcp-agent`**). **Reload / enable** the project entry if you need it; for agent work, ready **`user-jupyter-mcp-agent`** is enough — otherwise run `python scripts/agent_mcp_selftest.py …` from the repo root.
- **I5 / Cursor catalog:** treat ready **`user-jupyter-mcp-agent`** (or `jupyter-mcp-agent` / `jupyter-mcp-agent-project` if present) as Cursor MCP. Only if `GetMcpTools` has **no** ready `*jupyter-mcp-agent*` server, label **`tools_selftest`** and move on. Do **not** re-list “Cursor absent” when `user-jupyter-mcp-agent` is ready. Human RELOAD / enable for project entry: `exp_C/s2/RELOAD_SMOKE.md` + `exp_C/s5/CROSS_EXP_TRANSPORT.md`. Agents cannot fix host registration.
- **Selftest roots (required for matrix / cross-tree notebooks):** always pass workspace roots so trial dirs under `benchmarks/` (or anywhere outside the default notebook parent) are allowed:
  - `python scripts/agent_mcp_selftest.py --roots . -n <nb> …` **or**
  - `LLM_JUPYTER_ROOTS=<workspace>` (os.pathsep-separated; same as `serve`)
  - Before `run`, call **`server_info`** and assert the trial path is under **`effective_allowed_roots`** (and prefer non-empty **`extra_roots_resolved`** when you passed `--roots` / env).
  - Quick operator card: `benchmarks/v04_agent_matrix/_orchestrator/exp_C/AGENT_CHECKLIST.md`.
- **Cursor primary path:** `GetMcpTools` → `CallMcpTool` on ready `user-jupyter-mcp-agent` (or other `*jupyter-mcp-agent*`). Reuse the same `notebook_path` for `run` → `variable_preview` (one kernel). CLI selftest / `mcp_session_run_preview.py` is fallback — label `tools_selftest`; do not claim `tools_cursor_mcp`.
- **Same-session:** see Gap2 — CallMcpTool same `notebook_path`, or CLI `mcp_session_run_preview` / `--session`.
- **Path semantics in MCP:** **`notebook_path`** is resolved with `Path(...).resolve()` vs the server process **`cwd`** (recommended: **`"${workspaceFolder}"`** in `.cursor/mcp.json`). Omitting `notebook_path` targets the server's default **`--notebook`/`-n`**. When introducing a fresh **`.apynb`**, do **`export-apynb` → `companion_validate` → `run`** in order—the first leg must finish before validating, or `"skipped"` can appear while the filesystem catches up with relative paths.
- **Kernel cwd:** New ipykernels start with **cwd = notebook parent** by default (`server_info.kernel_cwd_policy=notebook_parent`), so relative `data.npz` / plots next to the `.ipynb` work even when `process_cwd` is `%USERPROFILE%`/repo. Opt out: `LLM_JUPYTER_KERNEL_CWD=process` or `serve --kernel-cwd process`. `process_cwd` remains the MCP server process cwd (set via `LLM_JUPYTER_PROCESS_CWD` / `--process-cwd` when Cursor ignores mcp.json `cwd`). After `run` / `kernel_restart`, see `kernel_status.kernel_cwd`.
- **`run`** requires **exactly one** intent: **`cell_id`**, **`run_all=true`**, or **`run_until_cell_id`**. Passing more than one is an error (avoids silent “`cell_id` wins” bugs).
- Every execution returns **`run_id`** and appends it to **`manifest.jsonl`** next to the notebook—**cite `run_id` in chat** when you want durable cross-turn memory of a specific execute. **Shell:** `python -m jupyter_mcp_agent manifest-tail path/to/analysis.ipynb` (recent rows) or add **`--run-id …`** after you cite one run in chat (same notebook filter still applies). If `--run-id` matches nothing, the CLI prints a short **stderr** explanation (stdout stays JSON for piping).

## Mindset: R&D, not shipping

- Optimize for **fast understanding**, not “enterprise” structure. One screen of clear code beats five files of ceremony.
- Prefer **seeing** what happened over **asserting** correctness on paper.
- A big metric jump is usually a **checkpoint**, not a finish line—ask what structure remains.

## Data: look with your eyes

- **Open real artefacts**: sample rows, skim saved tables on disk, **view plots** (thumbnails + originals), read **stderr** as carefully as stdout. Summaries and metrics are hints, not substitutes.
- Trace **how data moves**: after non-trivial transforms, surface **intermediate structure** (shapes, dtypes, key columns, class balance, NaNs, heads of intermediate frames, a line plot of a middle series). The story is often in the **path**, not only the final metric.
- Use **`variable_preview`** (or equivalent MCP tool) for **named values and behaviour**—not only types—when something “looks off.” Request bounded previews; escalate to full paths when needed.
- Slice by **cohort / batch / group** when those ids exist at prediction time—even if scaffold notes say to ignore them. Global metrics hide opposing effects.

## Debugging

- Trust **kernel truth** over stale notebook output: respect **`kernel_generation`**, **`outputs_might_be_stale`**, rerun after **restart** when diagnosing. Printed scores in cells can be **stale or fake**—recompute before trusting.
- Narrow the loop: change **one cell or one assumption**, re-run (`run_until` / targeted cell), compare before/after streams and previews.
- Prefer **visible failure** in the notebook (clear traceback, prints) over silent catches while exploring.
- Fit preprocessors on **train only** (or within fold). Replicating a leaky concat-fit is fine as a diagnostic, not as the final pipeline.

## After the first structural win (do not stop early)

When a simple fix (honest prep, per-group models, dropping a leak) cuts error sharply, **keep diagnosing inside the new regime**. Agent benchmark arcs that stop at “fit per batch / per cohort” leave large gains on the table; winners keep asking what remains.

**Residual forensics (preferred next step):**
1. Plot / correlate **residuals** vs features, interactions, and cohort id.
2. Check **sign flips and slope changes across groups** (per-group Pearson / scatter)—intercept-only or one-hot group dummies often fail when slopes differ.
3. Name a **small explicit structure** (e.g. group-specific slopes, one interaction) before jumping to a large tree or poly blast.
4. Run a **negative control**: mean-shift / intercept-only vs slope / interaction heterogeneity. If intercept-only ≈ naive global, the story is slopes, not offsets.
5. Only then try flexible corrections (**residual** GBR/HGBR on top of a structural linear model, or compact engineered features). Prefer stack/blend over replacing a clear linear story with an opaque global tree.

**Anti-patterns that look productive but stall understanding:**
- Shipping the first per-group ridge/ElasticNet because CV/LOBO “selected” it, without residual plots.
- Jumping straight to per-group GBR/RF as a substitute for naming interactions.
- Adding polynomials that help train CV under **covariate shift** but hurt held-out error—probe extras with a holdout or group CV, not test shopping.
- Treating selection discipline as a reason to **ignore** a clearly better structural hypothesis; use CV to choose among *named* candidates after forensics, not to freeze the first plateau.

**Stopping rule:** stop when residuals look unstructured *and* negative controls agree—or when further terms only fit train/shift artefacts. Do not stop merely because RMSE “looks much better than baseline.”

## Operator card (3 repeating gaps — fix once, stop rediscovering)

| # | Gap | Do this |
|---|-----|---------|
| 1 | No ready `*jupyter-mcp-agent*` in catalog | Label **`tools_selftest`**. Ready **`user-jupyter-mcp-agent`** counts as Cursor. Project key may be **`jupyter-mcp-agent-project`** (human enable/RELOAD). Cite CROSS_EXP_TRANSPORT; do not invent a new “tool gap” every pack. |
| 2 | One-shot selftest = new kernel | Use **CallMcpTool** with the same `notebook_path`, or CLI **`scripts/mcp_session_run_preview.py`** / **`agent_mcp_selftest.py --session`**, for `run`→`variable_preview`. |
| 3 | Kernel cwd / relative paths | Confirm `kernel_cwd_policy` / `kernel_cwd`; abs path if load fails (R013). |

## Anti-stamp (tools arm honesty)

- **Not tools evidence:** offline `solve_core` / numpy recipe → write notebook → post-hoc `mcp_refresh` that hardcodes preview names and patches `agent_report.variable_preview_count` / `used_mcp`.
- **Is tools evidence:** agent (or interactive session) uses MCP to **discover** middle states; cite **`run_id`** from that session; prefer preview names that appear in **`manifest.jsonl`** / live tool results, not only a patched count.
- If a wave is intentionally scripted (fixture smoke / Wilson ops), label **`scripted_selftest`** (or footnote harvest as scripted) — do **not** claim skill/process_pass MCP habit from a stamp. See `benchmarks/v04_agent_matrix/_orchestrator/meta_tool_improve/GRADING_SCRIPTED_STAMP.md`.
- **POISON:** `mcp_refresh` / `solve_*_live` post-hoc patch → always label **`scripted_selftest`**; never **`tools_selftest`** or **`tools_cursor_mcp`**.

## MCP usage habits

- Prefer editing in Cursor’s notebook UI; optional **`.apynb`** JSON (`companion_version`, `cells` with `cell_id` + `source` per **code cell in order**) is for agents and scripts—keep it in sync with the notebook or validation fails before **`run`**. **`companion_validate`** checks drift without executing. Refresh the sidecar after UI-only edits: **`python -m jupyter_mcp_agent export-apynb path/to/analysis.ipynb`**.
- Prefer **`run_all`** or **`run_until`** when reproducibility of the chain matters; note **`explore`** vs **`record`** when conclusions or shared figures matter (use `suggested_figure_prefix` / `LLM_NB_ART_PREFIX` when recording — see `exp_C/AGENT_CHECKLIST.md`).
- **Transport labels:** claim `tools_cursor_mcp` only after catalog shows a ready **`user-jupyter-mcp-agent`** (or `jupyter-mcp-agent` / `jupyter-mcp-agent-project`) **and** a Cursor-invoked `server_info` smoke; else use selftest/`build_mcp` and label **`tools_selftest`**. Scripted stamp waves: **`scripted_selftest`**. Do not silent-nbconvert on `PermissionError` without labeling **`local_fallback`**.
- **Selftest CLI:** `python scripts/agent_mcp_selftest.py -n path/to.ipynb TOOL key=value` (positional tool name; not `--tool`).
- **One kernel session:** see Gap2.
- **Qualifying previews:** after a structural win, preview **middle-state / residual / regime** names (`resid_*`, scores, cohort frames)—not dtype dumps of `X_train`/`y_train`. Count alone ≠ forensics.
- **`variable_preview`:** pass `names=["x", "y"]` (list), not `name=`.
- **`notebook_cells_patch` insert:** use exactly one of `at_index` / `after_cell_id` / `before_cell_id`.
- **Paths in cells:** relative to notebook parent (see **Kernel cwd**) or absolute.
- **Baseline observability:** Unreachable analyst oracles create decoy plateaus — prefer features agents can recover. (Task-design detail: `meta_tool_improve/META_CHARTER.md` → oracle_vs_observed.)

## Code style in cells (exploration)

Keep cells **short and linear** unless a split genuinely helps reading.

- **Try/except**: use **sparingly**. In R&D default to **let errors surface**; wrap only when you are handling a **known** contingency or need a **tight** diagnostic message. Wide `try/except Exception` that swallows context is usually wrong here.
- **Typing**: light or none in early cells (`# type: ignore` okay). Add hints only when they clarify intent, not to satisfy a linter in draft work.
- **Functions / classes**: introduce only when they **remove repetition** or clarify a **named idea**. Avoid “one function per line” refactors and abstract factories in first passes.
- **Production patterns to skip in early R&D**: layered config systems, DI containers, retry frameworks, feature flags, speculative “future-proof” abstractions—add them only when the **idea** is already validated.
- **Imports**: minimal; add dependencies when needed, don’t pre-import “everything we might use.”
- **Logs**: `print`/`display` and small assertions are fine for middle states; structured logging libraries are optional and usually later.

## Loop

1. Small change → 2. run → 3. **read outputs + stderr + any preview** → 4. only then reason or refactor.  
5. After a big metric win → **residual / cohort forensics** before declaring done.  
Repeat until the phenomenon is **understood**, not until the file is “pretty.”

## When to tighten up

When moving from **explore** to **record** (sharing, publication, handoff): add structure, naming, `run_all`, env snapshot discipline, and clearer figure names—still without turning the notebook into a microservice.
