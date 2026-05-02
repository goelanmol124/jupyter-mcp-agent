---
name: research-notebook-mcp-workflow
description: >-
  How to work with the Research Notebook MCP and notebook R&D in general:
  inspect real data and data flow, debug with kernel truth, keep code small
  and exploratory—not production style. Use when this MCP is configured or
  when doing similar notebook research with an LLM.
disable-model-invocation: true
---

# Research Notebook MCP — agent workflow

## Current MCP server (repo `llm_jupyter`): what exists today

- Tools are **`run`**, **`notebook_outline`**, **`kernel_*`**, **`clear_outputs`**, **`notebook_validate`**, **`companion_validate`**. Optional **`.apynb`** sidecar (same stem as the `.ipynb`): when that file exists, **`run`** cross-checks code-cell sources and `metadata.cell_id` before executing; use **`companion_strict=true`** to require a sidecar. **`variable_preview`** and **`cells_apply`** are **design targets**—do not assume they exist unless your install added them.
- With the repo’s **project-level MCP file** `.cursor/mcp.json` (see README): **reload Cursor** so `llm-jupyter` registers; otherwise run `python scripts/agent_mcp_selftest.py …` from the repo root to hit the same code path.
- **Path semantics:** **`notebook_path`** resolves vs the server **`cwd`**; omit for the **`serve -n`** default when calling **`run`** or **`kernel_*`**. For sidecars: **`export-apynb` → `companion_validate` → `run`**.
- **Multi-notebook:** Cursor shares one MCP process across chats; **`notebook_path`** selects a **distinct ipykernel**. Pass **`notebook_path`** on **`kernel_restart`**, **`kernel_interrupt`**, and **`kernel_status`** for any notebook that is not the **`serve -n`** default.
- **`run`** requires **exactly one** intent: **`cell_id`**, **`run_all=true`**, or **`run_until_cell_id`**. Passing more than one is an error (avoids silent “`cell_id` wins” bugs).
- Every execution returns **`run_id`** and appends it to **`manifest.jsonl`** next to the notebook—**cite `run_id` in chat** when you want durable cross-turn memory of a specific execute. **Shell:** `python -m llm_jupyter manifest-tail path/to/analysis.ipynb` (recent rows) or add **`--run-id …`** after you cite one run in chat (same notebook filter still applies). If `--run-id` matches nothing, the CLI prints a short **stderr** explanation (stdout stays JSON for piping).

## Mindset: R&D, not shipping

- Optimize for **fast understanding**, not “enterprise” structure. One screen of clear code beats five files of ceremony.
- Prefer **seeing** what happened over **asserting** correctness on paper.

## Data: look with your eyes

- **Open real artefacts**: sample rows, skim saved tables on disk, **view plots** (thumbnails + originals), read **stderr** as carefully as stdout. Summaries and metrics are hints, not substitutes.
- Trace **how data moves**: after non-trivial transforms, surface **intermediate structure** (shapes, dtypes, key columns, class balance, NaNs, heads of intermediate frames, a line plot of a middle series). The story is often in the **path**, not only the final metric.
- Use **`variable_preview`** (or equivalent MCP tool) for **named values and behaviour**—not only types—when something “looks off.” Request bounded previews; escalate to full paths when needed.

## Debugging

- Trust **kernel truth** over stale notebook output: respect **`kernel_generation`**, **`outputs_might_be_stale`**, rerun after **restart** when diagnosing.
- Narrow the loop: change **one cell or one assumption**, re-run (`run_until` / targeted cell), compare before/after streams and previews.
- Prefer **visible failure** in the notebook (clear traceback, prints) over silent catches while exploring.

## MCP usage habits

- Prefer editing in Cursor’s notebook UI; optional **`.apynb`** JSON (`companion_version`, `cells` with `cell_id` + `source` per **code cell in order**) is for agents and scripts—keep it in sync with the notebook or validation fails before **`run`**. **`companion_validate`** checks drift without executing. Refresh the sidecar after UI-only edits: **`python -m llm_jupyter export-apynb path/to/analysis.ipynb`**.
- Prefer **`run_all`** or **`run_until`** when reproducibility of the chain matters; note **`explore`** vs **`record`** when conclusions or shared figures matter.
- Name plot files using **server hints** (`suggested_figure_prefix` / `LLM_NB_ART_PREFIX`) so runs stay traceable in logs.

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
Repeat until the phenomenon is **understood**, not until the file is “pretty.”

## When to tighten up

When moving from **explore** to **record** (sharing, publication, handoff): add structure, naming, `run_all`, env snapshot discipline, and clearer figure names—still without turning the notebook into a microservice.
