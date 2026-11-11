#!/bin/bash
# Load the project tables into BigQuery dataset ad_analytics (used by connection "ad_analytics_bq").
set -euo pipefail
cd "$(dirname "$0")/.."
bq mk --dataset --location=US ad_analytics || true
bq load --replace --autodetect --source_format=CSV ad_analytics.hourly_monitor tableau/Data/hourly_monitor.csv
bq load --replace --autodetect --source_format=CSV ad_analytics.creative_attribution tableau/Data/creative_attribution.csv
bq load --replace --autodetect --source_format=CSV ad_analytics.model_health tableau/Data/model_health.csv
python3 - <<'PY'
import csv, json
g = json.load(open("outputs/game_ab_test.json"))
with open("/tmp/game_ab_summary.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["metric", "variant", "players", "retention"])
    for m, label in (("retention_1", "D1 retention"), ("retention_7", "D7 retention")):
        w.writerow([label, "gate_30 (control)", g["n_control"], g[m]["control"]])
        w.writerow([label, "gate_40 (treatment)", g["n_treatment"], g[m]["treatment"]])
PY
bq load --replace --autodetect --source_format=CSV ad_analytics.game_ab_summary /tmp/game_ab_summary.csv
