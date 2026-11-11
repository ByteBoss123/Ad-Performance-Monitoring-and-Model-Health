connection: "ad_analytics_bq"

include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"

label: "Ad Analytics"

explore: hourly_monitor {
  label: "Hourly CTR and Volume Monitor"
  description: "Hourly impressions, clicks and CTR with seasonal baselines and overdispersion-adjusted alerts."
}

explore: creative_attribution {
  label: "CTR Change Attribution"
}

explore: model_health {
  label: "CTR Model Health"
}

explore: game_ab_summary {
  label: "Game A/B Test Retention"
}
