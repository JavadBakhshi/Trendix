"""Online models with walk-forward check to reduce look-ahead bias."""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLS = [
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "ret_20",
    "rsi",
    "macd_hist",
    "bb_pct",
    "dist_sma50",
    "volume_ratio",
    "stoch_k",
    "atr_pct",
    "adx",
    "cci",
]


def score_ml(df: pd.DataFrame) -> dict:
    feat_cols = [c for c in FEATURE_COLS if c in df.columns]
    work = df.dropna(subset=feat_cols).copy()
    if len(work) < 90:
        return {"score": 0.0, "ok": False, "expected_return": 0.0, "up_prob": 0.5, "hit_rate": None, "reasons": []}

    X = work[feat_cols].to_numpy(dtype=float)
    y = work["close"].pct_change().shift(-1).to_numpy(dtype=float)
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    mask[-1] = False
    if mask.sum() < 70:
        return {"score": 0.0, "ok": False, "expected_return": 0.0, "up_prob": 0.5, "hit_rate": None, "reasons": []}

    idx = np.where(mask)[0]
    split = int(len(idx) * 0.75)
    train_i, test_i = idx[:split], idx[split:]
    ridge_ret, ridge_ok = _ridge(X, y, train_i, X[-1])
    log_prob, log_ok = _logreg(X, y, train_i, X[-1])
    hit = _hit_rate(X, y, train_i, test_i) if len(test_i) >= 20 else None

    expected = ridge_ret if ridge_ok else 0.0
    up_prob = log_prob if log_ok else 0.5
    ml_score = float(np.clip(expected * 2200, -100, 100))
    if log_ok:
        ml_score = 0.6 * ml_score + 0.4 * ((up_prob - 0.5) * 200)

    if hit is not None and hit < 0.52:
        ml_score *= 0.45  # downweight if walk-forward is weak
        note = f"مدل ML ضعیف است (hit-rate {hit*100:.0f}٪ روی walk-forward)؛ وزن کاهش یافت"
        bias = "neutral"
    else:
        note = f"Ridge+Logistic: احتمال صعود {up_prob*100:.0f}٪"
        bias = "buy" if ml_score > 8 else "sell" if ml_score < -8 else "neutral"

    return {
        "score": float(np.clip(ml_score, -100, 100)),
        "ok": ridge_ok or log_ok,
        "expected_return": float(expected),
        "up_prob": round(float(up_prob) * 100, 1),
        "down_prob": round((1 - float(up_prob)) * 100, 1),
        "hit_rate": None if hit is None else round(hit * 100, 1),
        "reasons": [{"id": "ml", "text": note, "bias": bias}],
    }


def _ridge(X, y, train_i, x_last, lam: float = 2.5):
    Xt, yt = X[train_i], y[train_i]
    mean, std = Xt.mean(0), Xt.std(0)
    std[std == 0] = 1
    Xs = (Xt - mean) / std
    n, p = Xs.shape
    Xb = np.c_[np.ones(n), Xs]
    eye = np.eye(p + 1)
    eye[0, 0] = 0
    try:
        beta = np.linalg.pinv(Xb.T @ Xb + lam * eye) @ Xb.T @ yt
    except np.linalg.LinAlgError:
        return 0.0, False
    pred = float(beta[0] + ((x_last - mean) / std) @ beta[1:])
    if not np.isfinite(pred):
        return 0.0, False
    return float(np.clip(pred, -0.06, 0.06)), True


def _logreg(X, y, train_i, x_last, steps: int = 80, lr: float = 0.15):
    yt = (y[train_i] > 0).astype(float)
    Xt = X[train_i]
    mean, std = Xt.mean(0), Xt.std(0)
    std[std == 0] = 1
    Xs = np.c_[np.ones(len(Xt)), (Xt - mean) / std]
    w = np.zeros(Xs.shape[1])
    for _ in range(steps):
        z = np.clip(Xs @ w, -20, 20)
        p = 1 / (1 + np.exp(-z))
        w -= lr * (Xs.T @ (p - yt)) / len(yt)
    xl = np.r_[1.0, (x_last - mean) / std]
    prob = float(1 / (1 + np.exp(-np.clip(xl @ w, -20, 20))))
    return prob, True


def _hit_rate(X, y, train_i, test_i) -> float | None:
    pred, ok = _ridge(X, y, train_i, X[test_i[0]])
    if not ok:
        return None
    # refit once on train, evaluate sign on test
    Xt, yt = X[train_i], y[train_i]
    mean, std = Xt.mean(0), Xt.std(0)
    std[std == 0] = 1
    Xs = np.c_[np.ones(len(Xt)), (Xt - mean) / std]
    eye = np.eye(Xs.shape[1])
    eye[0, 0] = 0
    beta = np.linalg.pinv(Xs.T @ Xs + 2.5 * eye) @ Xs.T @ yt
    Xte = np.c_[np.ones(len(test_i)), (X[test_i] - mean) / std]
    yhat = Xte @ beta
    ytrue = y[test_i]
    valid = np.isfinite(yhat) & np.isfinite(ytrue) & (ytrue != 0)
    if valid.sum() < 10:
        return None
    return float((np.sign(yhat[valid]) == np.sign(ytrue[valid])).mean())
