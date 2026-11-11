"""CTR model evaluation over time: discrimination, calibration, stability.

Setup mirrors production: train on Oct 21-27, then score each later day (Oct 28, 29, 30)
as if it arrived live. Three policies are compared:
  frozen        - train once, never touched
  frozen+recal  - same model, Platt-recalibrated each day on the previous day's labels
  daily_retrain - retrained each day on all labeled data up to the previous day
"""
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

LOW_CARD = ["C1", "banner_pos", "site_category", "app_category", "device_type", "device_conn_type"]
HIGH_CARD = ["site_id", "site_domain", "app_id", "device_model", "device_ip", "device_id"]
NUMERIC = ["C14", "C15", "C16", "C17", "C18", "C19", "C20", "C21"]
PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 200,
          "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
          "verbose": -1, "seed": 42, "deterministic": True, "num_threads": 4}
N_ROUNDS = 300


def make_features(train: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Count-encode high-cardinality ids using the training window only (no future info)."""
    X = pd.DataFrame(index=frame.index)
    for c in LOW_CARD:
        X[c] = frame[c].astype("category")
    for c in HIGH_CARD:
        counts = train[c].value_counts()
        X[c + "_cnt"] = frame[c].map(counts).fillna(0).astype(float)
    for c in NUMERIC:
        X[c] = frame[c]
    X["hour_of_day"] = frame.event_hour.dt.hour
    X["is_site"] = (frame.traffic_source == "site").astype(int)
    return X


def align_categories(X_train: pd.DataFrame, X_other: pd.DataFrame) -> pd.DataFrame:
    X_other = X_other.copy()
    for c in LOW_CARD:
        X_other[c] = pd.Categorical(X_other[c].astype(X_train[c].cat.categories.dtype),
                                    categories=X_train[c].cat.categories)
    return X_other


def fit(train: pd.DataFrame):
    X = make_features(train, train)
    booster = lgb.train(PARAMS, lgb.Dataset(X, train.click, categorical_feature=LOW_CARD), N_ROUNDS)
    return booster, X


def predict(booster, train, X_train, frame):
    return booster.predict(align_categories(X_train, make_features(train, frame)))


def ece(y, p, bins: int = 10) -> float:
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    err = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            err += m.mean() * abs(p[m].mean() - y[m].mean())
    return err


def calibration_slope_intercept(y, p):
    logit = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6))).reshape(-1, 1)
    lr = LogisticRegression(C=1e6).fit(logit, y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def normalized_entropy(y, p) -> float:
    """Log loss divided by the log loss of always predicting the base rate (lower is better; 1 = no skill)."""
    base = y.mean()
    return log_loss(y, p) / log_loss(y, np.full_like(p, base, dtype=float))


def psi(expected, actual, bins: int = 10) -> float:
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def metrics(y, p) -> dict:
    slope, intercept = calibration_slope_intercept(y, p)
    return {"n": len(y), "actual_ctr": y.mean(), "mean_pred": p.mean(),
            "pred_over_actual": p.mean() / y.mean(), "auc": roc_auc_score(y, p),
            "log_loss": log_loss(y, p), "normalized_entropy": normalized_entropy(y, p),
            "ece": ece(y, p), "cal_slope": slope, "cal_intercept": intercept}


def paired_bootstrap_auc_delta(y, p_a, p_b, n_boot: int = 1000, seed: int = 0):
    """AUC(b) - AUC(a) with a 95% percentile CI from resampling the same impressions."""
    rng = np.random.default_rng(seed)
    n = len(y)
    deltas = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        deltas.append(roc_auc_score(y[i], p_b[i]) - roc_auc_score(y[i], p_a[i]))
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return roc_auc_score(y, p_b) - roc_auc_score(y, p_a), lo, hi


def platt(p_prev, y_prev):
    logit = lambda q: np.log(np.clip(q, 1e-6, 1 - 1e-6) / (1 - np.clip(q, 1e-6, 1 - 1e-6)))
    lr = LogisticRegression(C=1e6).fit(logit(p_prev).reshape(-1, 1), y_prev)
    return lambda q: lr.predict_proba(logit(q).reshape(-1, 1))[:, 1]


def evaluate(df: pd.DataFrame, train_end: str = "2014-10-27"):
    df = df.sort_values(["event_hour", "id"]).reset_index(drop=True)
    dates = sorted(df.event_date.unique())
    train_end = pd.Timestamp(train_end).date()
    eval_dates = [d for d in dates if d > train_end]
    train = df[df.event_date <= train_end]

    frozen, X_tr = fit(train)
    train_scores = frozen.predict(X_tr)

    # in-time holdout benchmark: last training day held out from a model trained on the days before
    pre = df[df.event_date < train_end]
    b_pre, X_pre = fit(pre)
    last = df[df.event_date == train_end]
    rows = [{"policy": "in_time_holdout", "date": str(train_end),
             **metrics(last.click.values, predict(b_pre, pre, X_pre, last))}]

    psi_rows = []
    for d in eval_dates:
        day = df[df.event_date == d]
        y = day.click.values
        p_frozen = predict(frozen, train, X_tr, day)
        rows.append({"policy": "frozen", "date": str(d), **metrics(y, p_frozen)})

        prev = df[df.event_date == dates[dates.index(d) - 1]]
        cal = platt(predict(frozen, train, X_tr, prev), prev.click.values)
        rows.append({"policy": "frozen+recal", "date": str(d), **metrics(y, cal(p_frozen))})

        hist = df[df.event_date < d]
        b_rt, X_rt = fit(hist)
        p_rt = predict(b_rt, hist, X_rt, day)
        rows.append({"policy": "daily_retrain", "date": str(d), **metrics(y, p_rt)})
        delta, lo, hi = paired_bootstrap_auc_delta(y, p_frozen, p_rt)
        rows[-1].update({"auc_delta_vs_frozen": delta, "auc_delta_ci_low": lo, "auc_delta_ci_high": hi})

        base_rate = np.full(len(y), hist.click.mean())
        rows.append({"policy": "base_rate", "date": str(d), "n": len(y), "actual_ctr": y.mean(),
                     "mean_pred": base_rate.mean(), "pred_over_actual": base_rate.mean() / y.mean(),
                     "auc": 0.5, "log_loss": log_loss(y, base_rate),
                     "normalized_entropy": normalized_entropy(y, base_rate),
                     "ece": abs(base_rate.mean() - y.mean()), "cal_slope": np.nan, "cal_intercept": np.nan})

        Xd = align_categories(X_tr, make_features(train, day))
        feat_psi = {c: psi(X_tr[c].astype(float).values, Xd[c].astype(float).values)
                    for c in X_tr.columns if c not in LOW_CARD}
        unseen = {f"unseen_{c}_share": float((~day[c].isin(set(train[c]))).mean())
                  for c in ("C14", "C17", "site_id", "app_id")}
        psi_rows.append({"date": str(d), "score_psi": psi(train_scores, p_frozen), **unseen, **feat_psi})

    importance = pd.Series(frozen.feature_importance("gain"), index=X_tr.columns).sort_values(ascending=False)
    return pd.DataFrame(rows), pd.DataFrame(psi_rows), importance
