# LLM Jupyter

Open-source **Python MCP** server for **`ipykernel`** notebooks: **`run`** (single cell, **`run_all`**, or **`run_until`**, with **`halt_on_error`**), **`explore`** vs **`record`** modes, execution JSON (notebook file stamp, Python env snapshot, stdout/stderr chunked the same way, small previews), append-only **`manifest.jsonl`**.

**Cursor:** always-on rule [.cursor/rules/research-notebook-mcp-agent.mdc](.cursor/rules/research-notebook-mcp-agent.mdc); workflow skill [.cursor/skills/research-notebook-mcp-workflow/SKILL.md](.cursor/skills/research-notebook-mcp-workflow/SKILL.md).

Project-level MCP registration: **[`.cursor/mcp.json`](.cursor/mcp.json)** (targets [`demos/agent_scratch.ipynb`](demos/agent_scratch.ipynb); **`cwd`**: `${workspaceFolder}` so **`args -n demos/…`** resolves from the repo root). **Reload Cursor** after changing MCP config so the `llm-jupyter` server appears; before reload, the assistant only has other MCP servers (for example the browser tools in this environment).

**Manual same-as-MCP calls** (stdio handlers, no IDE bridge):

```bash
python scripts/agent_mcp_selftest.py run run_all=true
python scripts/agent_mcp_selftest.py notebook_validate
python -m llm_jupyter export-apynb path/to/notebook.ipynb   # (re)write same-stem `.apynb`
python -m llm_jupyter manifest-tail path/to/notebook.ipynb   # last manifest records for that notebook
python -m llm_jupyter manifest-tail path/to/notebook.ipynb --run-id abcdef123456   # one cited run_id (stderr hint if no match)
```

**Docs:** [PRD](docs/PRD.md) · [Implementation](docs/IMPLEMENTATION.md) · **License:** [MIT](LICENSE)

## Install

```bash
pip install -e ".[dev]"
```

## Run (stdio MCP)

```bash
python -m llm_jupyter serve --notebook /absolute/path/to/analysis.ipynb --default-mode explore
# or
llm-jupyter serve -n /absolute/path/to/analysis.ipynb
```

**`.apynb` sidecar refresh** (mirror code cells next to validation / `run`):

```bash
python -m llm_jupyter export-apynb demos/agent_demo_beta.ipynb
# or: llm-jupyter export-apynb path/to/analysis.ipynb -o path/to/other.apynb
python -m llm_jupyter manifest-tail demos/agent_demo_markov.ipynb --last 8
python -m llm_jupyter manifest-tail demos/agent_demo_ols.ipynb --run-id YOUR_RUN_ID
```

**Environment (optional):**

| Variable | Meaning |
|----------|---------|
| `LLM_JUPYTER_NOTEBOOK` | Default `--notebook` |
| `LLM_JUPYTER_MODE` | `explore` or `record` |
| `LLM_JUPYTER_ROOTS` | Extra allowed directories (`os.pathsep`-separated); default sandbox is the notebook’s parent only when `--notebook` is set |
| `LLM_NB_ART_PREFIX` | Passed into the kernel environment so saved figures can reuse a searchable prefix |

**Cursor MCP config example** (`mcp.json`):

```json
{
  "mcpServers": {
    "llm-jupyter": {
      "command": "python",
      "args": ["-m", "llm_jupyter", "serve", "-n", "C:\\path\\to\\notebook.ipynb"],
      "cwd": "C:\\path\\to\\project"
    }
  }
}
```

Use an **absolute** path for `-n` on Windows unless `cwd` is the notebook folder.

## Tools

| Tool | Purpose |
|------|---------|
| `run` | Execute **exactly one** of `cell_id`, `run_all=true`, or `run_until_cell_id`; response includes **`run_id`** (also in `manifest.jsonl`) |
| `kernel_restart` / `kernel_interrupt` / `kernel_status` | Kernel lifecycle (`kernel_generation` bumps on restart) |
| `clear_outputs` | Clear persisted outputs (optional `clear_execution_counts`) |
| `notebook_validate` | `nbformat` schema check without running |

**Security:** With `--notebook` set, writes are limited to that notebook path and its parent (plus `--roots`). Starting without `-n` only anchors each tool call’s path to itself—use `-n` in real projects.

## Tests

```bash
pytest -q
```

Kernel-heavy cases are marked `@pytest.mark.kernel` (included by default).

Committed demos under **`demos/`** (with `manifest.jsonl` gitignored there):

| Notebook | Idea |
|----------|------|
| [`demos/agent_scratch.ipynb`](demos/agent_scratch.ipynb) | Monte Carlo π |
| [`demos/agent_demo_euler.ipynb`](demos/agent_demo_euler.ipynb) | Euler vs `exp(-t)` |
| [`demos/agent_demo_buffer.ipynb`](demos/agent_demo_buffer.ipynb) | Rolling mean (`*.apynb` demo) |
| [`demos/agent_demo_lognormal.ipynb`](demos/agent_demo_lognormal.ipynb) | Lognormal mean vs closed form |
| [`demos/agent_demo_beta.ipynb`](demos/agent_demo_beta.ipynb) | Beta–Binomial posterior |
| [`demos/agent_demo_markov.ipynb`](demos/agent_demo_markov.ipynb) | Two-state stationary distribution |
| [`demos/agent_demo_ols.ipynb`](demos/agent_demo_ols.ipynb) | OLS recovery under Gaussian noise |
| [`demos/agent_demo_softmax.ipynb`](demos/agent_demo_softmax.ipynb) | Softmax temperature vs entropy |
| [`demos/agent_demo_poisson.ipynb`](demos/agent_demo_poisson.ipynb) | Poisson rate + Wald CI |

**MCP-style manual calls** (same handlers as `python -m llm_jupyter serve`):

```bash
python scripts/agent_mcp_selftest.py -n demos/agent_demo_euler.ipynb run run_all=true
python scripts/agent_mcp_selftest.py -n demos/agent_demo_euler.ipynb --list-cell-ids
```

Ephemeral temp-dir scripts (still useful for CI-free smoke):

```bash
python scripts/demo_research_sin_inv.py
python scripts/demo_polyfit_noise.py
```

## Scope notes (v1)

Companion YAML/JSON cell mirror, `cells_apply`, and `variable_preview` are **not** implemented yet; see [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).
