"""One-off generator: writes observations.csv (committed for reproducibility)."""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SEED = 20260204
RNG = np.random.default_rng(SEED)

# Canonical truth (embedded identically in judge.py)
MU = np.array([2.5, 5.35, 7.92], dtype=float)
SIG = np.array([0.38, 0.26, 0.41], dtype=float)
AMP = np.array([1.15, 0.78, 0.62], dtype=float)


def truth_at(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.zeros_like(x, dtype=float)
    for mu, sig, amp in zip(MU, SIG, AMP, strict=True):
        y += amp * np.exp(-0.5 * ((x - mu) / sig) ** 2)
    return y


def main() -> None:
    n = 240
    x = np.sort(RNG.uniform(0.0, 10.0, size=n))
    y = truth_at(x) + RNG.normal(0.0, 0.065, size=n)
    df = pd.DataFrame({"x": x, "y": y})
    out = ROOT / "observations.csv"
    df.to_csv(out, index=False)
    print("wrote", out)


if __name__ == "__main__":
    main()
