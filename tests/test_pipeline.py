import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import anomaly
import decompose
import model_health
import warehouse


def _hourly(days=8, imps=1000, ctr=0.17, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        for h in range(24):
            ts = pd.Timestamp("2014-10-21") + pd.Timedelta(days=d, hours=h)
            rows.append({"event_hour": ts, "event_date": ts.date(), "hour_of_day": h,
                         "impressions": imps, "clicks": rng.binomial(imps, ctr)})
    return pd.DataFrame(rows)


def test_anomaly_has_no_lookahead():
    h = _hourly()
    a = anomaly.score_hours(h)
    h2 = h.copy()
    last_day = h2.event_date.max()
    h2.loc[h2.event_date == last_day, "clicks"] = 0  # wreck the future
    b = anomaly.score_hours(h2)
    earlier = a.event_date < last_day
    pd.testing.assert_series_equal(a.loc[earlier, "z_ctr"], b.loc[earlier, "z_ctr"])


def test_anomaly_flags_large_drop_and_volume_collapse():
    h = _hourly()
    i = h.index[-1]
    h.loc[i, "clicks"] = int(h.loc[i, "clicks"] * 0.4)
    h.loc[i - 1, "impressions"] = 100
    s = anomaly.score_hours(h)
    assert s.loc[i, "ctr_flag"]
    assert s.loc[i - 1, "volume_flag"]


def test_first_days_are_not_scored():
    s = anomaly.score_hours(_hourly())
    assert s[s.event_date < date(2014, 10, 24)].z_ctr.isna().all()


def test_mix_rate_decomposition_is_exact():
    seg = pd.DataFrame({
        "event_date": [1, 1, 2, 2], "dimension": "d", "segment": ["a", "b", "a", "b"],
        "impressions": [600, 400, 300, 700], "clicks": [120, 40, 45, 77],
    })
    r = decompose.decompose(seg, 1, 2, "d")
    assert r["mix"] + r["rate"] + r["interaction"] == pytest.approx(r["delta"], abs=1e-12)


def test_creative_cohort_identity():
    rng = np.random.default_rng(3)
    n = 5000
    facts = pd.DataFrame({
        "event_date": [date(2014, 10, 21) + timedelta(days=int(x)) for x in rng.integers(0, 5, n)],
        "C14": rng.integers(0, 40, n), "click": rng.binomial(1, 0.17, n),
    })
    c = decompose.creative_cohort_attribution(facts).dropna(subset=["delta_ctr"])
    np.testing.assert_allclose(c.delta_ctr, c.established_movement + c.new_creative_gap, atol=1e-12)


def test_metric_sanity():
    rng = np.random.default_rng(1)
    x = rng.normal(size=5000)
    assert model_health.psi(x, x) == pytest.approx(0.0, abs=1e-9)
    assert model_health.psi(x, x + 1.0) > 0.25
    y = rng.binomial(1, 0.2, 20000)
    assert model_health.normalized_entropy(y, np.full(len(y), y.mean())) == pytest.approx(1.0)
    p = rng.uniform(0.05, 0.6, 50000)
    yy = rng.binomial(1, p)
    assert model_health.ece(yy, p) < 0.01


def test_warehouse_build_and_quality():
    con = warehouse.build(ROOT / "outputs" / "test_build.duckdb")
    q = warehouse.quality_checks(con)
    assert q["fact_rows"] == q["raw_rows"] == 200000
    assert q["duplicate_ids"] == 0 and q["null_clicks"] == 0 and q["non_binary_clicks"] == 0
    assert q["distinct_hours"] == 240
    assert q["hourly_rollup_matches_fact"] and q["segment_rollup_matches_fact"]
    # traffic-source split is structural: site rows carry one app_category, app rows one site_category
    assert con.execute("SELECT COUNT(DISTINCT app_category) FROM fact_impressions WHERE traffic_source='site'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(DISTINCT site_category) FROM fact_impressions WHERE traffic_source='app'").fetchone()[0] == 1
    con.close()
    (ROOT / "outputs" / "test_build.duckdb").unlink()


def test_game_ab_test_on_real_data():
    import game_retention
    r = game_retention.analyze(pd.read_csv(game_retention.RAW), n_boot=200)
    assert r["players"] == 90189 and r["n_control"] == 44700 and r["n_treatment"] == 45489
    assert r["retention_7"]["control"] == pytest.approx(0.19020, abs=1e-4)
    assert r["retention_7"]["p"] < 0.01 and r["retention_1"]["p"] > 0.05
    assert r["srm_p"] < 0.01  # the real data has a sample-ratio mismatch; keep it visible


def test_two_prop_z_matches_known_value():
    import game_retention
    z, _ = game_retention.two_prop_z(50, 100, 60, 100)
    assert z == pytest.approx(1.4213, abs=1e-3)


def test_ltv_on_real_cdnow():
    import ltv
    d = ltv.load()
    assert len(d) == 69659 and d.customer_id.nunique() == 23570
    curves = ltv.cohort_curves(d)
    assert (curves.ltv_30d <= curves.ltv_365d).all()
    s, _, ch = ltv.predictive_ltv(d)
    assert s["holdout_days"] == 273
    assert s["mae_model"] < s["mae_naive"]
    assert abs(s["freq_corr_gg_assumption"]) < 0.3  # Gamma-Gamma independence assumption holds
    assert ch.actual_value.sum() == pytest.approx(s["total_actual_holdout_revenue"])


def test_marketing_efficiency_from_sec():
    import marketing_efficiency as me
    d = me.load()
    assert len(d) == 147 and (d.sales_marketing_usd > 0).all()
    s, y, k = me.summary(d)
    assert k["publisher_quarters"] == 88
    assert set(s.index) == set(me.PUBLISHERS)
    # every YoY pair must have a real prior-year value for the same quarter
    lookup = d.set_index(["ticker", "year", "q"]).revenue_usd
    prior = [lookup[(t, yr - 1, q)] for t, yr, q in zip(y.ticker, y.year, y.q, strict=True)]
    assert list(y.revenue_usd_ly) == prior
