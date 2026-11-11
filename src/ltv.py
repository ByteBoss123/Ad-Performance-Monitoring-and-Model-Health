"""Customer LTV on real purchase data (CDNOW: 23,570 customers acquired Jan-Mar 1997, purchases to Jun 1998).

1. Cohort value curves: cumulative revenue per acquired customer at 30/90/180/365 days, by acquisition month.
2. ARPDAU: revenue per daily active (purchasing) customer.
3. Predictive LTV: BG/NBD (repeat-purchase frequency) + Gamma-Gamma (spend per order), fit on a
   39-week calibration window, then scored on the next 39 weeks the model never saw.
"""
from pathlib import Path

import pandas as pd
from lifetimes import BetaGeoFitter, GammaGammaFitter
from lifetimes.utils import calibration_and_holdout_data

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_ltv" / "CDNOW_master.txt"


def load() -> pd.DataFrame:
    df = pd.read_csv(RAW, sep=r"\s+", header=None, skiprows=1,
                     names=["customer_id", "date", "number_of_cds", "dollar_value"], dtype={"customer_id": str})
    df["date"] = pd.to_datetime(df.date.astype(str), format="%Y%m%d")
    return df


def daily_orders(df):
    """Same-day transactions collapse to one order (the standard CDNOW treatment)."""
    return df.groupby(["customer_id", "date"], as_index=False).dollar_value.sum()


def cohort_curves(df, horizons=(30, 90, 180, 365)) -> pd.DataFrame:
    first = df.groupby("customer_id").date.min().rename("first")
    d = df.join(first, on="customer_id")
    d["age"] = (d.date - d["first"]).dt.days
    d["cohort"] = d["first"].dt.to_period("M").astype(str)
    sizes = d.groupby("cohort").customer_id.nunique()
    out = pd.DataFrame({"customers": sizes})
    for h in horizons:
        out[f"ltv_{h}d"] = d[d.age < h].groupby("cohort").dollar_value.sum() / sizes
    out.loc["all"] = [sizes.sum()] + [d[d.age < h].dollar_value.sum() / sizes.sum() for h in horizons]
    return out


def arpdau(df) -> pd.DataFrame:
    g = daily_orders(df).groupby("date")
    a = pd.DataFrame({"active_customers": g.customer_id.nunique(), "revenue": g.dollar_value.sum()})
    a["arpdau"] = a.revenue / a.active_customers
    return a


def predictive_ltv(df, calib_end="1997-09-30", obs_end="1998-06-30"):
    o = daily_orders(df)
    ch = calibration_and_holdout_data(o, "customer_id", "date", calibration_period_end=calib_end,
                                      observation_period_end=obs_end, freq="D", monetary_value_col="dollar_value")
    horizon = ch.duration_holdout.iloc[0]
    bgf = BetaGeoFitter(penalizer_coef=0.0).fit(ch.frequency_cal, ch.recency_cal, ch.T_cal)
    ch["pred_purchases"] = bgf.conditional_expected_number_of_purchases_up_to_time(
        horizon, ch.frequency_cal, ch.recency_cal, ch.T_cal)
    rep = ch[(ch.frequency_cal > 0) & (ch.monetary_value_cal > 0)]
    ggf = GammaGammaFitter(penalizer_coef=0.0).fit(rep.frequency_cal, rep.monetary_value_cal)
    # expected spend per order; customers with no repeat order get the population mean
    ch["pred_aov"] = ggf.conditional_expected_average_profit(ch.frequency_cal, ch.monetary_value_cal)
    ch.loc[ch.frequency_cal == 0, "pred_aov"] = ggf.conditional_expected_average_profit(
        pd.Series([0]), pd.Series([0.0])).iloc[0]
    ch["pred_value"] = ch.pred_purchases * ch.pred_aov
    # actual holdout revenue (repeat orders only, matching what the model predicts)
    hold = o[(o.date > pd.Timestamp(calib_end)) & (o.date <= pd.Timestamp(obs_end))]
    ch["actual_value"] = hold.groupby("customer_id").dollar_value.sum().reindex(ch.index).fillna(0)

    # naive baseline: each customer repeats their calibration-period repeat-revenue rate
    cal = o[o.date <= pd.Timestamp(calib_end)]
    first = cal.groupby("customer_id").date.min()
    cal_rep = cal[cal.date > cal.customer_id.map(first)].groupby("customer_id").dollar_value.sum()
    ch["naive_value"] = cal_rep.reindex(ch.index).fillna(0) / ch.T_cal.clip(lower=1) * horizon

    ch["decile"] = pd.qcut(ch.pred_value.rank(method="first"), 10, labels=range(1, 11)).astype(int)
    dec = ch.groupby("decile")[["pred_value", "actual_value"]].mean()
    top10 = ch[ch.decile == 10].actual_value.sum() / ch.actual_value.sum()

    def mae(col):
        return float((ch[col] - ch.actual_value).abs().mean())

    summary = {
        "customers": len(ch), "holdout_days": int(horizon),
        "bgnbd_params": {k: float(v) for k, v in bgf.params_.items()},
        "gg_params": {k: float(v) for k, v in ggf.params_.items()},
        "total_actual_holdout_revenue": float(ch.actual_value.sum()),
        "total_predicted_holdout_revenue": float(ch.pred_value.sum()),
        "total_naive_holdout_revenue": float(ch.naive_value.sum()),
        "aggregate_error_pct": float(ch.pred_value.sum() / ch.actual_value.sum() - 1) * 100,
        "naive_aggregate_error_pct": float(ch.naive_value.sum() / ch.actual_value.sum() - 1) * 100,
        "mae_model": mae("pred_value"), "mae_naive": mae("naive_value"),
        "spearman_pred_actual": float(ch.pred_value.corr(ch.actual_value, method="spearman")),
        "top_decile_share_of_actual_revenue": float(top10),
        "freq_corr_gg_assumption": float(rep.frequency_cal.corr(rep.monetary_value_cal)),
    }
    return summary, dec, ch


if __name__ == "__main__":
    import json
    d = load()
    print(d.shape, d.customer_id.nunique(), d.date.min(), d.date.max(), round(d.dollar_value.sum(), 2))
    print(cohort_curves(d).round(2))
    a = arpdau(d)
    print(a.arpdau.describe().round(2))
    s, dec, _ = predictive_ltv(d)
    print(json.dumps(s, indent=1))
    print(dec.round(2))
