- dashboard: ad_monitoring
  title: Ad CTR Monitoring, Model Health and Game Retention
  layout: newspaper
  preferred_viewer: dashboards-next
  elements:
  - name: hourly_ctr
    title: Hourly CTR vs expected
    model: ad_analytics
    explore: hourly_monitor
    type: looker_line
    fields: [hourly_monitor.event_hour, hourly_monitor.ctr, hourly_monitor.expected_ctr]
    sorts: [hourly_monitor.event_hour]
    row: 0
    col: 0
    width: 24
    height: 7
  - name: hourly_volume
    title: Hourly impressions vs baseline
    model: ad_analytics
    explore: hourly_monitor
    type: looker_line
    fields: [hourly_monitor.event_hour, hourly_monitor.impressions, hourly_monitor.expected_impressions]
    sorts: [hourly_monitor.event_hour]
    row: 7
    col: 0
    width: 24
    height: 7
  - name: alerts
    title: Monitoring alerts
    model: ad_analytics
    explore: hourly_monitor
    type: looker_grid
    fields: [hourly_monitor.event_hour, hourly_monitor.alert_type, hourly_monitor.z_ctr, hourly_monitor.z_volume,
      hourly_monitor.impressions, hourly_monitor.ctr]
    filters:
      hourly_monitor.is_alert: 'Yes'
    sorts: [hourly_monitor.event_hour]
    row: 14
    col: 0
    width: 24
    height: 6
  - name: attribution
    title: Why CTR moved (creative cohort attribution)
    model: ad_analytics
    explore: creative_attribution
    type: looker_column
    fields: [creative_attribution.event_date, creative_attribution.component, creative_attribution.ctr_change]
    pivots: [creative_attribution.component]
    sorts: [creative_attribution.event_date]
    row: 20
    col: 0
    width: 12
    height: 7
  - name: auc
    title: CTR model AUC by policy
    model: ad_analytics
    explore: model_health
    type: looker_line
    fields: [model_health.scoring_date, model_health.policy, model_health.auc]
    pivots: [model_health.policy]
    sorts: [model_health.scoring_date]
    row: 20
    col: 12
    width: 12
    height: 7
  - name: calibration
    title: Calibration (predicted / actual CTR)
    model: ad_analytics
    explore: model_health
    type: looker_line
    fields: [model_health.scoring_date, model_health.policy, model_health.pred_over_actual]
    pivots: [model_health.policy]
    sorts: [model_health.scoring_date]
    row: 27
    col: 0
    width: 12
    height: 7
  - name: retention
    title: Game A/B test D1 and D7 retention
    model: ad_analytics
    explore: game_ab_summary
    type: looker_column
    fields: [game_ab_summary.metric, game_ab_summary.variant, game_ab_summary.retention]
    pivots: [game_ab_summary.variant]
    sorts: [game_ab_summary.metric]
    row: 27
    col: 12
    width: 12
    height: 7
