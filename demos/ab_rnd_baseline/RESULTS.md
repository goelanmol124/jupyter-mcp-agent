# Changepoint benchmark — summary

Synthetic Gaussian series length **n = 400**, **σ = 0.4**, means **μ− = 0**, **μ+ = 1.5**, RNG **`np.random.default_rng(4242)`** (scenario B consumes the next 400 draws after scenario A).

**Split definition:** τ* is the **first-segment length**: observations `0 … τ*−1` follow μ−; `τ* … n−1` follow μ+.

**Methods**

1. **Grid SSE:** For each candidate τ in **[10, 390]** (both segments ≥ 10 points), compute two-segment SSE with segment-specific sample means; choose minimizing τ.
2. **CUSUM:** Let `C_k = Σ_{i<k}(x_i − x̄)` for k = 0…n. Restrict argmax of **abs(C_k)** to **k ∈ [10, 390]** so the peak is not taken at trivial endpoints.

Run: `python demos/ab_rnd_baseline/run_changepoint_benchmark.py`

## |τ̂ − τ*| (this seed)

| Scenario | τ* | Method | τ̂ | abs error |
|----------|---:|--------|---:|----------:|
| A (interior) | 200 | grid_SSE | 200 | 0 |
| A | 200 | CUSUM_abs_argmax | 200 | 0 |
| B (edge) | 45 | grid_SSE | 45 | 0 |
| B | 45 | CUSUM_abs_argmax | 45 | 0 |

## Narrative

On this single realization both estimators recover the true τ* exactly for interior and early-edge placements: the mean gap is large relative to σ and **n**, so SSE curvature is sharp at the true split and the global-mean CUSUM magnitude peaks at the same boundary once extremes are clipped.

The figures under **`out/`** show the series with true vs estimated cuts, the SSE bowl over τ, and the |CUSUM| path. Edge scenario B remains **inside** the allowed grid `τ ≥ 10`; a much smaller true τ* could clip against **L_MIN** and bias estimators—a limit of the documented edge rule, not of the generators.
