# LLM Jupyter

Open-source **Python MCP** server for **`ipykernel`** notebooks: **`run`** (single **`cell_id`**, **`run_all`**, or **`run_until_cell_id`**, with **`halt_on_error`**), **`explore`** / **`record`** modes, truthful execution JSON (stamps, env snapshot, stdout/stderr chunking, small previews), optional same-stem **`.apynb`** drift checks, and append-only **`manifest.jsonl`**.

**Release:** v0.1.1 · **Python:** ≥ 3.10 · **License:** [MIT](LICENSE)

**Cursor:** [.cursor/rules/research-notebook-mcp-agent.mdc](.cursor/rules/research-notebook-mcp-agent.mdc) · skill [.cursor/skills/research-notebook-mcp-workflow/SKILL.md](.cursor/skills/research-notebook-mcp-workflow/SKILL.md)

Default MCP wiring: **[`.cursor/mcp.json`](.cursor/mcp.json)** — **`"type": "stdio"`**, **`cwd": "${workspaceFolder}"`**, **`args`** include **`-n demos/agent_scratch.ipynb`**. **Reload Cursor** after editing MCP config.

**Manual calls** (same Python entrypoint as MCP; no IDE transport):

```bash
python scripts/agent_mcp_selftest.py run run_all=true
python scripts/agent_mcp_selftest.py notebook_validate
python -m llm_jupyter export-apynb path/to/notebook.ipynb       # mirror code cells → .apynb
python -m llm_jupyter manifest-tail path/to/notebook.ipynb --last 8
python -m llm_jupyter manifest-tail path/to/notebook.ipynb --run-id YOUR_RUN_ID
```

**Docs:** [CHANGELOG](CHANGELOG.md) · [PRD](docs/PRD.md) · [Implementation](docs/IMPLEMENTATION.md)

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

Relative **`notebook_path`** values in tools (and **`serve -n`**) resolve with `Path(...).resolve()` vs the server process **`cwd`** — keep MCP **`cwd`** aligned with your notebooks.

### CLI subcommands (`llm-jupyter` / `python -m llm_jupyter`)

| Subcommand | Purpose |
|------------|---------|
| **`serve`** | MCP stdio server (above). |
| **`export-apynb`** | Write/update **`notebook.apynb`** from code cells; persists missing `metadata.cell_id`. |
| **`manifest-tail`** | Print **`manifest.jsonl`** rows for one notebook (**`--last`**, **`--run-id`**, optional **`-m`** path); stderr hints if **`--run-id`** misses. |

**Sidecar helpers:**

```bash
python -m llm_jupyter export-apynb demos/agent_demo_beta.ipynb
python -m llm_jupyter manifest-tail demos/agent_demo_markov.ipynb --last 8
```

**Environment (optional):**

| Variable | Meaning |
|----------|---------|
| `LLM_JUPYTER_NOTEBOOK` | Default **`serve --notebook`** |
| `LLM_JUPYTER_MODE` | `explore` or `record` |
| `LLM_JUPYTER_ROOTS` | Extra allowed roots (`os.pathsep`-separated) |
| `LLM_NB_ART_PREFIX` | Figure naming hint forwarded into kernel env |

**Example `mcp.json`** (repo default — see [**.cursor/mcp.json**](.cursor/mcp.json)):

```json
{
  "mcpServers": {
    "llm-jupyter": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "llm_jupyter", "serve", "-n", "demos/agent_scratch.ipynb"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

## Tools

| Tool | Purpose |
|------|---------|
| `run` | One execution mode (`cell_id` / `run_all` / `run_until_cell_id`); **`run_id`**, chunked streams, top-level **`stream_summary`** (tail + counts), **`execution_error`** (**`ename`**, **`evalue`**) when a cell fails, previews, stamps; same-stem **`.apynb`** checked when present |
| `kernel_restart` / `kernel_interrupt` / `kernel_status` | Kernel lifecycle (**`kernel_generation`** on restart) |
| `clear_outputs` | Strip persisted outputs; optional **`clear_execution_counts`** |
| `notebook_validate` | `nbformat` structural check |
| `companion_validate` | **`.apynb`** ↔ **`.ipynb`** before kernel work |

**Security:** With **`serve -n`** set, writes are constrained to that notebook path and its parent (plus **`--roots`**). Omitting **`-n`** anchors each tool’s path separately — prefer **`-n`** in shared projects.

## Tests

```bash
pytest -q
```

Heavy cases use **`@pytest.mark.kernel`** (included by default).

**CI:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs **`pytest`** on Ubuntu for Python **3.10** and **3.12**.

## Demos

Committed notebooks under **`demos/`** (`manifest.jsonl` gitignored):

| Notebook | Idea |
|----------|------|
| [`demos/agent_mcp_lab.ipynb`](demos/agent_mcp_lab.ipynb) | Long stdout / `stream_summary` lab |
| [`demos/agent_demo_euler.ipynb`](demos/agent_demo_euler.ipynb) | Euler vs `exp(-t)` |
| [`demos/agent_demo_buffer.ipynb`](demos/agent_demo_buffer.ipynb) | Rolling mean + `.apynb` gate |
| [`demos/agent_demo_lognormal.ipynb`](demos/agent_demo_lognormal.ipynb) | Lognormal mean vs closed form |
| [`demos/agent_demo_beta.ipynb`](demos/agent_demo_beta.ipynb) | Beta–Binomial posterior |
| [`demos/agent_demo_markov.ipynb`](demos/agent_demo_markov.ipynb) | Two-state stationary distribution |
| [`demos/agent_demo_ols.ipynb`](demos/agent_demo_ols.ipynb) | OLS recovery under Gaussian noise |
| [`demos/agent_demo_softmax.ipynb`](demos/agent_demo_softmax.ipynb) | Softmax temperature vs entropy |
| [`demos/agent_demo_poisson.ipynb`](demos/agent_demo_poisson.ipynb) | Poisson rate + Wald CI |
| [`demos/agent_demo_exponential.ipynb`](demos/agent_demo_exponential.ipynb) | Exponential mean vs **1/λ** |

```bash
python scripts/agent_mcp_selftest.py -n demos/agent_demo_euler.ipynb run run_all=true
python scripts/agent_mcp_selftest.py -n demos/agent_demo_euler.ipynb --list-cell-ids
```

See also standalone scripts [`scripts/demo_research_sin_inv.py`](scripts/demo_research_sin_inv.py) and [`scripts/demo_polyfit_noise.py`](scripts/demo_polyfit_noise.py).

## Releasing

1. Bump **`version`** in [`pyproject.toml`](pyproject.toml) and [`src/llm_jupyter/__init__.py`](src/llm_jupyter/__init__.py); note changes in [`CHANGELOG.md`](CHANGELOG.md).
2. `pip install ".[release]" && python -m build`
3. `twine check dist/* && twine upload dist/*` (configure **twine** credentials for your index).

## Scope (v1)

**Shipped:** JSON **`.apynb`** companions (`companion_version: 1`), **`companion_validate`**, **`export-apynb`**, **`manifest-tail`**, **`manifest.jsonl`**.

**Not shipped:** bulk **`cells_apply`**, **`variable_preview`**. See [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).
