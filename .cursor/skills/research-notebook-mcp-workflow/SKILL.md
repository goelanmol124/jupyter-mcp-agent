---
name: research-notebook-mcp-workflow
description: >-
  Operational workflow for llm-jupyter MCP: outline → validate → run,
  notebook_cells_patch / cells_apply / companion / export-apynb,
  variable_preview semantics, rich in-notebook comments,
  latency when JSON misbehaves. Use for notebook+R&D with this MCP,
  or MCP server work—keep prose tool blobs in README/PRD instead.
disable-model-invocation: true
---

# Research Notebook MCP — agent workflow

## Current MCP surface (repo `llm_jupyter`); match your install

- **Execution**: **`run`**, **`dry_run`** (same selectors as **`run`**—lists targets without starting the kernel—use before expensive **`run_all`** when ids are uncertain).
- **Layout / ids**: **`notebook_outline`**—call before **`run(..., cell_id=…)`** when ids unknown. **`persist_cell_ids=true`** assigns missing **`metadata.cell_id`** on **code / markdown / raw** cells (**`max_*`** parameters in [**`server.py`](../../../src/llm_jupyter/server.py)**).

- **Introspection**: **`variable_preview`**—capped **`repr`** snapshots for plain **identifiers** in live **`globals()`** (no **`df.col`** dotted paths; sanitize invalid names silently; warm the kernel via **`run`** where needed).

- **Edits**: **`notebook_cells_patch`**—single batch **`insert`** / **`delete`** / **`move`** / **`set_source`** (each **`insert`** or **`move`** uses exactly one anchor: **`after_cell_id`**, **`before_cell_id`**, or **`at_index`**). Response includes **`cells_summary`**; structural edits can leave **`outputs_might_be_stale`**—rerun/`kernel_restart` when needed. **`cells_apply`**—code-only **`set_source`** shorthand; duplicate **`cell_id`** last‑wins.
- **Validation**: **`notebook_validate`**, **`companion_validate`**. Same‑stem **`.apynb`** via **`export-apynb`**; **`export-apynb --format yaml`** for YAML companions.

- **`run`**: **exactly one** of **`cell_id`**, **`run_all=true`**, **`run_until_cell_id`**. Validates against `.apynb` when present (**`companion_strict=true`** requires match).

- **Kernel / notebook hygiene**: **`kernel_restart`** / **`kernel_interrupt`** / **`kernel_status`**, **`clear_outputs`**, **`server_info`**.

**Truth for tools:** **`server_info`** **`tool_names`** outweighs prose if your client differs from this tree.

Project MCP wiring: **[`.cursor/mcp.json`](../../../.cursor/mcp.json)** (**reload Cursor** after edits). Fallback: `python scripts/agent_mcp_selftest.py …`.

**Paths:** **`notebook_path`** resolves versus the server **`cwd`** (use **`"${workspaceFolder}"`** in **`mcp.json`**). Omit **`notebook_path`** when **`serve`** was started with **`-n`**. Fresh **`.apynb`**: run **`export-apynb` → `companion_validate` → `run`** so the filesystem settles before **`companion_strict`** rejects with **`"skipped"`**.

Every **`run`** returns **`run_id`** and appends to **`manifest.jsonl`** beside the notebook—cite **`run_id`** to anchor one execute cross‑chat. **`python -m llm_jupyter manifest-tail …`**; **`--run-id …`** filters rows.

## Mindset

Same intent as `.cursor/rules/research-notebook-mcp-agent.mdc`: prioritize **seeing** artefacts (streams, plots, **`stderr`**) over asserting correctness without them.

## Data: look with your eyes

- **Open artefacts**: rows, disk tables/plots (thumbnails + originals), **`stderr`**. Metrics/summaries are hints.
- Trace **movement** after transforms: shapes, dtypes, heads, imbalance, gaps, intermediate series—not only finals.
- Deeper inspection than **`variable_preview`** (**`globals()`** identifiers only)—**`print`**, **`display`**, **`run`** streams, **`notebook_outline`**, filesystem.

## Debugging

- Trust **kernel truth** over stale notebook output: respect **`kernel_generation`**, **`outputs_might_be_stale`**, rerun after **restart** when diagnosing.
- Narrow the loop: one cell or assumption; **`run_until`** / targeted **`cell_id`**; compare streams/previews.
- Prefer **visible failure** in the notebook (clear traceback, prints) over silent catches while exploring.

## MCP usage habits

- Notebook UI edits: **`export-apynb`**; **`companion_validate`** when **`companion_strict`** applies; then **`run`**.

- Loop: **`notebook_outline`** → **`notebook_cells_patch`** (or **`cells_apply`** / UI) → **`export-apynb`** → **`companion_validate`** (strict) → **`run`**.

- **`run_all`** / **`run_until`** for chain reproducibility; **`explore`** vs **`record`** when sharing or archiving.

- Name plot files using **server hints** (`suggested_figure_prefix` / `LLM_NB_ART_PREFIX`) so runs stay traceable in logs.

## Latency (`phase_timings_ms`) vs “big JSON”

_Use when MCP responses truncate, timeouts, or OOM—you are debugging serialization or oversized outputs._

- Runs return **`assistant_quick`** early—read before **`stdout_chunks`**.

- **`post_execute_through_chunks_ms`** is **before** MCP JSON encode: includes notebook save (**`notebook_save_after_execute_ms`** dominates if embedded outputs swell), previews, chunked stream joins.

- **`payload_assembly_ms`** includes **`record`** **`python_env_snapshot`** overhead (unless TTL cache)—not the Jupyter execute loop proper.

- **`kernel_runtime_ms`** ends when the **`run`** dict is built (**before** manifest append and MCP host JSON encode).

- Huge **`run_all`**: unrelated clients may time out idle stdio; this server doesn’t stream partial payloads. Prefer **`run_until`**, narrower prints, **`clear_outputs`** to shrink **`ipynb`** saves; **`compact_assistant_quick`**, **`LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC`** for **`record`**. Compare **`server_info`** **`process_pid`** across dropouts versus a restarted server.

## Comments and narrative (R&D notebooks)

Patchy loops are normal—**the notebook carries the thread** alongside **`manifest`** / chat **`run_id`** refs.

- **Use as much commentary as helps**: Markdown paragraphs for hypotheses and chapter breaks; **`#`** under code for rationale, “last run showed…”, **`kernel_generation`** if it matters.
- Capture **why** you changed course (plots, **`stderr`**, wrong intuitions)—future you and collaborators do not infer this from terse code alone.
- “Sparse production code” norms **do not** apply to documentation here; verbosity in comments is acceptable when it preserves context.

## Code style in cells (exploration)

Keep cells **short and linear** in *structure*, not meaning “avoid comments”—see §Comments and narrative.

- **Try/except**: **sparingly**. In R&D default to **letting errors surface**; wrap only for a **known** contingency or a **tight** diagnostic message. Wide `try/except Exception` that hides context hurts here.

- **Typing**: light or none (`# type: ignore` ok). Types clarify intent—not linter appeasement in drafts.

- **Functions / classes**: only when they **remove duplication** or name a coherent idea—not refactors chasing style.

- **Skip early**: layered configs, DI, retry frameworks, feature flags until the hypothesis is validated.

- **Imports**: minimal. **Logs**: **`print`** / **`display`** / small assertions beat heavy logging libs in exploratory cells.

## Loop

1. Small change → 2. **`run`** → 3. **read stdout/stderr/previews/disks** → 4. revise. Repeat until the phenomenon is understood—not until the notebook is “pretty.”

After a revealing **`run`**, extend **comments/narrative** so the trajectory survives without chat context (§Comments and narrative).

## When to tighten up

Moving **explore** → **record** (sharing, publication, handoff): structure, **`run_all`**, clearer figure names/env snapshot posture—still not a microservice.
