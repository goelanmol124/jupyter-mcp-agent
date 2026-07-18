# Biexponential toy — results (no MCP run)

## Figures

- `outputs/01_sim_y_vs_t.png` — simulated data
- `outputs/02_truth_vs_fit_table.png` — truth vs fitted parameters
- `outputs/03_biexp_fit_overlay_residuals.png` — correct-model overlay, residuals vs t, residual histogram
- `outputs/04_monoexp_misfit_residuals.png`, `outputs/04b_monoexp_residual_hist.png` — misspecified single exponential

## Numeric summary

- RMSE (biexponential): **0.01857**
- RMSE (single exponential): **0.03818**
- Relative abs error (fit vs truth): A1=1.42%, k1=0.58%, A2=3.37%, k2=3.25%

## Conclusions

- The **4-parameter biexponential** recovers ground-truth parameters to within sampling noise; **residuals vs t are mostly structureless** and the histogram is **consistent with Gaussian noise** (σ=0.02).
- A **single exponential is visibly misspecified**: **residuals show a systematic drift** (sign changes across t) and the **histogram is not Gaussian**, signalling unmodeled dynamics (the slower decay).
- **Nonlinear least squares hits the same predictive surface** for informative data, but **(A1,k1) vs (A2,k2) can swap** across random restarts because the two-term sum is symmetric in the labels—tie-breaking needs **constraints, priors, or side information**, not RSS alone.
- For this SNR and sampling, **curve_fit with a reasonable prior guess is adequate** for recovery when labels are fixed by convention; production work would add **bounds, multi-start search, and explicit measurement model checks**.
- **Residual structure beats a single RMSE**: the monoexp fit here has **noticeably higher RMSE** yet the critical signal is **systematic residual curvature vs t** and a **non-Gaussian** histogram, not the scalar loss gap.

## Short text — misspecification

The single-exponential fit absorbs part of the slow decay into the fast mode, so residuals are mostly negative at early times and positive at late times (a curved pattern in y vs t is folded into amplitude/decay rate). The residual histogram departs from Gaussian: longer tails and skew from structured error.

## Optimizer / initial guesses

See `outputs/optimizer_sensitivity_note.txt`.
