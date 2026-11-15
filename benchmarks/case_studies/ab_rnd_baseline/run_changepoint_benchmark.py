"""
Synthetic mean-shift changepoint benchmark (grid SSE vs |CUSUM| argmax).

Outputs under benchmarks/case_studies/ab_rnd_baseline/out/: PNG diagnostics + prints a summary table.
"""

from __future__ import annotations

import os

import numpy as np
import matplotlib.pyplot as plt

# --- Experiment constants ---
N = 400
SIGMA = 0.4
RNG = np.random.default_rng(4242)
MU_MINUS = 0.0
MU_PLUS = 1.5

# Interior grid / edge clipping: require at least L_MIN observations per segment so
# segment means are stable and we avoid degenerate SSE minima at τ in {1, n-1}.
# Same interior index set used for |CUSUM| argmax (exclude extremes).
L_MIN = 10  # τ and CUSUM k restricted to [L_MIN, N-L_MIN]


def simulate_series(tau_star: int) -> np.ndarray:
    """Mean shift after tau_star observations (first segment length tau_star)."""
    assert 1 <= tau_star <= N - 1
    x = np.empty(N, dtype=np.float64)
    x[:tau_star] = MU_MINUS + RNG.normal(scale=SIGMA, size=tau_star)
    x[tau_star:] = MU_PLUS + RNG.normal(scale=SIGMA, size=N - tau_star)
    return x


def sse_two_segment(x: np.ndarray, tau: int) -> float:
    """Two-segment SSE with segment-specific sample means; tau = len(segment 1)."""
    seg1 = x[:tau]
    seg2 = x[tau:]
    v1 = seg1 - seg1.mean()
    v2 = seg2 - seg2.mean()
    return float(np.dot(v1, v1) + np.dot(v2, v2))


def grid_sse_tau_hat(x: np.ndarray) -> tuple[int, np.ndarray]:
    taus = np.arange(L_MIN, N - L_MIN + 1, dtype=np.int64)
    sses = np.array([sse_two_segment(x, int(t)) for t in taus])
    idx = int(np.argmin(sses))
    return int(taus[idx]), sses


def cusum_abs_argmax(x: np.ndarray) -> tuple[int, np.ndarray]:
    """|CUSUM| vs split index k = len(prefix): C[k]=sum_{i<k}(x_i - mean(x)), k=0..N."""
    x_bar = x.mean()
    dev = x - x_bar
    C = np.concatenate([[0.0], np.cumsum(dev)])
    absC = np.abs(C)
    interior = slice(L_MIN, N - L_MIN + 1)
    rel_idx = int(np.argmax(absC[interior]))
    k_hat = L_MIN + rel_idx
    return k_hat, absC


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(root, "out")
    os.makedirs(out_dir, exist_ok=True)

    scenarios = [
        {"name": "A_interior", "tau_star": 200, "title": r"Scenario A: $\tau^*=200$ (interior)"},
        {"name": "B_edge", "tau_star": 45, "title": r"Scenario B: $\tau^*=45$ (edge)"},
    ]

    rows = []

    for sc in scenarios:
        tau_star = sc["tau_star"]
        x = simulate_series(tau_star)

        tau_sse, sses = grid_sse_tau_hat(x)
        tau_cusum, absC = cusum_abs_argmax(x)

        rows.append((sc["name"], "grid_SSE", tau_star, tau_sse, abs(tau_sse - tau_star)))
        rows.append((sc["name"], "CUSUM_abs_argmax", tau_star, tau_cusum, abs(tau_cusum - tau_star)))

        taus_grid = np.arange(L_MIN, N - L_MIN + 1)

        fig, axes = plt.subplots(2, 1, figsize=(10, 6), constrained_layout=True)
        axes[0].plot(np.arange(N), x, lw=0.8, color="0.25")
        axes[0].axvline(tau_star - 0.5, color="green", ls="--", lw=1.5, label=r"true $\tau^*$ boundary")
        axes[0].axvline(tau_sse - 0.5, color="C0", ls=":", lw=1.5, label=rf"SSE $\hat{{\tau}}={tau_sse}$")
        axes[0].axvline(tau_cusum - 0.5, color="C3", ls=":", lw=1.5, label=rf"CUSUM $\hat{{\tau}}={tau_cusum}$")
        axes[0].set_title(sc["title"] + r": series ($\mu_-=0$, $\mu_+=1.5$, $\sigma=0.4$, n=400)")
        axes[0].set_xlabel("t (index)")
        axes[0].set_ylabel("x")
        axes[0].legend(loc="upper left", fontsize=8)

        axes[1].plot(taus_grid, sses, color="C0", lw=1.2, label="two-segment SSE")
        axes[1].axvline(tau_star, color="green", ls="--", lw=1.2)
        axes[1].axvline(tau_sse, color="C0", ls=":", lw=1.2)
        axes[1].set_xlabel(r"candidate split $\tau$ (first segment length)")
        axes[1].set_ylabel("SSE")
        axes[1].legend(loc="upper right", fontsize=8)

        fig.savefig(os.path.join(out_dir, f"changepoint_{sc['name']}_series_sse.png"), dpi=150)
        plt.close(fig)

        k_axis = np.arange(N + 1)
        fig2, ax = plt.subplots(figsize=(10, 3.5), constrained_layout=True)
        ax.plot(k_axis, absC, color="C3", lw=1.0, label=r"$|C_k|$ (global-mean CUSUM)")
        ax.axvline(tau_star, color="green", ls="--", lw=1.2, label=r"true $\tau^*$")
        ax.axvline(tau_cusum, color="k", ls=":", lw=1.2, label=rf"argmax interior $\hat{{\tau}}={tau_cusum}$")
        ax.fill_between(k_axis, 0, absC, alpha=0.12, color="C3")
        ax.set_xlim(0, N)
        ax.set_xlabel(r"$k$ (prefix length; $C_k=\sum_{i<k}(x_i-\bar{x})$)")
        ax.set_ylabel(r"$|C_k|$")
        ax.set_title(sc["title"] + r": $|CUSUM|$ path")
        ax.legend(loc="upper right", fontsize=8)
        fig2.savefig(os.path.join(out_dir, f"changepoint_{sc['name']}_cusum_abs.png"), dpi=150)
        plt.close(fig2)

    print(
        "Interior / edge clipping: tau (SSE grid) and k (CUSUM argmax) restricted to "
        f"[{L_MIN}, {N - L_MIN}] so each segment has >= {L_MIN} points."
    )
    print()
    print("|scenario|method|tau_star|tau_hat|abs_err|")
    print("|---|---|---:|---:|---:|")
    for name, method, ts, th, err in rows:
        print(f"|{name}|{method}|{ts}|{th}|{err}|")


if __name__ == "__main__":
    main()
