-- =============================================================================
-- 04_analysis_queries.sql  -  business questions answered off the view layer
--
--   psql -d promo_lab -f sql/04_analysis_queries.sql
--
-- Every query below reads from the views in 03_analytical_views.sql. They are the
-- SQL equivalent of the Python analysis and feed the same story that lands in
-- docs/executive_recommendation.md.
-- =============================================================================

\echo '--- Q1. Were the treatment and control groups balanced before the promotion? ---'
-- Randomisation check: pre-period spend and customer counts should be close.
SELECT
    "group",
    count(*)                              AS customers,
    round(avg(spend), 2)                  AS avg_pre_spend,
    round(avg(eligible_spend), 2)         AS avg_pre_eligible_spend
FROM v_customer_period
WHERE period = 'pre'
GROUP BY "group"
ORDER BY "group";

\echo ''
\echo '--- Q2. Headline difference-in-differences (spend per customer, whole test) ---'
SELECT
    round(treat_pre, 2)                    AS treat_pre,
    round(treat_post, 2)                   AS treat_post,
    round(control_pre, 2)                  AS control_pre,
    round(control_post, 2)                 AS control_post,
    round(did_spend_per_customer, 2)       AS did_spend_per_customer,
    round(ci_low, 2)                       AS ci_low_95,
    round(ci_high, 2)                      AS ci_high_95,
    round(lift_pct * 100, 1)               AS lift_pct
FROM v_did_overall;

\echo ''
\echo '--- Q3. Did the groups move together BEFORE the promotion? (parallel trends) ---'
-- Split the pre period in half and run a placebo DiD. A small, CI-spanning-zero
-- number here means the parallel-trends assumption is credible.
WITH half AS (
    SELECT
        c.customer_id,
        c."group",
        CASE WHEN t.study_week > (SELECT max(study_week) / 2 FROM promotion_calendar WHERE period = 'pre')
             THEN 'late_pre' ELSE 'early_pre' END AS pseudo_period,
        t.amount
    FROM transactions t
    JOIN customers c USING (customer_id)
    WHERE t.period = 'pre'
),
cust AS (
    SELECT customer_id, "group", pseudo_period, sum(amount) AS spend
    FROM half GROUP BY customer_id, "group", pseudo_period
),
cell AS (
    SELECT "group", pseudo_period, avg(spend) AS avg_spend
    FROM cust GROUP BY "group", pseudo_period
)
SELECT
    round(
        max(avg_spend) FILTER (WHERE "group"='treatment' AND pseudo_period='late_pre')
      - max(avg_spend) FILTER (WHERE "group"='treatment' AND pseudo_period='early_pre')
      - ( max(avg_spend) FILTER (WHERE "group"='control' AND pseudo_period='late_pre')
        - max(avg_spend) FILTER (WHERE "group"='control' AND pseudo_period='early_pre') )
    , 2) AS placebo_did_pre_period
FROM cell;

\echo ''
\echo '--- Q4. Segment-level lift on the PRIMARY outcome (eligible-category spend) ---'
SELECT
    segment,
    treatment_customers,
    round(did_eligible_spend_per_cust, 2)   AS did_eligible_per_cust,
    round(eligible_ci_low, 2)               AS ci_low_95,
    round(eligible_ci_high, 2)              AS ci_high_95,
    round(eligible_lift_pct * 100, 1)       AS eligible_lift_pct,
    eligible_significant_95                 AS significant,
    round(halo_spend_per_cust, 2)           AS halo_per_cust
FROM v_did_by_segment
ORDER BY did_eligible_spend_per_cust DESC;

\echo ''
\echo '--- Q5. Which merchant categories actually moved? ---'
SELECT
    merchant_category,
    is_eligible,
    round(did_spend_per_cust, 2)    AS did_per_cust,
    round(ci_low, 2)                AS ci_low_95,
    round(ci_high, 2)               AS ci_high_95,
    significant_95
FROM v_did_by_category
ORDER BY is_eligible DESC, did_spend_per_cust DESC;

\echo ''
\echo '--- Q6. Regional read (expect no strong pattern - promo was not region-targeted) ---'
SELECT
    region,
    round(did_spend_per_cust, 2)  AS did_per_cust,
    round(ci_low, 2)              AS ci_low_95,
    round(ci_high, 2)             AS ci_high_95,
    significant_95
FROM v_did_by_region
ORDER BY did_spend_per_cust DESC;

\echo ''
\echo '--- Q7. Promotion economics by segment (identified effect = eligible spend) ---'
SELECT
    segment,
    eligible_significant_95                    AS significant,
    round(incremental_eligible_spend)          AS incr_eligible_spend,
    round(halo_spend)                          AS halo_spend,
    round(promotion_cost)                      AS promo_cost,
    round(incremental_margin)                  AS incr_margin,
    round(net_benefit)                         AS net_benefit,
    round(roi * 100)                           AS roi_pct,
    round(roi_with_halo * 100)                 AS roi_with_halo_pct,
    round(breakeven_eligible_lift_pct * 100, 1) AS breakeven_lift_pct,
    recommendation
FROM v_promotion_economics_by_segment
ORDER BY net_benefit DESC;

\echo ''
\echo '--- Q8. Overall economics: everyone vs. targeted rollout ---'
SELECT
    scenario,
    round(incremental_eligible_spend)   AS incr_eligible_spend,
    round(halo_spend)                   AS halo_upside,
    round(promotion_cost)               AS promo_cost,
    round(net_benefit)                  AS net_benefit,
    round(roi * 100)                    AS roi_pct
FROM v_promotion_economics_overall;

\echo ''
\echo '--- Q9. Weekly spend per customer by group, with running total (window fn) ---'
SELECT
    study_week,
    "group",
    period,
    round(spend_per_customer, 2)              AS spend_per_customer,
    round(running_spend_per_customer, 2)      AS running_spend_per_customer,
    round(wow_change_per_customer, 2)         AS wow_change
FROM v_weekly_trend
ORDER BY study_week, "group";

\echo ''
\echo '--- Q10. Do heavy pre-period spenders respond more? (NTILE window fn) ---'
-- Compare the treatment vs control spend change across pre-period spend quintiles.
SELECT
    pre_spend_quintile,
    round(avg(spend_change) FILTER (WHERE "group" = 'treatment'), 2) AS treat_change,
    round(avg(spend_change) FILTER (WHERE "group" = 'control'), 2)   AS control_change,
    round(
        avg(spend_change) FILTER (WHERE "group" = 'treatment')
      - avg(spend_change) FILTER (WHERE "group" = 'control')
    , 2)                                                             AS did_by_quintile
FROM v_customer_baseline_deciles
GROUP BY pre_spend_quintile
ORDER BY pre_spend_quintile;

\echo ''
\echo '--- Q11. Top 10 treated customers by measured spend change (RANK window fn) ---'
SELECT customer_id, segment, region,
       round(pre_spend, 2)  AS pre_spend,
       round(post_spend, 2) AS post_spend,
       round(spend_change, 2) AS spend_change,
       pre_spend_rank_in_segment
FROM v_customer_baseline_deciles
WHERE "group" = 'treatment'
ORDER BY spend_change DESC
LIMIT 10;

\echo ''
\echo '--- Q12. Segment x region incremental spend grid (for the dashboard heatmap) ---'
WITH cell AS (
    SELECT segment, region, "group", period, avg(spend) AS avg_spend
    FROM v_customer_period
    GROUP BY segment, region, "group", period
)
SELECT
    segment,
    region,
    round(
        ( max(avg_spend) FILTER (WHERE "group"='treatment' AND period='post')
        - max(avg_spend) FILTER (WHERE "group"='treatment' AND period='pre') )
      - ( max(avg_spend) FILTER (WHERE "group"='control' AND period='post')
        - max(avg_spend) FILTER (WHERE "group"='control' AND period='pre') )
    , 2) AS did_spend_per_cust
FROM cell
GROUP BY segment, region
ORDER BY segment, region;
