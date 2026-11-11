"""Load the raw Avazu sample into a DuckDB warehouse and build the KPI views."""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "outputs" / "ad_metrics.duckdb"


def build(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    files = [str(RAW / f"{s}_data.csv") for s in ("train", "val", "test")]
    con.execute(
        "CREATE TABLE raw_impressions AS SELECT * FROM read_csv_auto(?, header=true)",
        [files],
    )
    # In Avazu, site-served impressions carry one placeholder app_id; the label-encoded
    # mirror keeps that as the single most frequent app_id value. Check it is dominant
    # and that those rows never carry a non-placeholder app_category.
    modal_app = con.execute(
        "SELECT app_id, COUNT(*) n FROM raw_impressions GROUP BY 1 ORDER BY n DESC LIMIT 1"
    ).fetchone()[0]
    con.execute(
        f"""
        CREATE TABLE fact_impressions AS
        SELECT DISTINCT ON (id)
            id,
            CAST(hour AS TIMESTAMP)               AS event_hour,
            CAST(CAST(hour AS TIMESTAMP) AS DATE) AS event_date,
            click,
            C1, banner_pos, site_id, site_domain, site_category,
            app_id, app_domain, app_category,
            device_id, device_ip, device_model, device_type, device_conn_type,
            C14, C15, C16, C17, C18, C19, C20, C21,
            CASE WHEN app_id = {modal_app} THEN 'site' ELSE 'app' END AS traffic_source
        FROM raw_impressions
        """
    )
    con.execute((ROOT / "sql" / "kpi_views.sql").read_text())
    return con


def quality_checks(con: duckdb.DuckDBPyConnection) -> dict:
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "raw_rows": q("SELECT COUNT(*) FROM raw_impressions"),
        "fact_rows": q("SELECT COUNT(*) FROM fact_impressions"),
        "duplicate_ids": q("SELECT COUNT(*) - COUNT(DISTINCT id) FROM raw_impressions"),
        "null_clicks": q("SELECT COUNT(*) FROM fact_impressions WHERE click IS NULL"),
        "non_binary_clicks": q("SELECT COUNT(*) FROM fact_impressions WHERE click NOT IN (0,1)"),
        "distinct_hours": q("SELECT COUNT(DISTINCT event_hour) FROM fact_impressions"),
        "first_hour": str(q("SELECT MIN(event_hour) FROM fact_impressions")),
        "last_hour": str(q("SELECT MAX(event_hour) FROM fact_impressions")),
        "overall_ctr": q("SELECT AVG(click) FROM fact_impressions"),
        "site_share": q("SELECT AVG(CASE WHEN traffic_source='site' THEN 1 ELSE 0 END) FROM fact_impressions"),
        "hourly_rollup_matches_fact": q(
            "SELECT (SELECT SUM(impressions) FROM kpi_hourly) = (SELECT COUNT(*) FROM fact_impressions)"
        ),
        "segment_rollup_matches_fact": q(
            "SELECT COUNT(*) = 0 FROM (SELECT dimension, SUM(impressions) s FROM kpi_daily_segment "
            "GROUP BY 1 HAVING s <> (SELECT COUNT(*) FROM fact_impressions))"
        ),
    }
