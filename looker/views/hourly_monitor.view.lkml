view: hourly_monitor {
  sql_table_name: `ad_analytics.hourly_monitor` ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: CAST(${TABLE}.event_hour AS STRING) ;;
  }

  dimension_group: event {
    type: time
    timeframes: [raw, hour, date, day_of_week, hour_of_day]
    sql: ${TABLE}.event_hour ;;
  }

  dimension: alert_type {
    type: string
    description: "Normal, CTR alert or Volume alert (|z| > 3, overdispersion-adjusted)."
    sql: ${TABLE}.alert_type ;;
  }

  dimension: is_alert {
    type: yesno
    sql: ${alert_type} <> 'Normal' ;;
  }

  dimension: z_ctr {
    type: number
    value_format_name: decimal_2
    sql: ${TABLE}.z_ctr ;;
  }

  dimension: z_volume {
    type: number
    value_format_name: decimal_2
    sql: ${TABLE}.z_volume ;;
  }

  measure: impressions {
    type: sum
    sql: ${TABLE}.impressions ;;
  }

  measure: clicks {
    type: sum
    sql: ${TABLE}.clicks ;;
  }

  measure: ctr {
    label: "CTR"
    description: "Clicks / impressions at the grain of the query (never an average of rates)."
    type: number
    value_format_name: percent_2
    sql: SAFE_DIVIDE(${clicks}, ${impressions}) ;;
  }

  measure: expected_impressions {
    description: "Median impressions for the same hour of day on prior days."
    type: sum
    value_format_name: decimal_0
    sql: ${TABLE}.expected_impressions ;;
  }

  measure: expected_ctr {
    label: "Expected CTR"
    description: "Pooled CTR for the same hour of day on prior days."
    type: average
    value_format_name: percent_2
    sql: ${TABLE}.expected_ctr ;;
  }

  measure: alert_hours {
    type: count
    filters: [is_alert: "yes"]
  }
}
