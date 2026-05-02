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

- Edit cells through **MCP cell tools** or the **companion file**—avoid hand-editing raw `.ipynb` JSON as the default path.
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
