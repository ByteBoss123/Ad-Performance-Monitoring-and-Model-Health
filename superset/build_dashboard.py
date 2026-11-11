"""Create the Superset dashboard through Superset's REST API.

Prereqs: Superset running at $SUPERSET_URL (default http://localhost:8088) with an admin user,
PREVENT_UNSAFE_DB_CONNECTIONS = False (to allow the bundled SQLite file).
Run: python superset/build_dashboard.py
"""
import json
import os
import uuid
from pathlib import Path

import requests

URL = os.environ.get("SUPERSET_URL", "http://localhost:8088")
USER, PWD = os.environ.get("SUPERSET_USER", "admin"), os.environ.get("SUPERSET_PASSWORD", "admin")
DB_FILE = Path(__file__).resolve().parent / "ad_game_analytics.db"

s = requests.Session()


def api(method, path, **kw):
    r = s.request(method, URL + path, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
    return r.json() if r.text else {}


def login():
    tok = api("POST", "/api/v1/security/login",
              json={"username": USER, "password": PWD, "provider": "db", "refresh": True})["access_token"]
    s.headers["Authorization"] = f"Bearer {tok}"
    s.headers["X-CSRFToken"] = api("GET", "/api/v1/security/csrf_token/")["result"]
    s.headers["Referer"] = URL


def metric(sql, label):
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label}


def main():
    login()
    db = api("POST", "/api/v1/database/", json={
        "database_name": "Ad & Game Analytics (SQLite)", "sqlalchemy_uri": f"sqlite:///{DB_FILE}",
        "expose_in_sqllab": True})["id"]
    ds = {}
    for t in ("hourly_monitor", "creative_attribution", "model_health", "model_drift",
              "game_ab_summary"):
        ds[t] = api("POST", "/api/v1/dataset/", json={"database": db, "table_name": t, "schema": "main"})["id"]
    # mark the hourly timestamp as temporal
    # (PUT replaces the whole column list, so send every column back)
    cols = api("GET", f"/api/v1/dataset/{ds['hourly_monitor']}")["result"]["columns"]
    keep = ("id", "column_name", "type", "groupby", "filterable", "is_dttm", "expression", "verbose_name")
    new_cols = [{k: c[k] for k in keep if k in c} | {"is_dttm": c["column_name"] == "event_hour"} for c in cols]
    api("PUT", f"/api/v1/dataset/{ds['hourly_monitor']}",
        json={"columns": new_cols, "main_dttm_col": "event_hour"})

    charts = []

    def chart(name, table, viz, params):
        p = {"datasource": f"{ds[table]}__table", "viz_type": viz, **params}
        cid = api("POST", "/api/v1/chart/", json={
            "slice_name": name, "viz_type": viz, "datasource_id": ds[table], "datasource_type": "table",
            "params": json.dumps(p)})["id"]
        charts.append((cid, name))
        return cid

    chart("Hourly CTR by alert status", "hourly_monitor", "echarts_timeseries_scatter", {
        "x_axis": "event_hour", "time_grain_sqla": "PT1H", "metrics": [metric("AVG(ctr)", "CTR")],
        "groupby": ["alert_type"], "row_limit": 10000, "y_axis_format": ".0%", "markerSize": 6,
        "color_scheme": "supersetColors", "show_legend": True})
    chart("Hourly impressions vs baseline", "hourly_monitor", "echarts_timeseries_line", {
        "x_axis": "event_hour", "time_grain_sqla": "PT1H",
        "metrics": [metric("SUM(impressions)", "Impressions"),
                    metric("AVG(expected_impressions)", "Expected (prior-day median)")],
        "row_limit": 10000, "show_legend": True})
    chart("Why CTR moved: creative cohort attribution", "creative_attribution", "echarts_timeseries_bar", {
        "x_axis": "event_date", "metrics": [metric("SUM(ctr_change)", "CTR change")], "groupby": ["component"],
        "row_limit": 1000, "y_axis_format": ".1%", "show_legend": True})
    chart("CTR model AUC by policy", "model_health", "echarts_timeseries_line", {
        "x_axis": "date", "metrics": [metric("AVG(auc)", "AUC")], "groupby": ["policy"], "row_limit": 1000,
        "y_axis_format": ".3f", "show_legend": True, "markerEnabled": True, "markerSize": 8,
        "truncateYAxis": True, "y_axis_bounds": [0.69, 0.745]})
    chart("Calibration: predicted / actual CTR", "model_health", "echarts_timeseries_line", {
        "x_axis": "date", "metrics": [metric("AVG(pred_over_actual)", "Pred / actual")], "groupby": ["policy"],
        "row_limit": 1000, "y_axis_format": ".2f", "show_legend": True, "markerEnabled": True, "markerSize": 8,
        "truncateYAxis": True, "y_axis_bounds": [0.92, 1.04]})
    chart("Game A/B test: D1 and D7 retention", "game_ab_summary", "echarts_timeseries_bar", {
        "x_axis": "metric", "metrics": [metric("AVG(retention)", "Retention")], "groupby": ["variant"],
        "row_limit": 100, "y_axis_format": ".1%", "show_legend": True, "show_value": True})
    chart("Game A/B test: results table", "game_ab_summary", "table", {
        "query_mode": "raw", "all_columns": ["metric", "variant", "players", "retention", "ci_low", "ci_high",
                                             "diff_pp", "p_value"], "row_limit": 100,
        "column_config": {"retention": {"d3NumberFormat": ".2%"}, "ci_low": {"d3NumberFormat": ".2%"},
                          "ci_high": {"d3NumberFormat": ".2%"}, "diff_pp": {"d3NumberFormat": ".2f"},
                          "p_value": {"d3NumberFormat": ".4f"}}})

    # 2 charts per row, 12-column grid
    pos = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
           "HEADER_ID": {"id": "HEADER_ID", "type": "HEADER",
                         "meta": {"text": "Ad CTR Monitoring, Model Health and Game Retention"}}}
    layout = [[0], [1], [2, 3], [4, 5], [6]]
    for row in layout:
        rid = f"ROW-{uuid.uuid4().hex[:8]}"
        pos["GRID_ID"]["children"].append(rid)
        pos[rid] = {"type": "ROW", "id": rid, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                    "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for i in row:
            cid, name = charts[i]
            k = f"CHART-{uuid.uuid4().hex[:8]}"
            pos[rid]["children"].append(k)
            pos[k] = {"type": "CHART", "id": k, "children": [], "parents": ["ROOT_ID", "GRID_ID", rid],
                      "meta": {"chartId": cid, "sliceName": name, "width": 12 // len(row), "height": 55}}
    dash = api("POST", "/api/v1/dashboard/", json={
        "dashboard_title": "Ad CTR Monitoring, Model Health and Game Retention", "slug": "ad-game-analytics",
        "published": True, "position_json": json.dumps(pos)})["id"]
    for cid, _ in charts:
        api("PUT", f"/api/v1/chart/{cid}", json={"dashboards": [dash]})
    print(f"{URL}/superset/dashboard/ad-game-analytics/")


if __name__ == "__main__":
    main()
