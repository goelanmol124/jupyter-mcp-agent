"""Robust curve fit for benchmark_robust_curve → submission_branchB.csv."""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import HuberRegressor
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

DIR = Path(__file__).resolve().parent


def feats_fourier(t: np.ndarray, n_harm: int, omega: float) -> np.ndarray:
    t = np.asarray(t, dtype=float).ravel()
    cols = [np.ones_like(t), t, t**2]
    for k in range(1, n_harm + 1):
        cols.append(np.sin(k * omega * t))
        cols.append(np.cos(k * omega * t))
    return np.column_stack(cols)


def cv_mad(fit_predict):
    tr = pd.read_csv(DIR / "train.csv").sort_values("t")
    t = tr["t"].values.astype(float)
    y = tr["y_meas"].values.astype(float)
    kf = KFold(n_splits=5, shuffle=True, random_state=0)
    scores = []
    for tr_idx, te_idx in kf.split(t):
        tt, yt = t[tr_idx], y[tr_idx]
        tv, yv = t[te_idx], y[te_idx]
        yhat = fit_predict(tt, yt, tv)
        scores.append(np.median(np.abs(yhat - yv)))
    return float(np.mean(scores))


def huber_spline(tt, yt, tv):
    nk = min(28, max(10, len(tt) // 7))
    pipe = make_pipeline(
        SplineTransformer(n_knots=nk, degree=3),
        StandardScaler(with_mean=False),
        HuberRegressor(max_iter=500),
    )
    pipe.fit(tt.reshape(-1, 1), yt)
    return pipe.predict(tv.reshape(-1, 1))


def huber_four(tt, yt, tv, omega: float, nh: int):
    Xtr = feats_fourier(tt, nh, omega)
    Xv = feats_fourier(tv, nh, omega)
    pipe = make_pipeline(StandardScaler(), HuberRegressor(max_iter=2000))
    pipe.fit(Xtr, yt)
    return pipe.predict(Xv)


def gbrt_huber(tt, yt, tv):
    m = GradientBoostingRegressor(
        loss="huber",
        max_depth=3,
        n_estimators=400,
        learning_rate=0.04,
        subsample=0.85,
        random_state=0,
    )
    m.fit(tt.reshape(-1, 1), yt)
    return m.predict(tv.reshape(-1, 1))


def pick_model():
    sc_spline = cv_mad(huber_spline)
    best_o, best_sc = None, 1e9
    for omega in np.linspace(1.4, 9.0, 35):
        nh = 14

        def fp(tt, yt, tv, o=omega):
            return huber_four(tt, yt, tv, o, nh)

        sc = cv_mad(fp)
        if sc < best_sc:
            best_sc, best_o = sc, omega
    sc_gb = cv_mad(gbrt_huber)
    return sc_spline, best_o, best_sc, sc_gb


def main():
    sc_spline, best_o, best_four, sc_gb = pick_model()
    print(
        "CV median MAD - spline Huber:",
        round(sc_spline, 5),
        "Fourier Huber (best omega):",
        round(best_four, 5),
        "omega:",
        round(best_o, 4),
        "GBRT huber:",
        round(sc_gb, 5),
    )

    tr = pd.read_csv(DIR / "train.csv").sort_values("t")
    ho = pd.read_csv(DIR / "holdout_inputs.csv")
    t_tr = tr["t"].values.astype(float)
    y_tr = tr["y_meas"].values.astype(float)
    t_ho = ho["t"].values.astype(float)

    ps = huber_spline(t_tr, y_tr, t_ho)
    pf = huber_four(t_tr, y_tr, t_ho, best_o, 14)
    # Weight by inverse CV MAD (GBRT was weaker on this split; omit).
    ws = 1.0 / max(sc_spline, 1e-6)
    wf = 1.0 / max(best_four, 1e-6)
    y_hat = (ws * ps + wf * pf) / (ws + wf)

    out = pd.DataFrame({"idx": ho["idx"].astype(int), "y_hat": y_hat})
    out_path = DIR / "submission_branchB.csv"
    out.to_csv(out_path, index=False, lineterminator="\n", float_format="%.10f")
    assert len(out) == 480
    assert list(out.columns) == ["idx", "y_hat"]
    print("wrote", out_path, "rows", len(out))


if __name__ == "__main__":
    main()
