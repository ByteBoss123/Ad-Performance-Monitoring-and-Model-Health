#!/bin/bash
exec > /var/log/mbsetup.log 2>&1
set -x
dnf install -y java-21-amazon-corretto-headless python3 git
git clone --depth 1 https://github.com/ByteBoss123/Ad-Performance-Monitoring-and-Model-Health /opt/repo
mkdir -p /opt/data && cp /opt/repo/tableau/Data/hourly_monitor.csv /opt/repo/tableau/Data/creative_attribution.csv /opt/repo/tableau/Data/model_health.csv /opt/data/
cat > /opt/mkgame.py <<'PYEOF'
import csv, json
g = json.load(open("/opt/repo/outputs/game_ab_test.json"))
w = csv.writer(open("/opt/data/game_ab_summary.csv", "w"))
w.writerow(["metric", "variant", "players", "retention"])
for m, label in (("retention_1", "D1 retention"), ("retention_7", "D7 retention")):
    w.writerow([label, "gate_30 (control)", g["n_control"], round(g[m]["control"], 5)])
    w.writerow([label, "gate_40 (treatment)", g["n_treatment"], round(g[m]["treatment"], 5)])
PYEOF
python3 /opt/mkgame.py
cat > /opt/setup.py <<'PYEOF'
"""Runs on the EC2 instance: build SQLite from the project CSVs, start Metabase, build the dashboard via API,
render each card to PNG, export definitions, and upload everything to S3."""
import csv, json, os, sqlite3, subprocess, time, urllib.request, urllib.error
B, P = "amarg-cpa-emr-2026", "metabase-run/"
H = "http://localhost:3000"
log = []

def s3(cmd):
    return subprocess.run("aws s3 " + cmd, shell=True, capture_output=True, text=True)

def note(m):
    log.append(f"{time.strftime('%H:%M:%S')} {m}")
    open("/opt/run.log", "w").write("\n".join(log)); s3(f"cp /opt/run.log s3://{B}/{P}out/run.log")

def api(method, path, body=None, sess=None, raw=False):
    req = urllib.request.Request(H + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"X-Metabase-Session": sess} if sess else {})})
    r = urllib.request.urlopen(req, timeout=120).read()
    return r if raw else (json.loads(r) if r else {})

# 1. SQLite from the CSVs
db = "/opt/ad_game_analytics.sqlite"
con = sqlite3.connect(db)
for f in os.listdir("/opt/data"):
    t = f[:-4]
    rows = list(csv.reader(open(f"/opt/data/{f}")))
    hdr, data = rows[0], rows[1:]
    def typ(i):
        try:
            [float(r[i]) for r in data if r[i] != ""]; return "REAL"
        except ValueError:
            return "TEXT"
    con.execute(f'CREATE TABLE "{t}" ({", ".join(f"{h} {typ(i)}" for i, h in enumerate(hdr))})')
    con.executemany(f'INSERT INTO "{t}" VALUES ({",".join("?"*len(hdr))})', [[None if v == "" else v for v in r] for r in data])
    note(f"table {t}: {len(data)} rows")
con.commit(); con.close()

# 2. start Metabase
proc = subprocess.Popen("cd /opt && MB_DB_FILE=/opt/mbmeta java -jar metabase.jar > /opt/mb.log 2>&1", shell=True)
for _ in range(120):
    try:
        if api("GET", "/api/health").get("status") == "ok": break
    except Exception:
        pass
    time.sleep(5)
note("metabase healthy, version " + api("GET", "/api/session/properties").get("version", {}).get("tag", "?"))
props = api("GET", "/api/session/properties")
sess = api("POST", "/api/setup", {"token": props["setup-token"], "user": {"first_name": "Portfolio", "last_name": "Admin",
           "email": "admin@example.org", "password": "Portfolio-demo-2026!", "site_name": "Ad Analytics"},
           "prefs": {"site_name": "Ad Analytics", "allow_tracking": False}})["id"]
dbid = api("POST", "/api/database", {"engine": "sqlite", "name": "Ad & Game Analytics", "details": {"db": db}}, sess)["id"]
time.sleep(20)
note(f"database {dbid} added")

CARDS = [
 ("Hourly CTR vs expected (prior-day same hour)", "line",
  "SELECT event_hour, ctr AS \"CTR\", expected_ctr AS \"Expected CTR\" FROM hourly_monitor ORDER BY event_hour",
  {"graph.dimensions": ["event_hour"], "graph.metrics": ["CTR", "Expected CTR"]}),
 ("Hourly impressions vs baseline", "line",
  "SELECT event_hour, impressions AS \"Impressions\", expected_impressions AS \"Expected\" FROM hourly_monitor ORDER BY event_hour",
  {"graph.dimensions": ["event_hour"], "graph.metrics": ["Impressions", "Expected"]}),
 ("Monitoring alerts (overdispersion-adjusted)", "table",
  "SELECT event_hour, alert_type, impressions, ROUND(expected_impressions,0) AS expected_impressions, ROUND(ctr,4) AS ctr, "
  "ROUND(expected_ctr,4) AS expected_ctr, ROUND(z_ctr,2) AS z_ctr, ROUND(z_volume,2) AS z_volume FROM hourly_monitor "
  "WHERE alert_type <> 'Normal' ORDER BY event_hour", {}),
 ("Why CTR moved: creative cohort attribution", "bar",
  "SELECT event_date, component, ctr_change FROM creative_attribution ORDER BY event_date",
  {"graph.dimensions": ["event_date", "component"], "graph.metrics": ["ctr_change"]}),
 ("CTR model AUC by retraining policy", "line",
  "SELECT date, policy, auc FROM model_health WHERE policy <> 'Frozen + daily recalibration' ORDER BY date",
  {"graph.dimensions": ["date", "policy"], "graph.metrics": ["auc"], "graph.y_axis.auto_range": False,
   "graph.y_axis.min": 0.69, "graph.y_axis.max": 0.745}),
 ("Calibration: predicted / actual CTR", "line",
  "SELECT date, policy, pred_over_actual FROM model_health ORDER BY date",
  {"graph.dimensions": ["date", "policy"], "graph.metrics": ["pred_over_actual"], "graph.y_axis.auto_range": False,
   "graph.y_axis.min": 0.92, "graph.y_axis.max": 1.04}),
 ("Game A/B test: D1 and D7 retention", "bar",
  "SELECT metric, variant, retention FROM game_ab_summary ORDER BY metric, variant",
  {"graph.dimensions": ["metric", "variant"], "graph.metrics": ["retention"], "graph.show_values": True}),
]
ids = []
for name, display, sql, viz in CARDS:
    c = api("POST", "/api/card", {"name": name, "display": display, "visualization_settings": viz,
                                   "dataset_query": {"type": "native", "database": dbid, "native": {"query": sql}}}, sess)
    ids.append(c["id"])
    res = api("POST", f"/api/card/{c['id']}/query", {}, sess)
    note(f"card {c['id']} '{name}': status={res.get('status')} rows={res.get('row_count')}")
dash = api("POST", "/api/dashboard", {"name": "Ad CTR Monitoring, Model Health and Game Retention"}, sess)["id"]
layout = [(0, 0, 24, 6), (0, 6, 24, 6), (0, 12, 24, 6), (0, 18, 12, 6), (12, 18, 12, 6), (0, 24, 12, 6), (12, 24, 12, 6)]
dcs = [{"id": -(i + 1), "card_id": cid, "col": x, "row": y, "size_x": w, "size_y": h}
       for i, (cid, (x, y, w, h)) in enumerate(zip(ids, layout))]
api("PUT", f"/api/dashboard/{dash}", {"dashcards": dcs}, sess)
note(f"dashboard {dash} with {len(dcs)} cards")

os.makedirs("/opt/out", exist_ok=True)
for cid in ids:
    try:
        png = api("GET", f"/api/pulse/preview_card_png/{cid}", sess=sess, raw=True)
        open(f"/opt/out/card_{cid}.png", "wb").write(png)
        open(f"/opt/out/card_{cid}.png.hex", "w").write(png.hex())
        note(f"png card {cid}: {len(png)} bytes")
    except Exception as ex:
        note(f"png card {cid} failed: {ex!r}")
export = {"dashboard": api("GET", f"/api/dashboard/{dash}", sess=sess),
          "cards": [api("GET", f"/api/card/{cid}", sess=sess) for cid in ids]}
json.dump(export, open("/opt/out/metabase_dashboard_export.json", "w"), indent=1, default=str)
s3(f"cp /opt/out s3://{B}/{P}out/ --recursive")
note("DONE")
s3(f"cp /opt/run.log s3://{B}/{P}out/run.log")
subprocess.run("shutdown -h now", shell=True)
PYEOF
curl -sSL -o /opt/metabase.jar https://downloads.metabase.com/latest/metabase.jar; ls -la /opt/metabase.jar
python3 /opt/setup.py || { tail -80 /opt/mb.log > /opt/mbtail.log; aws s3 cp /opt/mbtail.log s3://amarg-cpa-emr-2026/metabase-run/out/mbtail.log; }
aws s3 cp /var/log/mbsetup.log s3://amarg-cpa-emr-2026/metabase-run/out/mbsetup.log
shutdown -h now
