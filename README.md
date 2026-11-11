# Ad CTR Monitoring and Model Health

KPI monitoring, root-cause analysis and CTR-model evaluation on **real mobile-ad click logs** (Avazu).
The goal: when ad performance moves, tell whether it is noise, a traffic problem, a change in
the traffic mix, or the model going stale.

`python run_pipeline.py` rebuilds everything (≈35 s on CPU). `pytest tests` runs 11 tests.

## Data

- **Source:** 200,000 impressions sampled from the Kaggle Avazu CTR training log, taken from the public
  GitHub repo [ekaksher/FedCTR](https://github.com/ekaksher/FedCTR) (`FL/datasets/{train,val,test}_data.csv`,
  commit `4975377`). SHA-256 hashes are in `data/raw/SHA256SUMS`.
- **Coverage:** all 240 hours from 2014-10-21 00:00 to 2014-10-30 23:00, 16.8% CTR, 0 duplicate IDs, 0 null or non-binary labels.
- **Limitations, stated up front:**
  - The mirror label-encodes the ID fields and min-max scales C14-C21, so segments show as codes rather than names.
  - This is a sample, not the full log, so hourly counts (~830 impressions) are noisy. That noise is the reason for the overdispersion work below.
  - "New creative" means first seen *in this sample*, so a creative that ran earlier but wasn't sampled will count as new.
- **Traffic source:** site and app traffic are split on the placeholder `app_id` that site impressions carry. This is checked structurally: every site row has exactly one `app_category`, and every app row has exactly one `site_category`. Site traffic is 63.9% of impressions.

## Pipeline

| Step | What | Where |
|---|---|---|
| Warehouse | DuckDB fact table + SQL KPI views (hourly, daily with Wilson 95% CIs, daily by 6 segment dimensions); rollups reconciled to the fact table | `src/warehouse.py`, `sql/kpi_views.sql` |
| Anomaly detection | Hour-of-day seasonal baseline using only *earlier* days. CTR: binomial z-score with an overdispersion factor. Volume: robust log z-score. | `src/anomaly.py` |
| Root cause | Exact mix/rate/interaction decomposition of every day-over-day CTR move on 6 dimensions; creative-cohort attribution | `src/decompose.py` |
| Model health | LightGBM CTR model trained Oct 21-27, scored live on Oct 28-30 under 3 policies; AUC, normalized entropy, calibration ratio, ECE, calibration slope, score/feature PSI, paired bootstrap AUC CIs | `src/model_health.py` |
| Dashboard | Self-contained HTML monitor with data tables | `outputs/dashboard.html` |

## Findings

**1. A traffic outage that CTR monitoring would have missed.** On Oct 24, 19:00-23:00, hourly impressions
ran 70-86% below the same-hour baseline (73-159 vs 431-702 expected). The volume monitor flagged all five hours
(z down to -18.1). The CTR monitor raised no alert in that window, so volume and rate have to be watched separately.

**2. The naive alert threshold is mostly noise, so it was recalibrated out of sample.** Real hourly CTR varies more
than a binomial model assumes. I fit an overdispersion factor on Oct 24-26 (φ = 1.74, robust MAD estimate)
and applied it to the next 96 hours (Oct 27-30). CTR alerts dropped from **10 to 3** and volume alerts from 5 to 2,
and the outage was still caught. The cost is measured, not hidden: in a 200-trial injection test, detection of a
one-hour 30% CTR drop fell from 62.5% to 33.0% (50% drops: 97.0% to 82.5%). At this sample's hourly volume,
only large hourly drops are reliably detectable.

**3. The two big CTR drops came from new creatives, not traffic mix.** CTR fell 1.95pp on Oct 22 and 2.52pp on Oct 28.
A mix/rate decomposition by traffic source puts only 7% and 12% of those moves on mix; the drop happened *inside* site
traffic (site CTR 19.9%→17.1% and 21.8%→18.4%, app CTR roughly flat). Both days had a wave of creatives (C14) first seen
that day: 35% and 36% of impressions, at 10.8% and 12.0% CTR vs 18.0% and 17.0% for established creatives.
An exact attribution assigns **−2.53pp** (more than the whole drop) on Oct 22 and **−1.81pp of −2.52pp (72%)** on Oct 28
to new-creative underperformance.

**4. The CTR model goes stale in days; recalibration doesn't fix it, retraining does.**

| Scoring day | Unseen creatives | Frozen AUC | Daily-retrain AUC | Retrain AUC gain (95% CI) | Frozen pred/actual | Retrain pred/actual |
|---|---|---|---|---|---|---|
| Oct 28 | 36.3% | 0.735 | 0.735 (same model) | n/a | 1.019 | 1.019 |
| Oct 29 | 41.5% | 0.714 | 0.726 | +0.012 (0.008 to 0.015) | 0.976 | 1.027 |
| Oct 30 | 49.4% | 0.701 | 0.722 | +0.021 (0.017 to 0.026) | 0.937 | 1.009 |

- The frozen model's AUC fell 0.035 in two days as the share of impressions on creatives it had never seen rose from 36% to 49%.
- Its score PSI crossed 0.1 on Oct 30 (0.137).
- Daily Platt recalibration on the previous day's labels can't change AUC (it is monotone), and its effect on calibration was mixed. Pred/actual improved on Oct 28 (1.019 to 0.987) and Oct 30 (0.937 to 0.962) but worsened on Oct 29 (0.976 to 0.958). ECE got worse on Oct 28 and Oct 29. Day-level CTR swings don't carry over reliably to the next day.
- Retraining daily kept predicted CTR within 2.7% of actual and normalized entropy at or below 0.902, vs 0.925 frozen.

## Honest notes

- Daily retrain and frozen are the same model on Oct 28 by construction (no new labels yet).
- AUC 0.70-0.74 and normalized entropy ~0.89-0.92 are modest. The features are label-encoded and the training
  window is about 133K rows. This project is about evaluating and monitoring a model, not about maximizing its accuracy.
- The injection test perturbs one real hour at a time. It measures detector power and is not presented as real incidents.
- Ten days of data cannot establish weekly seasonality.

## Tableau dashboard

`tableau/Ad_CTR_Monitoring.twbx` is a packaged workbook with its data bundled. Open it in Tableau Desktop or Tableau Public.
It has 6 worksheets and one 1400×1300 dashboard: hourly CTR alerts, the hourly volume monitor, new-creative attribution,
creative churn, model AUC, and calibration. Regenerate it with `python tableau/build_twbx.py`.

## Mobile-game retention A/B test (D1/D7)

`src/game_retention.py` analyzes the real **Cookie Cats** mobile-puzzle-game A/B test: 90,189 players, with the first
progress gate moved from level 30 to level 40. Source: GitHub repo ryanschaub/Mobile-Games-A-B-Testing-with-Cookie-Cats,
`cookie_cats.csv` (SHA-256 in `data/raw_game/SHA256SUMS`).

| Metric | gate_30 (control) | gate_40 | Difference | p (two-proportion z) |
|---|---|---|---|---|
| D1 retention | 44.82% | 44.23% | −0.59pp | 0.074 (not significant; MDE 0.93pp) |
| D7 retention | 19.02% | 18.20% | −0.82pp | 0.0016 |

- The bootstrap 95% CI on the D7 difference is −1.31pp to −0.30pp. Among players who returned on D1, D7 retention is 33.3% vs 32.3% (p=0.035).
- **Sample-ratio mismatch:** the arms are 44,700 vs 45,489 players, χ² p=0.0086. Keep gate 30, but treat the effect size with caution until the assignment is checked.
- A retention table split by game rounds was dropped on purpose: rounds are a post-treatment outcome, so splitting on them biases the comparison.

## Superset dashboard

`superset/` builds the same monitor in Apache Superset 6.1:
- `build_db.py` builds a SQLite file from the pipeline outputs.
- `build_dashboard.py` creates the database, 5 datasets, 7 charts and the dashboard through Superset's REST API.
- `dashboard_export.zip` is the exported bundle (Dashboards → Import), and `dashboard_screenshot.png` is the rendered result.

## Ad economics: eCPM and return on spend (Criteo, 16.5M impressions)

`ad_economics/aggregate_lambda.py` ran as an AWS Lambda in my account. It pulled Criteo's own release of the attribution
dataset from Hugging Face: 30 days of live display-ad traffic, 16,468,027 impressions, 675 campaigns. It aggregated
cost, clicks and attributed conversions by campaign and day. Results are in `ad_economics/results.json`.

- **Concentration:** the top 10% of campaigns take 58.3% of spend.
- **Return varies a lot between campaigns:** among the 346 campaigns with at least 10K impressions (89.7% of spend),
  return on spend runs from 1.98 at the 10th percentile to 7.71 at the 90th, a 3.9x spread.
- **Expensive inventory doesn't pay back more:** campaign eCPM is negatively correlated with return on spend (r = −0.40).
  This makes a case for reviewing bids on high-eCPM, low-return campaigns.

**Caveats:**
- The dataset card says `cost` and `cpo` are transformed versions of the real prices. Absolute eCPM and ROAS are
  therefore in the dataset's units, not dollars. Only comparisons (spread, ranking, correlation) are claimed. The paper
  uses the same two columns for its utility metric (value minus cost).
- The sample is subsampled (in-sample CTR is 36%), so CTR is not representative of live traffic.
- The dataset card's "45K conversions" doesn't match the file: it has 435,810 distinct conversion IDs, 236,331 of them
  attributed. The counts above come from the file.

## Customer LTV: cohort curves and predictive LTV (CDNOW, real purchases)

`src/ltv.py` uses CDNOW_master: 69,659 real purchases worth $2.50M by 23,570 customers acquired Jan-Mar 1997 and tracked
to June 1998. It's the standard benchmark for customer-LTV models (Fader & Hardie), and it ships inside the `lifetimes`
package (SHA-256 in `data/raw_ltv/SHA256SUMS`).

**Cohort value curves** (cumulative revenue per acquired customer):

| Cohort | Customers | 30d | 90d | 180d | 365d |
|---|---|---|---|---|---|
| Jan 1997 | 7,846 | $42.62 | $55.21 | $68.29 | $93.97 |
| Feb 1997 | 8,476 | $41.80 | $53.10 | $66.56 | $89.13 |
| Mar 1997 | 7,248 | $41.63 | $52.24 | $65.53 | $89.09 |
| All | 23,570 | $42.02 | $53.54 | $66.82 | $90.73 |

**Predictive LTV, out of sample.** BG/NBD (repeat-purchase frequency) and Gamma-Gamma (spend per order) were fit on the
first 39 weeks, then scored against the next 39 weeks (273 days) the model never saw:
- **Total revenue:** predicted $642K vs actual $777K (−17.3%). The naive baseline, which carries each customer's
  run-rate forward, predicted $1.12M (+44.1%).
- **Per-customer error:** MAE $32.68 vs $42.32 for the naive baseline (22.8% lower). Spearman rank correlation with actual value is 0.42.
- **Targeting:** the top predicted decile captured 51.6% of actual future revenue. The lower deciles are mostly tied
  one-time buyers, so their order is not informative.
- **Assumption check:** Gamma-Gamma requires spend per order to be independent of purchase frequency. It is (r = 0.08).

**ARPDAU:** CDNOW records purchases, not app sessions, so non-paying daily users are invisible and true ARPDAU can't be
computed. `outputs/ltv_daily_arppu.csv` reports what the data supports instead: revenue per daily paying customer
(daily ARPPU, mean $38.19 over 546 days).

## Marketing efficiency of public mobile-game publishers (SEC XBRL, real USD)

ROAS needs ad spend and the revenue it produced, and no public dataset has both in real money. The closest real-dollar
measure is blended marketing efficiency: revenue per dollar of sales-and-marketing expense, from companies' own SEC filings.

`data/raw_sec/sec_fetch_lambda.py` ran as an AWS Lambda and pulled quarterly revenue and S&M from SEC XBRL
(data.sec.gov companyfacts) into `data/raw_sec/sec_revenue_sm_quarterly.csv`. `src/marketing_efficiency.py` analyzes five
mobile/social game publishers, the advertisers that buy user acquisition: Playtika, Playstudios, DoubleDown, SciPlay
and Zynga. That's 88 company-quarters.

- **Typical level:** median revenue per marketing dollar is 4.1 to 5.3 depending on the publisher.
- **Diminishing returns:** in the 29 quarters where marketing spend rose more than 10% YoY (median +28%), revenue grew a
  median of only +4.6%. Across all 73 YoY pairs, marketing growth and revenue growth correlate at just r = 0.25.
- **Playtika:** revenue per marketing dollar fell from 4.81 (first four quarters) to 3.06 (last four). Its 2025
  marketing spend rose 38–52% YoY while revenue rose 8–11%.

**Caveats:**
- This is blended, not attributed. All revenue (including returning players) is divided by all S&M (including
  non-ad costs), so it is not campaign ROAS.
- Acquisitions move both lines.
- Q4 values exist only where companies tagged them as standalone quarters, so most series skip Q4.
- AppLovin, Take-Two, Unity and Roblox were also fetched but left out of the publisher analysis: different business models.
