-- KPI layer over fact_impressions (one row per ad impression).
-- All rates are computed as SUM(clicks)/COUNT(*) at the reported grain, never as averages of rates.

CREATE OR REPLACE VIEW kpi_hourly AS
SELECT
    event_hour,
    CAST(event_hour AS DATE)            AS event_date,
    EXTRACT(hour FROM event_hour)       AS hour_of_day,
    COUNT(*)                            AS impressions,
    SUM(click)                          AS clicks,
    SUM(click) * 1.0 / COUNT(*)         AS ctr
FROM fact_impressions
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW kpi_daily AS
SELECT
    event_date,
    COUNT(*)                            AS impressions,
    SUM(click)                          AS clicks,
    SUM(click) * 1.0 / COUNT(*)         AS ctr,
    -- 95% Wilson interval for daily CTR
    (SUM(click) * 1.0 / COUNT(*) + 1.96^2 / (2 * COUNT(*))
      - 1.96 * SQRT((SUM(click) * 1.0 / COUNT(*)) * (1 - SUM(click) * 1.0 / COUNT(*)) / COUNT(*)
                    + 1.96^2 / (4 * COUNT(*)^2)))
      / (1 + 1.96^2 / COUNT(*))         AS ctr_ci_low,
    (SUM(click) * 1.0 / COUNT(*) + 1.96^2 / (2 * COUNT(*))
      + 1.96 * SQRT((SUM(click) * 1.0 / COUNT(*)) * (1 - SUM(click) * 1.0 / COUNT(*)) / COUNT(*)
                    + 1.96^2 / (4 * COUNT(*)^2)))
      / (1 + 1.96^2 / COUNT(*))         AS ctr_ci_high
FROM fact_impressions
GROUP BY 1;

-- Long segment table: one row per (date, dimension, segment value).
CREATE OR REPLACE VIEW kpi_daily_segment AS
WITH long AS (
    SELECT event_date, 'traffic_source'  AS dimension, traffic_source              AS segment, click FROM fact_impressions
    UNION ALL
    SELECT event_date, 'device_type',      CAST(device_type AS VARCHAR),      click FROM fact_impressions
    UNION ALL
    SELECT event_date, 'banner_pos',       CAST(banner_pos AS VARCHAR),       click FROM fact_impressions
    UNION ALL
    SELECT event_date, 'device_conn_type', CAST(device_conn_type AS VARCHAR), click FROM fact_impressions
    UNION ALL
    SELECT event_date, 'site_category',    CAST(site_category AS VARCHAR),    click FROM fact_impressions
    UNION ALL
    SELECT event_date, 'app_category',     CAST(app_category AS VARCHAR),     click FROM fact_impressions
)
SELECT
    event_date,
    dimension,
    segment,
    COUNT(*)                    AS impressions,
    SUM(click)                  AS clicks,
    SUM(click) * 1.0 / COUNT(*) AS ctr
FROM long
GROUP BY 1, 2, 3;
