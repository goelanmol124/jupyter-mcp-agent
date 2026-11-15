# Offline regression benchmark (Demos)

You are improving **test-set RMSE** on a fixed synthetic regression task. All work stays under `benchmarks/case_studies/rnd_benchmark_2026/`.

## Data (do not change)

- Load arrays only from **`benchmarks/case_studies/rnd_benchmark_2026/data.npz`** using `allow_pickle=False`:
  - `X_train`, `X_test`, `y_train`, `y_test`
- **Do not** resplit, shuffle differently, or leak test labels into training decisions.
- scipy / sklearn / numpy / pandas / matplotlib allowed.

## Goal

Build a regression model (or ensemble) that minimizes **RMSE on `y_test`**:

`test_rmse = sqrt(mean((y_pred - y_test)**2))`

## Deliverable

In your notebook, end with a cell that **prints exactly**:

`FINAL_TEST_RMSE: <number>`

(use a float rounded to at least 4 decimal places). Optionally save `y_pred.npy` beside the notebook.

## Notes

- EDA on **train only** (or train+features without peeking at test **labels** in a way that fits on test—honor the spirit: no fitting on `y_test`).
- Track what you tried—plots and intermediate metrics help you debug.
