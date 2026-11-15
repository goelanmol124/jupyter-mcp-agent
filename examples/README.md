# Examples

Small, self-contained notebooks for trying `jupyter-mcp-agent` with an AI coding agent
(or with `scripts/agent_mcp_selftest.py`, which calls the same MCP handlers without an IDE).
`.apynb` files are the code-cell sidecars written by `jupyter-mcp-agent export-apynb`.

| Notebook | Idea |
|----------|------|
| [`agent_scratch.ipynb`](agent_scratch.ipynb) | Monte Carlo pi (default selftest notebook) |
| [`agent_demo_euler.ipynb`](agent_demo_euler.ipynb) | Euler vs `exp(-t)` |
| [`agent_demo_buffer.ipynb`](agent_demo_buffer.ipynb) | Rolling mean (`.apynb` demo) |
| [`agent_demo_lognormal.ipynb`](agent_demo_lognormal.ipynb) | Lognormal mean vs closed form |
| [`agent_demo_beta.ipynb`](agent_demo_beta.ipynb) | Beta-Binomial posterior |
| [`agent_demo_markov.ipynb`](agent_demo_markov.ipynb) | Two-state stationary distribution |
| [`agent_demo_ols.ipynb`](agent_demo_ols.ipynb) | OLS recovery under Gaussian noise |
| [`agent_demo_softmax.ipynb`](agent_demo_softmax.ipynb) | Softmax temperature vs entropy |
| [`agent_demo_poisson.ipynb`](agent_demo_poisson.ipynb) | Poisson rate + Wald CI |
| [`agent_demo_exponential.ipynb`](agent_demo_exponential.ipynb) | Exponential mean vs 1/lambda |
| [`agent_mcp_lab.ipynb`](agent_mcp_lab.ipynb) | Long stdout, exercises chunked stream summaries |
| [`changepoint_probe.ipynb`](changepoint_probe.ipynb) | Mean-shift changepoint toy |
| [`synth_noisy_clusters.ipynb`](synth_noisy_clusters.ipynb) | Label-noise mixture, iterated relabel/refit |

```bash
python scripts/agent_mcp_selftest.py -n examples/agent_demo_euler.ipynb --list-cell-ids
python scripts/agent_mcp_selftest.py -n examples/agent_demo_euler.ipynb run run_all=true
```

`manifest.jsonl` files written next to these notebooks are gitignored.
