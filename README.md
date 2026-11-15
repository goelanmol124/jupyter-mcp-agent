# jupyter-mcp-agent

**An MCP server that lets AI coding agents run and edit Jupyter notebooks on a real ipykernel and report exactly what ran.**

`jupyter-mcp-agent` is a Python [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for `.ipynb` notebooks. An AI coding agent (Claude Code, Claude Desktop, Cursor, or any other MCP client) can run one cell, run all cells, or run up to a given cell. It can also edit cells, preview variables and restart or interrupt the kernel. Each call gets back structured JSON: a `run_id`, a notebook file stamp, an environment snapshot, chunked stdout/stderr and small previews. Every run is also appended to a `manifest.jsonl` file beside the notebook, so a person can check afterwards what the agent actually ran.

> Formerly named `llm-jupyter`. The old import path (`llm_jupyter`), `python -m llm_jupyter` and the `llm-jupyter` command still work as aliases.

## Why

Research and data work is iterative: change a small piece of code, run it, look at numbers and plots, revise. Notebooks fit that loop, but agents usually either rewrite whole scripts or drive a full Jupyter server through a browser-shaped API. This server gives a notebook agent a small, predictable set of actions on a real kernel. Results are written to disk (the `.ipynb`, figures, the run manifest), not just into the chat, so they can be checked later. The design notes are in [docs/PRD.md](docs/PRD.md) and [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

## Features

- **Real ipykernel execution:** one pooled kernel per notebook path. Run modes are `cell_id`, `run_all` and `run_until_cell_id`, with `halt_on_error`.
- **Trustworthy run metadata:** a `run_id`, notebook file stamp, sources hash, Python env snapshot and kernel generation on every reply. Runs are logged append-only to `manifest.jsonl`. `explore` and `record` modes are available.
- **Notebook editing:** `cells_apply` (code-cell source edits) and `notebook_cells_patch` (insert, delete, move or set source, applied as one batch). Edits are serialised per notebook with an exclusive lock.
- **Inspection without blowing the context window:** capped `variable_preview`, chunked streams, and `execute_result`/`display_data` previews. Oversized output spills to `.llm_jupyter/runs/<run_id>/`.
- **Planning without a kernel:** `notebook_execution_plan` (structural map, companion `.apynb` sidecar checks) and `notebook_validate` (nbformat schema).
- **Sandboxed paths:** writes stay inside the notebook's folder plus any extra `--roots` you allow.
- **Host quirks handled:** `--process-cwd` covers MCP hosts that ignore `cwd`. Kernels start in the notebook's folder by default (`--kernel-cwd`).

### MCP tools

| Tool | Purpose |
|------|---------|
| `run` | Execute exactly one of `cell_id`, `run_all=true` or `run_until_cell_id`; returns `run_id` (also logged to `manifest.jsonl`) |
| `notebook_execution_plan` | Structural notebook map + companion checks, no kernel |
| `cells_apply` | Set the source of code cells by `cell_id` |
| `notebook_cells_patch` | Ordered insert / delete / move / set_source ops in one batch |
| `variable_preview` | Capped `repr` of named kernel variables |
| `kernel_restart` / `kernel_interrupt` / `kernel_status` | Kernel lifecycle (`kernel_generation` bumps on restart) |
| `clear_outputs` | Strip persisted outputs (optionally execution counts) |
| `notebook_validate` | nbformat schema check; optionally persist cell ids |
| `server_info` | No-kernel smoke test: version, tools, Python path, cwd, allowed roots |

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/goelanmol124/jupyter-mcp-agent.git
cd jupyter-mcp-agent
pip install -e .            # or: pip install -e ".[dev]" for tests
jupyter-mcp-agent serve --notebook /absolute/path/to/analysis.ipynb
```

`serve` speaks MCP over stdio, so normally your MCP client starts it for you (see below). Use an absolute notebook path unless the client's `cwd` is the notebook's folder.

### Claude Code

```bash
claude mcp add jupyter -- jupyter-mcp-agent serve --notebook /absolute/path/to/analysis.ipynb
# or, without installing the console script on PATH:
claude mcp add jupyter -- python -m jupyter_mcp_agent serve -n /absolute/path/to/analysis.ipynb
```

Or commit a project-scoped `.mcp.json`:

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "jupyter-mcp-agent",
      "args": ["serve", "--notebook", "notebooks/analysis.ipynb", "--roots", "."]
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json` (Settings > Developer > Edit Config):

```json
{
  "mcpServers": {
    "jupyter": {
      "command": "python",
      "args": ["-m", "jupyter_mcp_agent", "serve", "-n", "C:\\path\\to\\analysis.ipynb"]
    }
  }
}
```

Use the full path to the Python interpreter that has the package installed if `python` on PATH is a different one.

### Cursor and other MCP clients

Any client that can launch a stdio MCP server works; the command is `jupyter-mcp-agent serve -n <notebook>` (or `python -m jupyter_mcp_agent serve ...`). This repo ships a project-level Cursor config in [`.cursor/mcp.json`](.cursor/mcp.json), plus an agent rule ([`.cursor/rules/research-notebook-mcp-agent.mdc`](.cursor/rules/research-notebook-mcp-agent.mdc)) and a workflow skill ([`.cursor/skills/research-notebook-mcp-workflow/SKILL.md`](.cursor/skills/research-notebook-mcp-workflow/SKILL.md)). Cursor on Windows often ignores `cwd`; set `LLM_JUPYTER_PROCESS_CWD` (or `--process-cwd`) when relative paths resolve in the wrong place. Reload the client after changing MCP config.

### Try it without an MCP client

`scripts/agent_mcp_selftest.py` calls the same tool handlers in-process:

```bash
python scripts/agent_mcp_selftest.py -n examples/agent_demo_euler.ipynb --list-cell-ids
python scripts/agent_mcp_selftest.py -n examples/agent_demo_euler.ipynb run run_all=true
python scripts/agent_mcp_selftest.py notebook_validate
```

Other CLI commands:

```bash
jupyter-mcp-agent export-apynb path/to/notebook.ipynb            # (re)write the same-stem .apynb code sidecar
jupyter-mcp-agent manifest-tail path/to/notebook.ipynb --last 8   # recent manifest records for a notebook
jupyter-mcp-agent manifest-tail path/to/notebook.ipynb --run-id abcdef123456
```

## Configuration

| Option / variable | Meaning |
|----------|---------|
| `--notebook` / `LLM_JUPYTER_NOTEBOOK` | Default notebook; also anchors the write sandbox |
| `--default-mode` / `LLM_JUPYTER_MODE` | `explore` or `record` |
| `--roots` / `LLM_JUPYTER_ROOTS` | Extra allowed directories (`os.pathsep`-separated) |
| `--process-cwd` / `LLM_JUPYTER_PROCESS_CWD` | `chdir` before serving (for hosts that ignore `cwd`) |
| `--kernel-cwd` / `LLM_JUPYTER_KERNEL_CWD` | `notebook_parent` (default) or `process` |
| `--watch` | Dev only: restart when package sources change (needs `watchfiles`) |
| `LLM_NB_ART_PREFIX` | Passed into the kernel so saved figures can share a searchable prefix |

Environment variables keep the `LLM_JUPYTER_` prefix, and notebooks keep the `metadata.llm_jupyter` namespace and the `.llm_jupyter/` evidence folder, so existing notebooks and configs keep working.

**Security:** with `--notebook` set, writes are limited to that notebook's folder plus `--roots`. Without `-n`, each tool call is anchored only to the path it names, so use `-n` in real projects. The kernel runs arbitrary code as your user. Only point it at notebooks you trust.

## Architecture

```
MCP client (Claude Code / Desktop / Cursor / ...)
        | stdio (Model Context Protocol)
        v
server.py   FastMCP tool surface, JSON envelopes, path sandbox
session.py  per-notebook kernel pool (jupyter_client), exclusive locks, run orchestration
notebook.py / notebook_cells_patch.py / cells_apply_helpers.py   nbformat read/modify/write
manifest.py / stamp.py / env_snapshot.py   run_id, file stamps, manifest.jsonl, env capture
chunks.py / previews.py / stream_artifacts.py   capped stdout/stderr, previews, spill files
companion.py   .apynb code-cell sidecar export and drift checks
cli.py      `serve`, `export-apynb`, `manifest-tail`
```

Source lives in [`src/jupyter_mcp_agent/`](src/jupyter_mcp_agent); `src/llm_jupyter/` is the compatibility alias.

## Repository layout

| Path | Contents |
|------|----------|
| `src/jupyter_mcp_agent/` | The package |
| `tests/` | pytest suite (`@pytest.mark.kernel` tests start a live ipykernel) |
| `examples/` | Small demo notebooks ([examples/README.md](examples/README.md)) |
| `benchmarks/case_studies/` | MCP vs no-MCP research notebooks ([benchmarks/README.md](benchmarks/README.md)) |
| `scripts/` | Selftest harness, profiling and demo scripts |
| `docs/` | PRD and implementation notes |

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

## Status

Beta (0.3.x). The MCP tool surface is usable day to day but may still change between minor versions; see [CHANGELOG.md](CHANGELOG.md). Tested on Windows and Linux with Python 3.10 and 3.12.

## License

[MIT](LICENSE)
