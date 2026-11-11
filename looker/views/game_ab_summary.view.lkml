view: game_ab_summary {
  sql_table_name: `ad_analytics.game_ab_summary` ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: CONCAT(${TABLE}.metric, '|', ${TABLE}.variant) ;;
  }

  dimension: metric {
    description: "D1 retention or D7 retention."
    type: string
    sql: ${TABLE}.metric ;;
  }

  dimension: variant {
    type: string
    sql: ${TABLE}.variant ;;
  }

  measure: players {
    type: sum
    sql: ${TABLE}.players ;;
  }

  measure: retention {
    type: average
    value_format_name: percent_2
    sql: ${TABLE}.retention ;;
  }
}
