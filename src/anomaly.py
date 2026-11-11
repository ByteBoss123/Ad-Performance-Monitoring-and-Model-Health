"""Hourly KPI anomaly detection with hour-of-day seasonality.

For each hour, the expected value comes only from *earlier* days at the same hour of day
(no look-ahead). CTR is scored with a binomial z-score that also carries the uncertainty
of the baseline; volume is scored with a robust z-score on log impressions.
"""
import numpy as np
import pandas as pd

MIN_HISTORY_DAYS = 3


def score_hours(hourly: pd.DataFrame, z_threshold: float = 3.0, phi: float = 1.0,
                vol_scale: float = 1.0) -> pd.DataFrame:
    """phi: CTR variance inflation (quasi-binomial); vol_scale: divisor on the volume z-score."""
    """hourly: columns event_hour, event_date, hour_of_day, impressions, clicks."""
    df = hourly.sort_values("event_hour").reset_index(drop=True).copy()
    rows = []
    for _, r in df.iterrows():
        hist = df[(df.hour_of_day == r.hour_of_day) & (df.event_date < r.event_date)]
        if len(hist) < MIN_HISTORY_DAYS:
            rows.append((np.nan, np.nan, np.nan, np.nan))
            continue
        base_clicks, base_imps = hist.clicks.sum(), hist.impressions.sum()
        p0 = base_clicks / base_imps
        p = r.clicks / r.impressions
        se = np.sqrt(p0 * (1 - p0) / r.impressions + p0 * (1 - p0) / base_imps)
        z_ctr = (p - p0) / (se * np.sqrt(phi))
        log_hist = np.log(hist.impressions.values)
        med = np.median(log_hist)
        mad = np.median(np.abs(log_hist - med)) * 1.4826
        mad = max(mad, 0.05)  # floor so a very stable history cannot make every move "extreme"
        z_vol = (np.log(r.impressions) - med) / mad / vol_scale
        rows.append((p0, z_ctr, float(np.exp(med)), z_vol))
    df[["expected_ctr", "z_ctr", "expected_impressions", "z_volume"]] = rows
    df["ctr_flag"] = df.z_ctr.abs() > z_threshold
    df["volume_flag"] = df.z_volume.abs() > z_threshold
    return df


def robust_scale(z: pd.Series) -> float:
    """1.4826 * MAD: a standard-deviation estimate that real anomalies barely move."""
    z = z.dropna().to_numpy()
    return float(1.4826 * np.median(np.abs(z - np.median(z))))


def fit_dispersion(scored_raw: pd.DataFrame, calib_dates) -> tuple[float, float]:
    """Estimate CTR overdispersion (phi) and volume scale from a calibration window of raw scores."""
    c = scored_raw[scored_raw.event_date.isin(calib_dates)]
    return max(robust_scale(c.z_ctr) ** 2, 1.0), max(robust_scale(c.z_volume), 1.0)


def injection_test(hourly: pd.DataFrame, drops=(0.10, 0.20, 0.30, 0.50), n_trials: int = 200,
                   z_threshold: float = 3.0, seed: int = 7, phi: float = 1.0) -> pd.DataFrame:
    """Sensitivity check: thin the real clicks of one scorable hour by `drop` (binomial),
    rescore, and record whether that hour is flagged. Only the injected hour is altered;
    everything else is the real data."""
    rng = np.random.default_rng(seed)
    base = hourly.sort_values("event_hour").reset_index(drop=True)
    scored = score_hours(base, z_threshold, phi=phi)
    candidates = scored.index[scored.z_ctr.notna() & ~scored.ctr_flag].to_numpy()
    out = []
    for drop in drops:
        hits = 0
        for _ in range(n_trials):
            i = rng.choice(candidates)
            mod = base.copy()
            mod.loc[i, "clicks"] = rng.binomial(int(mod.loc[i, "clicks"]), 1 - drop)
            # score just that hour against its (unchanged) history
            hist = mod[(mod.hour_of_day == mod.loc[i, "hour_of_day"]) & (mod.event_date < mod.loc[i, "event_date"])]
            p0 = hist.clicks.sum() / hist.impressions.sum()
            n = mod.loc[i, "impressions"]
            p = mod.loc[i, "clicks"] / n
            se = np.sqrt(phi * (p0 * (1 - p0) / n + p0 * (1 - p0) / hist.impressions.sum()))
            hits += abs((p - p0) / se) > z_threshold
        out.append({"ctr_drop": drop, "detection_rate": hits / n_trials, "trials": n_trials})
    return pd.DataFrame(out)


def daily_injection_test(hourly: pd.DataFrame, drops=(0.05, 0.10, 0.20), z_threshold: float = 3.0,
                         seed: int = 11, n_trials: int = 200, phi: float = 1.0) -> pd.DataFrame:
    """Same idea at daily grain: a sustained drop across all 24 hours of a day, scored against
    all prior days."""
    rng = np.random.default_rng(seed)
    daily = hourly.groupby("event_date", as_index=False)[["impressions", "clicks"]].sum()
    daily = daily.sort_values("event_date").reset_index(drop=True)
    idx = daily.index[daily.index >= MIN_HISTORY_DAYS].to_numpy()
    out = []
    for drop in drops:
        hits = 0
        for _ in range(n_trials):
            i = rng.choice(idx)
            hist = daily.iloc[:i]
            p0 = hist.clicks.sum() / hist.impressions.sum()
            n = daily.loc[i, "impressions"]
            c = rng.binomial(int(daily.loc[i, "clicks"]), 1 - drop)
            se = np.sqrt(phi * (p0 * (1 - p0) / n + p0 * (1 - p0) / hist.impressions.sum()))
            hits += abs((c / n - p0) / se) > z_threshold
        out.append({"ctr_drop": drop, "detection_rate": hits / n_trials, "trials": n_trials})
    return pd.DataFrame(out)
