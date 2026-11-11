view: model_health {
  sql_table_name: `ad_analytics.model_health` ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: CONCAT(${TABLE}.date, '|', ${TABLE}.policy) ;;
  }

  dimension_group: scoring {
    type: time
    datatype: date
    timeframes: [raw, date]
    sql: ${TABLE}.date ;;
  }

  dimension: policy {
    description: "Frozen model, Frozen + daily recalibration, or Daily retrain."
    type: string
    sql: ${TABLE}.policy ;;
  }

  measure: auc {
    label: "AUC"
    type: average
    value_format_name: decimal_3
    sql: ${TABLE}.auc ;;
  }

  measure: pred_over_actual {
    label: "Predicted / actual CTR"
    description: "1.0 means calibrated."
    type: average
    value_format_name: decimal_3
    sql: ${TABLE}.pred_over_actual ;;
  }

  measure: normalized_entropy {
    type: average
    value_format_name: decimal_3
    sql: ${TABLE}.normalized_entropy ;;
  }

  measure: ece {
    label: "Expected calibration error"
    type: average
    value_format_name: decimal_4
    sql: ${TABLE}.ece ;;
  }
}
