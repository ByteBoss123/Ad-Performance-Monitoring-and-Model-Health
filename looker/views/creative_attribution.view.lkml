view: creative_attribution {
  sql_table_name: `ad_analytics.creative_attribution` ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: CONCAT(${TABLE}.event_date, '|', ${TABLE}.component) ;;
  }

  dimension_group: event {
    type: time
    datatype: date
    timeframes: [raw, date]
    sql: ${TABLE}.event_date ;;
  }

  dimension: component {
    description: "Established creatives movement or new-creative gap. The two sum exactly to the day-over-day CTR change."
    type: string
    sql: ${TABLE}.component ;;
  }

  measure: ctr_change {
    label: "CTR change"
    type: sum
    value_format_name: percent_2
    sql: ${TABLE}.ctr_change ;;
  }
}
