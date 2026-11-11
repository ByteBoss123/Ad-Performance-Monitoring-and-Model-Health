"""Mix-vs-rate decomposition of a change in an aggregate rate (CTR).

CTR_t = sum_s w_s,t * r_s,t where w is a segment's impression share and r its CTR.
Delta CTR = mix (sum dw * r0) + rate (sum w0 * dr) + interaction (sum dw * dr). Exact.
"""
import pandas as pd


def decompose(seg: pd.DataFrame, date0, date1, dimension: str) -> dict:
    """seg: long table with event_date, dimension, segment, impressions, clicks."""
    s = seg[seg.dimension == dimension]
    a = s[s.event_date == date0].set_index("segment")[["impressions", "clicks"]]
    b = s[s.event_date == date1].set_index("segment")[["impressions", "clicks"]]
    j = a.join(b, how="outer", lsuffix="0", rsuffix="1").fillna(0)
    w0 = j.impressions0 / j.impressions0.sum()
    w1 = j.impressions1 / j.impressions1.sum()
    r0 = (j.clicks0 / j.impressions0).fillna(0)
    r1 = (j.clicks1 / j.impressions1).fillna(0)
    # segments absent on one side contribute through mix only
    r1 = r1.where(j.impressions1 > 0, r0)
    r0 = r0.where(j.impressions0 > 0, r1)
    mix = ((w1 - w0) * r0).sum()
    rate = (w0 * (r1 - r0)).sum()
    inter = ((w1 - w0) * (r1 - r0)).sum()
    ctr0 = j.clicks0.sum() / j.impressions0.sum()
    ctr1 = j.clicks1.sum() / j.impressions1.sum()
    by_seg = pd.DataFrame({
        "share0": w0, "share1": w1, "ctr0": r0, "ctr1": r1,
        "mix_contrib": (w1 - w0) * r0, "rate_contrib": w0 * (r1 - r0),
    }).sort_values("rate_contrib")
    return {"dimension": dimension, "date0": str(date0), "date1": str(date1),
            "ctr0": ctr0, "ctr1": ctr1, "delta": ctr1 - ctr0,
            "mix": mix, "rate": rate, "interaction": inter, "by_segment": by_seg}


def creative_cohort_attribution(facts: pd.DataFrame, creative_col: str = "C14") -> pd.DataFrame:
    """Split each day's CTR change into (a) new-creative underperformance and (b) movement of
    established creatives. A creative is "new" on the first day it appears in the data.

    CTR_t = R_t + w_t * (N_t - R_t), with R = established-creative CTR, N = new-creative CTR,
    w = new-creative impression share. Then CTR_t - CTR_{t-1} =
        (R_t - CTR_{t-1})            established-creative movement
      + w_t * (N_t - R_t)            new-creative gap
    which is an exact identity.
    """
    first = facts.groupby(creative_col).event_date.min().rename("first_day")
    f = facts.join(first, on=creative_col)
    f["is_new"] = f.event_date == f.first_day
    g = f.groupby("event_date")
    out = pd.DataFrame({
        "impressions": g.size(),
        "ctr": g.click.mean(),
        "new_share": g.is_new.mean(),
        "ctr_new": f[f.is_new].groupby("event_date").click.mean(),
        "ctr_established": f[~f.is_new].groupby("event_date").click.mean(),
    }).sort_index()
    out["delta_ctr"] = out.ctr.diff()
    out["established_movement"] = out.ctr_established - out.ctr.shift(1)
    out["new_creative_gap"] = (out.new_share * (out.ctr_new - out.ctr_established)).where(out.new_share > 0, 0.0)
    out.loc[out.index[0], ["ctr_established", "established_movement", "new_creative_gap"]] = float("nan")
    return out.reset_index()
