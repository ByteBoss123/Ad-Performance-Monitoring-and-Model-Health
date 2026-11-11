"""End-to-end run: warehouse -> KPI monitoring -> KPI decomposition -> model health -> outputs."""
import json
import sys
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

import anomaly
import decompose
import game_retention
import ltv
import marketing_efficiency
import model_health
import report
import warehouse

OUT = ROOT / "outputs"


def main():
    con = warehouse.build()
    checks = warehouse.quality_checks(con)

    hourly = con.execute("SELECT * FROM kpi_hourly ORDER BY event_hour").df()
    daily = con.execute("SELECT * FROM kpi_daily ORDER BY event_date").df()
    seg = con.execute("SELECT * FROM kpi_daily_segment").df()
    hourly["event_date"] = pd.to_datetime(hourly.event_date).dt.date
    daily["event_date"] = pd.to_datetime(daily.event_date).dt.date
    seg["event_date"] = pd.to_datetime(seg.event_date).dt.date

    # 1) binomial-only scoring; 2) fit dispersion on Oct 24-26 (first scorable days);
    # 3) rescore with it and compare false-alert load out of sample on Oct 27-30.
    raw = anomaly.score_hours(hourly)
    calib = [pd.Timestamp(x).date() for x in ("2014-10-24", "2014-10-25", "2014-10-26")]
    phi, vol_scale = anomaly.fit_dispersion(raw, calib)
    scored = anomaly.score_hours(hourly, phi=phi, vol_scale=vol_scale)
    scored["z_ctr_binomial_only"] = raw.z_ctr
    scored["z_volume_unscaled"] = raw.z_volume
    scored["ctr_flag_binomial_only"] = raw.ctr_flag
    scored["volume_flag_unscaled"] = raw.volume_flag
    holdout = scored.event_date > calib[-1]
    inj_h = pd.concat([anomaly.injection_test(hourly).assign(model="binomial_only"),
                       anomaly.injection_test(hourly, phi=phi).assign(model="overdispersion_adjusted")])

    # decompose every day-over-day move on every dimension
    dates = sorted(daily.event_date)
    decomp_rows, seg_detail = [], []
    for d0, d1 in pairwise(dates):
        for dim in seg.dimension.unique():
            r = decompose.decompose(seg, d0, d1, dim)
            seg_detail.append(r["by_segment"].assign(dimension=dim, date0=str(d0), date1=str(d1)))
            decomp_rows.append({k: v for k, v in r.items() if k != "by_segment"})
    decomp = pd.DataFrame(decomp_rows)
    decomp["mix_share_of_delta"] = decomp["mix"] / decomp["delta"]

    facts = con.execute("SELECT * FROM fact_impressions").df()
    facts["event_hour"] = pd.to_datetime(facts.event_hour)
    facts["event_date"] = pd.to_datetime(facts.event_date).dt.date
    health, drift, importance = model_health.evaluate(facts)
    cohort = decompose.creative_cohort_attribution(facts)
    cohort.to_csv(OUT / "creative_cohort_attribution.csv", index=False)

    OUT.mkdir(exist_ok=True)
    scored.to_csv(OUT / "hourly_kpi_scored.csv", index=False)
    daily.to_csv(OUT / "daily_kpi.csv", index=False)
    seg.to_csv(OUT / "daily_segment_kpi.csv", index=False)
    inj_h.to_csv(OUT / "injection_test_hourly.csv", index=False)
    decomp.to_csv(OUT / "ctr_decomposition.csv", index=False)
    pd.concat(seg_detail).to_csv(OUT / "ctr_decomposition_by_segment.csv")
    health.to_csv(OUT / "model_health.csv", index=False)
    drift.to_csv(OUT / "model_drift_psi.csv", index=False)
    importance.to_csv(OUT / "feature_importance_gain.csv", header=["gain"])

    summary = {
        "quality_checks": checks,
        "scorable_hours": int(scored.z_ctr.notna().sum()),
        "phi_ctr": phi, "volume_scale": vol_scale,
        "holdout_hours": int((holdout & scored.z_ctr.notna()).sum()),
        "holdout_ctr_flags_binomial_only": int(scored[holdout].ctr_flag_binomial_only.sum()),
        "holdout_ctr_flags_adjusted": int(scored[holdout].ctr_flag.sum()),
        "holdout_volume_flags_unscaled": int(scored[holdout].volume_flag_unscaled.sum()),
        "holdout_volume_flags_adjusted": int(scored[holdout].volume_flag.sum()),
        "all_ctr_flags_binomial_only": int(scored.ctr_flag_binomial_only.sum()),
        "ctr_flags": scored[scored.ctr_flag][["event_hour", "impressions", "ctr", "expected_ctr", "z_ctr"]]
            .astype(str).to_dict("records"),
        "volume_flags": scored[scored.volume_flag][["event_hour", "impressions", "expected_impressions", "z_volume"]]
            .astype(str).to_dict("records"),
    }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2, default=str))
    game = game_retention.analyze(pd.read_csv(game_retention.RAW))
    (OUT / "game_ab_test.json").write_text(json.dumps(game, indent=2, default=float))
    cd = ltv.load()
    ltv.cohort_curves(cd).to_csv(OUT / "ltv_cohort_curves.csv")
    ltv.arpdau(cd).to_csv(OUT / "ltv_daily_arppu.csv")
    ltv_summary, ltv_dec, _ = ltv.predictive_ltv(cd)
    ltv_dec.to_csv(OUT / "ltv_deciles.csv")
    (OUT / "ltv_summary.json").write_text(json.dumps(ltv_summary, indent=2))
    me_sum, me_yoy, me_k = marketing_efficiency.summary(marketing_efficiency.load())
    me_sum.to_csv(OUT / "marketing_efficiency_by_publisher.csv")
    me_yoy.to_csv(OUT / "marketing_efficiency_yoy.csv", index=False)
    (OUT / "marketing_efficiency_summary.json").write_text(json.dumps(me_k, indent=2, default=float))
    report.build()
    print(json.dumps(checks, indent=1, default=str))
    print(scored.describe()[["z_ctr", "z_volume"]])
    print("CTR flags:", int(scored.ctr_flag.sum()), " volume flags:", int(scored.volume_flag.sum()))
    print({k: v for k, v in summary.items() if k not in ("ctr_flags", "volume_flags", "quality_checks")})
    print(pd.DataFrame(summary["ctr_flags"]).to_string()); print(pd.DataFrame(summary["volume_flags"]).to_string())
    print(inj_h)
    print(daily)
    print(health.round(4).to_string())
    print(drift.round(3).to_string())
    print(importance.head(10))
    print(cohort.round(4).to_string())


if __name__ == "__main__":
    main()
