"""Build a self-contained HTML monitoring dashboard from the pipeline outputs."""
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

# validated categorical slots (fixed order) + reserved status color
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CRITICAL, MUTED, INK, INK2, SURFACE = "#d03b3b", "#8a8984", "#0b0b0b", "#52514e", "#fcfcfb"
POLICY_COLOR = {"frozen": BLUE, "frozen+recal": ORANGE, "daily_retrain": AQUA}
POLICY_NAME = {"frozen": "Frozen model", "frozen+recal": "Frozen + daily recalibration",
               "daily_retrain": "Daily retrain"}


def _layout(fig, title, ytitle, yfmt=None, height=320):
    fig.update_layout(
        title={"text": title, "font": {"size": 15, "color": INK}, "x": 0},
        height=height, margin={"l": 60, "r": 20, "t": 50, "b": 40},
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font={"family": "Arial", "color": INK2, "size": 12},
        hovermode="x unified", legend={"orientation": "h", "y": 1.12, "x": 0},
    )
    fig.update_yaxes(title=ytitle, gridcolor="#e6e5e1", zeroline=False, tickformat=yfmt)
    fig.update_xaxes(gridcolor="#f0efec", showline=True, linecolor="#c9c8c2")
    return fig


def _html(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False})


def _table(df, fmt):
    d = df.copy()
    for c, f in fmt.items():
        d[c] = d[c].map(lambda v, f=f: "" if pd.isna(v) else f.format(v))
    return d.to_html(index=False, border=0, classes="tbl")


def build():
    s = json.loads((OUT / "results.json").read_text())
    hourly = pd.read_csv(OUT / "hourly_kpi_scored.csv", parse_dates=["event_hour"])
    cohort = pd.read_csv(OUT / "creative_cohort_attribution.csv")
    health = pd.read_csv(OUT / "model_health.csv")
    drift = pd.read_csv(OUT / "model_drift_psi.csv")
    inj = pd.read_csv(OUT / "injection_test_hourly.csv")

    charts = []

    # 1. hourly CTR vs seasonal expectation
    f = go.Figure()
    f.add_scatter(x=hourly.event_hour, y=hourly.ctr, name="Hourly CTR", line={"color": BLUE, "width": 2})
    f.add_scatter(x=hourly.event_hour, y=hourly.expected_ctr, name="Expected (same hour, prior days)",
                  line={"color": MUTED, "width": 2, "dash": "dot"})
    fl = hourly[hourly.ctr_flag]
    f.add_scatter(x=fl.event_hour, y=fl.ctr, mode="markers", name="⚠ CTR alert (|z| > 3, overdispersion-adjusted)",
                  marker={"color": CRITICAL, "size": 10, "symbol": "triangle-down", "line": {"color": SURFACE, "width": 2}})
    charts.append(_html(_layout(f, "Hourly CTR monitor", "CTR", ".0%")))

    # 2. hourly volume
    f = go.Figure()
    f.add_scatter(x=hourly.event_hour, y=hourly.impressions, name="Hourly impressions (sample)",
                  line={"color": BLUE, "width": 2})
    f.add_scatter(x=hourly.event_hour, y=hourly.expected_impressions, name="Expected (median, prior days)",
                  line={"color": MUTED, "width": 2, "dash": "dot"})
    fl = hourly[hourly.volume_flag]
    f.add_scatter(x=fl.event_hour, y=fl.impressions, mode="markers", name="⚠ Volume alert",
                  marker={"color": CRITICAL, "size": 10, "symbol": "triangle-down", "line": {"color": SURFACE, "width": 2}})
    f.add_annotation(x="2014-10-24 22:00", y=73, text="Oct 24, 19:00-23:00: volume 70-86% below baseline; no CTR alert fired",
                     showarrow=True, ax=-170, ay=-150, arrowcolor=INK2, bgcolor=SURFACE,
                     font={"color": INK, "size": 11})
    charts.append(_html(_layout(f, "Hourly impression volume monitor", "Impressions")))

    # 3. creative cohort attribution
    c = cohort.dropna(subset=["delta_ctr"])
    f = go.Figure()
    f.add_bar(x=c.event_date, y=c.established_movement, name="Established creatives' CTR movement",
              marker={"color": BLUE, "cornerradius": 4}, offsetgroup=0)
    f.add_bar(x=c.event_date, y=c.new_creative_gap, name="New-creative gap (share × CTR shortfall)",
              marker={"color": ORANGE, "cornerradius": 4}, offsetgroup=1)
    f.add_scatter(x=c.event_date, y=c.delta_ctr, mode="markers", name="Total day-over-day CTR change",
                  marker={"color": INK, "size": 9, "symbol": "diamond", "line": {"color": SURFACE, "width": 2}})
    f.update_layout(bargap=0.3, bargroupgap=0.08)
    f.update_xaxes(type="category")
    charts.append(_html(_layout(f, "Why did CTR move? Day-over-day change split by creative cohort",
                                "Change in CTR (pp)", ".1%")))

    # 4-6. model health small multiples, one measure each
    ev = health[health.policy.isin(POLICY_COLOR)]
    for metric, title, fmt in [("auc", "CTR model AUC by scoring day (recalibration is monotone, so its AUC equals frozen)",
                                ".3f"),
                               ("pred_over_actual", "Calibration: predicted CTR ÷ actual CTR (1.0 = calibrated)", ".2f"),
                               ("normalized_entropy", "Normalized entropy (lower is better; 1.0 = base rate)", ".3f")]:
        f = go.Figure()
        for pol, col in POLICY_COLOR.items():
            if metric == "auc" and pol == "frozen+recal":
                continue
            d = ev[ev.policy == pol]
            f.add_scatter(x=d.date, y=d[metric], name=POLICY_NAME[pol], mode="lines+markers",
                          line={"color": col, "width": 2},
                          marker={"size": 9, "line": {"color": SURFACE, "width": 2}})
        if metric == "pred_over_actual":
            f.add_hline(y=1.0, line={"color": MUTED, "dash": "dot", "width": 1})
        f.update_xaxes(type="category")
        charts.append(_html(_layout(f, title, metric.replace("_", " "), fmt, height=290)))

    # 7. drift
    f = go.Figure()
    f.add_bar(x=drift.date, y=drift.unseen_C14_share, name="Impressions on creatives unseen in training",
              marker={"color": BLUE, "cornerradius": 4})
    f.update_xaxes(type="category")
    charts.append(_html(_layout(f, "Creative churn since training cutoff (Oct 27)", "Share of impressions", ".0%",
                                height=280)))

    # 8. detector sensitivity
    f = go.Figure()
    for model, col, nm in [("binomial_only", BLUE, "Binomial-only"),
                           ("overdispersion_adjusted", ORANGE, "Overdispersion-adjusted")]:
        d = inj[inj.model == model]
        f.add_scatter(x=d.ctr_drop, y=d.detection_rate, name=nm, mode="lines+markers",
                      line={"color": col, "width": 2}, marker={"size": 9, "line": {"color": SURFACE, "width": 2}})
    f.update_xaxes(title="Injected one-hour CTR drop", tickformat=".0%")
    charts.append(_html(_layout(f, "Detector sensitivity: one-hour drop detection rate (200 trials each)",
                                "Detection rate", ".0%", height=290)))

    alerts_tbl = hourly[hourly.ctr_flag | hourly.volume_flag][
        ["event_hour", "impressions", "expected_impressions", "z_volume", "ctr", "expected_ctr", "z_ctr"]]
    health_tbl = health[["policy", "date", "n", "actual_ctr", "mean_pred", "pred_over_actual", "auc",
                         "normalized_entropy", "ece", "auc_delta_vs_frozen", "auc_delta_ci_low", "auc_delta_ci_high"]]
    q = s["quality_checks"]
    tiles = [
        ("Impressions (sample)", f"{q['fact_rows']:,}"), ("Hours monitored", f"{q['distinct_hours']}"),
        ("Overall CTR", f"{q['overall_ctr']:.1%}"),
        ("Held-out CTR alerts", f"{s['holdout_ctr_flags_binomial_only']} → {s['holdout_ctr_flags_adjusted']}"),
    ]
    tile_html = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div></div>' for k, v in tiles)

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ad CTR Monitoring and Model Health</title>
<script>{get_plotlyjs()}</script>
<style>body{{font-family:Arial,sans-serif;background:{SURFACE};color:{INK};max-width:1100px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0 0 4px}} p.sub{{color:{INK2};margin:0 0 16px;font-size:13px}}
.tiles{{display:flex;gap:12px;margin:12px 0 20px}} .tile{{flex:1;border:1px solid #e6e5e1;border-radius:8px;padding:12px}}
.tile .v{{font-size:24px;font-weight:bold}} .tile .k{{color:{INK2};font-size:12px}}
.tbl{{border-collapse:collapse;font-size:12px;margin:8px 0 24px}} .tbl td,.tbl th{{padding:4px 8px;border-bottom:1px solid #eee;text-align:right}}
h2{{font-size:16px;margin-top:28px}}</style></head><body>
<h1>Ad CTR Monitoring and Model Health</h1>
<p class="sub">Real Avazu mobile-ad click logs: 200,000-impression random sample, Oct 21-30 2014, 240 hours.
CTR model trained on Oct 21-27 and scored day by day on Oct 28-30.</p>
<div class="tiles">{tile_html}</div>
{''.join(charts)}
<h2>Data tables</h2>
<h3>Alerts</h3>{_table(alerts_tbl, {"expected_impressions": "{:.0f}", "z_volume": "{:.2f}", "ctr": "{:.3f}",
                                     "expected_ctr": "{:.3f}", "z_ctr": "{:.2f}"})}
<h3>Model health</h3>{_table(health_tbl, {c: "{:.4f}" for c in health_tbl.columns[3:]})}
<h3>Creative cohort attribution</h3>{_table(cohort, {c: "{:.4f}" for c in cohort.columns[2:]})}
</body></html>"""
    (OUT / "dashboard.html").write_text(html)


if __name__ == "__main__":
    build()
