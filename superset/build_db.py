"""Build the SQLite file Superset reads, from the pipeline outputs."""
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "superset" / "ad_game_analytics.db"


def main():
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    h = pd.read_csv(ROOT / "tableau" / "Data" / "hourly_monitor.csv", parse_dates=["event_hour"])
    h.to_sql("hourly_monitor", con, index=False)
    for t in ("creative_attribution", "model_health", "model_drift"):
        pd.read_csv(ROOT / "tableau" / "Data" / f"{t}.csv").to_sql(t, con, index=False)
    g = json.loads((ROOT / "outputs" / "game_ab_test.json").read_text())
    rows = []
    for m, label in (("retention_1", "D1 retention"), ("retention_7", "D7 retention")):
        r = g[m]
        for v, n, key, ci in (("gate_30 (control)", g["n_control"], "control", "control_ci"),
                              ("gate_40 (treatment)", g["n_treatment"], "treatment", "treatment_ci")):
            rows.append({"metric": label, "variant": v, "players": n, "retention": r[key], "ci_low": r[ci][0],
                         "ci_high": r[ci][1], "diff_pp": r["diff_pp"], "p_value": r["p"]})
    pd.DataFrame(rows).round(5).to_sql("game_ab_summary", con, index=False)
    con.close()


if __name__ == "__main__":
    main()
