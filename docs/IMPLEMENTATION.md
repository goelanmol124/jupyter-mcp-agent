# Implementation



Working notes for implementation — not frozen requirements.

### Snapshot — strengths already embodied in code

Aligned with [PRD vision](PRD.md#why-this-exists-vision): inspectable behaviour (streams, previews, fingerprints), artefacts humans can open, and honest handling of failures and staleness—not only “final plots look fine”:

- **Notebook-keyed kernel pool:** one MCP process → **OrderedDict** of handles by resolved **`.ipynb`** path; **LRU eviction** capped by **`LLM_JUPYTER_MAX_NOTEBOOK_KERNELS`**.
- **Per-notebook serialization:** **`notebook_exclusive`** lock + **`LLM_JUPYTER_NOTEBOOK_LOCK_TIMEOUT_SEC`** (timed queue, infinite queue, or non-blocking busy) so parallel MCP clients do not corrupt one file.
- **Agent honesty:** **`process_session_id`** and **`server_info.tool_names`**, **`stable_tool_error`** field order, **`assistant_quick`** + verbosity compaction, **`halt_on_error=false`** still surfacing **`status:error`** when cells fail.
- **Stale narrative:** **`outputs_might_be_stale` / `stale_notes`** tied to partial runs and **`kernel_generation`** (including “full notebook at this generation” bookkeeping).
- **Bounded evidence:** stream suffix / tail semantics, optional spill to **`.llm_jupyter/runs/{run_id}/`**, **`run_stream_read`** for paged UTF-8 bytes.
- **`record` fingerprints:** whitelist-based env snapshot hashing + optional short TTL reuse ( **`LLM_JUPYTER_RECORD_ENV_SNAPSHOT_CACHE_SEC`** ); policy version bumps invalidate cache semantics.
- **Disk vs RAM coaching:** **`NOTEBOOK_EDIT_PERSISTED_VS_KERNEL_HINT`** after structural saves; companion mirror stale hints after patches.

Probe-style **excluding** cells from **`run_all` / `run_until`** (metadata flag) remains a **documentation / product backlog** item—the current selectors still include every **code** cell.



### Companion files and MCP descriptions



Optional **companion file** beside `.ipynb` carries cell ids + source. After humans touch `.ipynb`, regenerate or compare the companion copy before trusting execution.



Each MCP tool should carry a **short description** — long blobs belong in README or Cursor skills.



### Stack



`ipykernel`, `jupyter_client`, `nbformat`, MCP over **stdio**. Optional Pillow (or similar) for smaller image previews in JSON.



### Stable `cell_id` and automated tests



Store a **`cell_id`** (uuid / ulid) in cell metadata. Tools address **ids before indices**.



Add tests early for companion-file mismatches and any optional **`variable_preview`** code path—even if off by default—because they regress without noise.



Optionally snapshot-test MCP tool definitions so summaries stay brief.



### Variable previews and “under the hood” behaviour



Notebooks and PNGs show **endpoints**, not always the **path**. For R&D you care about **middle states and behaviour**: what the cell **actually produced** (text streams, return value, intermediate objects), not only whether a chart saved. Wrong branch, silent coercion, order-dependent mutation—all of that shows up in **how** the run unfolded, not only in `shape`.



Expose optional **`variable_preview`** (or similar): **names the user or assistant chooses**, plus safe defaults—**capped values** (truncated `repr`, small samples), not only metadata. Pair with **rich execution records** (stdout/stderr chunks, structured previews, paths to heavier dumps on disk) so “under the hood” stays **inspectable** without pasting megabytes into chat. Default off until behaviour is stable; caps are mandatory.



### Authoring priority



Implement **cell mutation tools before** introducing a companion file; add the companion file only if plain tools feel too awkward.



Structural checks **without running code** (`notebook_validate` flag) catch bad merges before hitting the kernel.



### Modes (`explore` / `record`)



Expose `run(mode="explore"|"record")` or a sibling config knob.



**`record`:** fuller **python_env_snapshot**, stronger **notebook_file_stamp**, plot-prefix hints, optional full notebook clones.



**`explore`:** skip heavy clones by default yet still stamps files and forwards stderr faithfully.



Implement in the shortest code path that behaves honestly.



### Example JSON after execution



Exact fields will move; approximate shape:



```json

{

  "mode": "explore",

  "kernel_generation": 4,

  "cells_executed": ["fe8…", "92a…"],

  "status": "ok | error | interrupted",

  "restart_since_previous_tool_call": false,

  "outputs_might_be_stale": true,

  "stale_notes": ["kernel restarted since full rerun"],

  "notebook_path": ".../analysis.ipynb",

  "notebook_file_stamp": {"mtime_ns": "...", "bytes": 18234, "sha256_prefix": "a3f9…"},

  "python_env_snapshot": {

    "python_version": "3.12.x",

    "packages_summary_or_hash": "…",

    "git_commit": null

  },

  "kernel_runtime_ms": 8400,

  "suggested_figure_prefix": "20260202_gen4_fe8",

  "output_files": ["20260202_gen4_fe8_loss.png"],

  "previews": {"tables": [], "images": []},

  "stdout_chunks": {},

  "stderr_chunks": {},

  "variable_preview_optional": { "examples": ["truncated repr / small value samples for requested names"] }

}

```



- **notebook_file_stamp:** catches disk edits concurrent with assistant planning.  

- **python_env_snapshot:** answers “why does my result differ?”—fill aggressively in **`record`**, lighter in **`explore`**.

- **suggested_figure_prefix:** lowers naming friction; models still name plots sensibly.

- **variable_preview_optional:** when requested—**values and behaviour**, not only dtypes (capped); see Variable previews section.


Keep **`outputs_might_be_stale`** truthful through any UI shortening; **never drop stderr silently.**



### `run` surface



Minimal behaviour set:



1. Run **one** cell by **`cell_id`**.  

2. Run **`all`** code cells downward.  

3. Run **`until`** a **`cell_id`**, inclusive from the notebook start.  



Support **halt on first error.** Layer **`explore`** / **`record`** on top via mode flag.



### Validate before execute



Parse with **`nbformat`**, validate schema, optionally diff companion file — only when invoked or when safety flags demand it — before wasting kernel time.



### Preview parameters



Concrete knob names to try: **`preview_rows`**, **`max_image_side`**.



Saved output files on disk stay full quality for humans; previews in JSON stay small.



### Long stdout / stderr



Use the **same chunking pattern** for both streams. Deferred: true streaming transports until proved necessary.



### Keep the tool count small



Aim for: **`cells_apply`**, **`run`**, one **`kernel`** group (`restart`, `interrupt`, optionally `status`), optional **`clear_outputs`**, optional **`notebook_validate`**.



Automatically appending to **`manifest.jsonl`** after important runs avoids inventing separate “history writer” tools the model must remember.



Linting stays a **developer-only** flag—not part of baseline UX.



### Run log (`manifest.jsonl`)



Per line: timestamp, **notebook_file_stamp**, **python_env_snapshot** (depth mode-dependent), **kernel_generation**, **cells_executed**, status, optional hash over sources only for quick deltas, optional stderr digest.



Prefer a skinny log plus rare full clones when disk budget allows.



### Interrupts and stale output



Wire interrupt cleanly; restarting bumps **`kernel_generation`**. Treat persisted outputs as **untrusted until a matching rerun**, unless cleared explicitly.



User-facing structural validation errors stay **short** (one sentence naming the affected cell id where possible). Dense tracebacks hide behind **`debug`**. Syntax slips surface mainly through kernel output.



### Build order (single checklist)



1. Stub MCP wiring that returns plausible JSON (+ mode placeholder).  

2. Run **single cell** via kernel → write outputs → return JSON.  

3. **`all`** + **`until`**, **`halt_on_error`**, stale-output flags, symmetrical stdout/stderr chunk fields.  

4. **`notebook_file_stamp`** + **`python_env_snapshot`**.  

5. Chunk handling experiments for stdout and stderr.  

6. **`manifest.jsonl`** wired for **`explore`** versus **`record`**.  

7. Companion file round-trip plus optional **`variable_preview`**, guarded by tests.


