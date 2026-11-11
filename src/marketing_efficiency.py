"""Blended marketing efficiency of public mobile-game publishers from SEC XBRL (real USD).

MER (marketing efficiency ratio) = revenue / sales-and-marketing expense, per company-quarter.
This is blended (all revenue / all marketing), not ad-attributed ROAS.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw_sec" / "sec_revenue_sm_quarterly.csv"
PUBLISHERS = {"PLTK": "Playtika", "MYPS": "Playstudios", "DDI": "DoubleDown Interactive",
              "SCPL": "SciPlay", "ZNGA": "Zynga"}


def load():
    d = pd.read_csv(RAW)
    d["year"] = d.frame.str[2:6].astype(int)
    d["q"] = d.frame.str[-1].astype(int)
    d["mer"] = d.revenue_usd / d.sales_marketing_usd
    d["sm_share"] = d.sales_marketing_usd / d.revenue_usd
    return d


def yoy(d):
    """Same-quarter year-over-year changes (avoids seasonality)."""
    prev = d[["ticker", "year", "q", "revenue_usd", "sales_marketing_usd"]].copy()
    prev["year"] += 1
    m = d.merge(prev, on=["ticker", "year", "q"], suffixes=("", "_ly"))
    m["rev_yoy"] = m.revenue_usd / m.revenue_usd_ly - 1
    m["sm_yoy"] = m.sales_marketing_usd / m.sales_marketing_usd_ly - 1
    m["incremental_rev_per_sm_dollar"] = (m.revenue_usd - m.revenue_usd_ly) / (
        m.sales_marketing_usd - m.sales_marketing_usd_ly)
    return m


def summary(d):
    p = d[d.ticker.isin(PUBLISHERS)]
    rows = []
    for tk, g in p.sort_values(["year", "q"]).groupby("ticker"):
        rows.append({"ticker": tk, "company": PUBLISHERS[tk], "quarters": len(g),
                     "first": g.frame.iloc[0], "last": g.frame.iloc[-1],
                     "mer_median": g.mer.median(), "mer_first4": g.mer.head(4).mean(),
                     "mer_last4": g.mer.tail(4).mean(), "mer_min": g.mer.min(), "mer_max": g.mer.max()})
    s = pd.DataFrame(rows).set_index("ticker")
    y = yoy(p)
    corr = y.rev_yoy.corr(y.sm_yoy)
    spend_up = y[y.sm_yoy > 0.10]
    return s, y, {"publisher_quarters": len(p), "yoy_pairs": len(y), "corr_sm_growth_vs_rev_growth": corr,
                  "quarters_sm_up_10pct": len(spend_up),
                  "median_rev_yoy_when_sm_up_10pct": spend_up.rev_yoy.median(),
                  "median_sm_yoy_when_sm_up_10pct": spend_up.sm_yoy.median()}


if __name__ == "__main__":
    d = load()
    s, y, k = summary(d)
    print(s.round(2).to_string())
    print(k)
    print(y[y.ticker == "PLTK"][["frame", "rev_yoy", "sm_yoy", "mer"]].round(3).to_string())
