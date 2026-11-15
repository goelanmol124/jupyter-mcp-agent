# Benchmarks and case studies

Exploratory "with MCP vs without MCP" research notebooks used while developing
`jupyter-mcp-agent`. They are kept for reference and are **not** part of the test suite.

`case_studies/` holds the committed material:

| Path | What |
|------|------|
| `rnd_benchmark_2026/` | Fixed synthetic regression task (`TASK.md`, `data.npz`) with an MCP track and a terminal track notebook |
| `ab_rnd_baseline/`, `ab_rnd_changepoint.ipynb` | Changepoint detection (grid SSE vs CUSUM) baseline and agent run |
| `benchmark_robust_curve/`, `benchmark_peakfit/` | Robust curve / peak fitting tasks |
| `comparison_latent/` | Latent-class classification, baseline vs MCP notebook |
| `longtest_*` | Biexponential fit, long MCP session vs scripted run |
| `rd_hpfilter_*` | Hodrick-Prescott cycle recovery, MCP vs no-MCP |
| `rnd_mcp_confounded.ipynb` | Confounded-regression experiment |

Most notebooks use repo-root-relative paths (for example
`benchmarks/case_studies/rnd_benchmark_2026/data.npz`); start the kernel from the repo root
(`serve --kernel-cwd process`) when re-running them. Saved outputs are historical and may
mention the old `demos/` folder.
