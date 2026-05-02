# PRD: Research Notebook MCP

## Why this exists (vision)

Notebook-style work fits **research**: change a small piece of code, run it, inspect numbers and plots, revise. That loop is awkward when the only path is “rewrite a big script” or “drive a full Jupyter server stack.” Meanwhile, **LLM assistants** shine when the environment gives them **clear actions** (run this cell, rerun from the top, surface stderr, show a small preview of a table or figure) and **truth on disk** humans can open without parsing chat.

This project is building a **thin MCP server**: it runs a real **Python kernel**, updates **`.ipynb`** and output files, returns **predictable JSON**, and keeps **history** you can search—so **R&D workflows stay easy for both you and the model**, not only for shipping application code.

### What’s under the hood (behaviour, not only structure)

R&D debugging isn’t only **`shape` / dtypes**—it’s **how the run actually behaved**: what was **returned**, what **side effects** landed in memory, what **middle states** existed between “start cell” and “final plot.” Final outputs can look plausible while the trajectory was wrong (silent coercion, wrong branch, order-dependent state, a mutated object you forgot).

You need ways to see **that story** without re-running blind: **captured stdout/stderr**, **last result / display** for a cell where that’s meaningful, **snapshots of chosen names** after a run (values, not just types), and room for **optional breadcrumbs** (logging hooks, stepping, or “dump these locals after cell X”)—always **capped** so chat context stays usable.

Optional **`variable_preview`** and the **execution JSON** (streams, previews, paths) exist for this: make **behaviour and intermediate reality** inspectable for you and for the assistant, not only the polished surface of a figure.

## What we’re building

A **small, open-source** Python MCP server that uses **`ipykernel`** to execute notebook cells and save **`.ipynb`** files so editors keep working as usual—with outputs and image paths on disk so people can inspect **real numbers and plots**, not only short summaries.

The editor talks to the language model; **this server only runs Python**. Each tool call related to execution returns plain **JSON** (what ran, status, paths, small previews). The editor may summarise that text or pipe it through unchanged.

Prefer **small default previews**, plus parameters to fetch **more rows or larger images** when needed.

## Plain-language terms

- **Companion file:** optional **same-stem JSON `.apynb`** beside the notebook (`companion_version: 1`; code cells only, with `cell_id` + `source`). **Implemented** — regenerate via **`llm-jupyter export-apynb`** after UI edits; **`companion_validate`** / **`run`** reject drift.

- **MCP tool text:** keep **tool descriptions short**. Long blocks in MCP definitions confuse models; spell out workflows in README or Cursor rules instead.

## Who edits the notebook

**By default**, agents edit through **validated MCP tools**. They may instead use the **companion file** pattern described above instead of patching raw notebook JSON.

People keep using the normal notebook UI on `.ipynb`. If notebook structure is invalid after an edit, **validation should fail visibly**, not silently write bad files.

## Modes: quick try vs save for keeps

| Mode | Intent |
|------|--------|
| **`explore` (quick try)** | Faster loops, lighter logging. Still store notebook **file stamps** and stream stdout/stderr fairly. Heavy optional notebook copies stay off unless you turn them on. |
| **`record` (save for keeps)** | Richer logs: Python and key packages, fuller run-log lines, **plot naming hints every run** (`suggested_figure_prefix` or an env var kernels can read), friendly push toward **`run_all`** before sharing figures. |

Toggle via **`run(mode=…)`** or server configuration; first cut can stay blunt and simple.

## What every execution reply must carry

The model does not hold kernel RAM between chats. Routine fields:

- **`kernel_generation`:** integer that goes **up whenever the kernel restarts** (the “restart counter”).  
- **Which cells ran** (by `cell_id`).  
- **`outputs_might_be_stale` (or similar):** loud when graphs on disk may disagree with RAM—common after restart or interrupt.

Stale plots mislead more than sloppy code once. Same warnings should survive into short summaries the UI shows—not only buried JSON keys.

## Tables, plots, stderr

Summaries + small samples by default; parameters widen scope.

Treat **stderr like stdout**: same truncation and chunk rules. Warnings are part of reading the experiment.

## Plot filenames

Avoid `plot1.png`. Prefer time + **`kernel_generation`** + **`cell_id`** + short label—or call **`suggested_figure_prefix`** / **`LLM_NB_ART_PREFIX`** from the server so logs stay searchable without extra tooling.

## Run log

Append one line per meaningful run to **`manifest.jsonl`** (and optionally duplicate whole notebooks occasionally), keyed using **notebook file stamps**—more detail under **`record`**.

## Run behaviours

Expose clearly in MCP so the assistant does not improvise semantics:

| Behaviour | Meaning |
|-----------|---------|
| **`run_all`** | All code cells **top → bottom**. |
| **`run_until`** | From the top **through** a target **`cell_id`**, inclusive. Prefer ids over naked indices. |
| **`halt_on_error`** | Stop at first failing cell versus continue—match familiar notebook UX. |

## Scope

**Out of scope for v1 design:** one MCP instance fanning multiple notebooks inside **the same chat** at once. Separate chats pointing at different notebooks with separate configs **is fine**.

## Safety and experiments

Writes only under configured roots: notebook folder, output folder, optional companion file alongside them.

Server code **must not call** hosted LLMs (OpenAI, Google, etc.)—that stays in the editor.

**Tests:** cover companion-file drift and optional **variable previews** early, even when those features default **off**.

Stopping the MCP process destroys in-memory kernel state; rerun cells when disk and interpreter must agree.
