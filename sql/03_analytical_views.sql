-- =============================================================================
-- 03_analytical_views.sql  -  reusable analytical layer
--
--   psql -d promo_lab -f sql/03_analytical_views.sql
--
-- These views mirror the Python analysis so the two can be cross-checked. They
-- use CTEs, window functions, aggregations and treatment-vs-control differencing.
-- The difference-in-differences (DiD) estimate is:
--
--     DiD = (treat_post - treat_pre) - (control_post - control_pre)
--
-- i.e. how much more the treatment group's spend moved than the control group's.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- v_customer_period : one row per customer per period (the analysis panel)
-- Customers with no activity in a period still appear, with zeros.
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_customer_period CASCADE;
CREATE VIEW v_customer_period AS
WITH periods AS (
    SELECT unnest(ARRAY['pre', 'post']) AS period
),
grid AS (
    SELECT c.customer_id, c.segment, c.region, c."group", p.period
    FROM customers c
    CROSS JOIN periods p
),
agg AS (
    SELECT
        customer_id,
        period,
        sum(amount)                                             AS spend,
        count(*)                                                AS txns,
        sum(amount) FILTER (WHERE is_eligible_category)         AS eligible_spend,
        sum(cashback_earned)                                    AS cashback
    FROM transactions
    GROUP BY customer_id, period
)
SELECT
    g.customer_id,
    g.segment,
    g.region,
    g."group",
    g.period,
    (g.period = 'post')::int                    AS post,
    (g."group" = 'treatment')::int              AS treat,
    COALESCE(a.spend, 0)                         AS spend,
    COALESCE(a.txns, 0)                          AS txns,
    COALESCE(a.eligible_spend, 0)                AS eligible_spend,
    COALESCE(a.cashback, 0)                      AS cashback
FROM grid g
LEFT JOIN agg a
       ON a.customer_id = g.customer_id
      AND a.period       = g.period;

-- -----------------------------------------------------------------------------
-- v_did_cells : the 2x2 group x period means that feed every DiD calculation
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_did_cells CASCADE;
CREATE VIEW v_did_cells AS
SELECT
    "group",
    period,
    count(DISTINCT customer_id)          AS customers,
    avg(spend)                           AS avg_spend,
    avg(eligible_spend)                  AS avg_eligible_spend,
    stddev_samp(spend)                   AS sd_spend,
    sum(spend)                           AS total_spend,
    sum(cashback)                        AS total_cashback
FROM v_customer_period
GROUP BY "group", period;

-- -----------------------------------------------------------------------------
-- v_did_overall : headline difference-in-differences with a 95% CI
-- CI uses the standard 2x2 DiD standard error:
--   SE(DiD) = sqrt( sum over the 4 cells of (sd^2 / n) )
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_did_overall CASCADE;
CREATE VIEW v_did_overall AS
WITH cells AS (
    SELECT
        "group", period, customers, avg_spend, sd_spend
    FROM v_did_cells
),
p AS (
    SELECT
        max(avg_spend) FILTER (WHERE "group" = 'treatment' AND period = 'pre')  AS t_pre,
        max(avg_spend) FILTER (WHERE "group" = 'treatment' AND period = 'post') AS t_post,
        max(avg_spend) FILTER (WHERE "group" = 'control'   AND period = 'pre')  AS c_pre,
        max(avg_spend) FILTER (WHERE "group" = 'control'   AND period = 'post') AS c_post,
        sum(sd_spend * sd_spend / NULLIF(customers, 0))                         AS var_did
    FROM cells
),
params AS (
    SELECT param_value AS sig_z FROM promo_params WHERE param_name = 'sig_z'
)
SELECT
    (t_post - t_pre) - (c_post - c_pre)                       AS did_spend_per_customer,
    sqrt(var_did)                                             AS std_error,
    (t_post - t_pre) - (c_post - c_pre) - sig_z * sqrt(var_did) AS ci_low,
    (t_post - t_pre) - (c_post - c_pre) + sig_z * sqrt(var_did) AS ci_high,
    t_pre  AS treat_pre,  t_post AS treat_post,
    c_pre  AS control_pre, c_post AS control_post,
    -- counterfactual = treatment pre + the control group's pre->post change
    (t_pre + (c_post - c_pre))                                AS counterfactual_treat_post,
    ((t_post - t_pre) - (c_post - c_pre)) / NULLIF(t_pre + (c_post - c_pre), 0) AS lift_pct
FROM p CROSS JOIN params;

-- -----------------------------------------------------------------------------
-- Generic DiD by an arbitrary dimension, implemented once per dimension below.
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_did_by_segment CASCADE;
CREATE VIEW v_did_by_segment AS
WITH cells AS (
    SELECT
        segment, "group", period,
        count(*)                          AS customers,
        avg(spend)                        AS avg_spend,
        stddev_samp(spend)                AS sd_spend,
        avg(eligible_spend)               AS avg_eligible_spend,
        stddev_samp(eligible_spend)       AS sd_eligible_spend
    FROM v_customer_period
    GROUP BY segment, "group", period
),
w AS (
    SELECT
        segment,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='pre')  AS t_pre,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='post') AS t_post,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='pre')  AS c_pre,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='post') AS c_post,
        max(avg_eligible_spend) FILTER (WHERE "group"='treatment' AND period='pre')  AS te_pre,
        max(avg_eligible_spend) FILTER (WHERE "group"='treatment' AND period='post') AS te_post,
        max(avg_eligible_spend) FILTER (WHERE "group"='control'   AND period='pre')  AS ce_pre,
        max(avg_eligible_spend) FILTER (WHERE "group"='control'   AND period='post') AS ce_post,
        sum(sd_spend * sd_spend / NULLIF(customers,0))                      AS var_did,
        sum(sd_eligible_spend * sd_eligible_spend / NULLIF(customers,0))    AS var_did_elig,
        sum(customers) FILTER (WHERE "group"='treatment' AND period='pre')  AS n_treat
    FROM cells
    GROUP BY segment
),
params AS (SELECT param_value AS sig_z FROM promo_params WHERE param_name='sig_z')
SELECT
    w.segment,
    w.n_treat                                                       AS treatment_customers,
    -- total spend (carries the halo; noisier)
    (t_post - t_pre) - (c_post - c_pre)                              AS did_spend_per_cust,
    (t_post - t_pre) - (c_post - c_pre) - sig_z*sqrt(var_did)        AS ci_low,
    (t_post - t_pre) - (c_post - c_pre) + sig_z*sqrt(var_did)        AS ci_high,
    (t_pre + (c_post - c_pre))                                       AS counterfactual_spend_per_cust,
    ((t_post - t_pre) - (c_post - c_pre)) / NULLIF(t_pre + (c_post - c_pre), 0) AS lift_pct,
    (abs((t_post - t_pre) - (c_post - c_pre)) > sig_z*sqrt(var_did)) AS significant_95,
    -- eligible-category spend (PRIMARY outcome; cleaner identification)
    (te_post - te_pre) - (ce_post - ce_pre)                          AS did_eligible_spend_per_cust,
    (te_post - te_pre) - (ce_post - ce_pre) - sig_z*sqrt(var_did_elig) AS eligible_ci_low,
    (te_post - te_pre) - (ce_post - ce_pre) + sig_z*sqrt(var_did_elig) AS eligible_ci_high,
    (te_pre + (ce_post - ce_pre))                                    AS counterfactual_eligible_spend_per_cust,
    ((te_post - te_pre) - (ce_post - ce_pre)) / NULLIF(te_pre + (ce_post - ce_pre), 0) AS eligible_lift_pct,
    (abs((te_post - te_pre) - (ce_post - ce_pre)) > sig_z*sqrt(var_did_elig)) AS eligible_significant_95,
    -- halo = total effect minus eligible effect
    ((t_post - t_pre) - (c_post - c_pre)) - ((te_post - te_pre) - (ce_post - ce_pre)) AS halo_spend_per_cust
FROM w CROSS JOIN params;

DROP VIEW IF EXISTS v_did_by_region CASCADE;
CREATE VIEW v_did_by_region AS
WITH cells AS (
    SELECT region, "group", period,
           count(*) AS customers, avg(spend) AS avg_spend, stddev_samp(spend) AS sd_spend
    FROM v_customer_period
    GROUP BY region, "group", period
),
w AS (
    SELECT region,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='pre')  AS t_pre,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='post') AS t_post,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='pre')  AS c_pre,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='post') AS c_post,
        sum(sd_spend*sd_spend / NULLIF(customers,0))                        AS var_did
    FROM cells GROUP BY region
),
params AS (SELECT param_value AS sig_z FROM promo_params WHERE param_name='sig_z')
SELECT region,
    (t_post - t_pre) - (c_post - c_pre)                       AS did_spend_per_cust,
    (t_post - t_pre) - (c_post - c_pre) - sig_z*sqrt(var_did) AS ci_low,
    (t_post - t_pre) - (c_post - c_pre) + sig_z*sqrt(var_did) AS ci_high,
    (abs((t_post - t_pre) - (c_post - c_pre)) > sig_z*sqrt(var_did)) AS significant_95
FROM w CROSS JOIN params;

DROP VIEW IF EXISTS v_did_by_category CASCADE;
CREATE VIEW v_did_by_category AS
WITH cat_cust AS (
    -- customer x period x category spend (only categories the customer used)
    SELECT
        c.customer_id, c."group", cat.merchant_category, per.period,
        COALESCE(sum(t.amount), 0) AS spend
    FROM customers c
    CROSS JOIN (SELECT DISTINCT merchant_category FROM transactions) cat
    CROSS JOIN (SELECT unnest(ARRAY['pre','post']) AS period) per
    LEFT JOIN transactions t
           ON t.customer_id = c.customer_id
          AND t.merchant_category = cat.merchant_category
          AND t.period = per.period
    GROUP BY c.customer_id, c."group", cat.merchant_category, per.period
),
cells AS (
    SELECT merchant_category, "group", period,
           count(*) AS customers, avg(spend) AS avg_spend, stddev_samp(spend) AS sd_spend
    FROM cat_cust
    GROUP BY merchant_category, "group", period
),
w AS (
    SELECT merchant_category,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='pre')  AS t_pre,
        max(avg_spend) FILTER (WHERE "group"='treatment' AND period='post') AS t_post,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='pre')  AS c_pre,
        max(avg_spend) FILTER (WHERE "group"='control'   AND period='post') AS c_post,
        sum(sd_spend*sd_spend / NULLIF(customers,0))                        AS var_did
    FROM cells GROUP BY merchant_category
),
params AS (SELECT param_value AS sig_z FROM promo_params WHERE param_name='sig_z')
SELECT
    w.merchant_category,
    w.merchant_category IN ('Dining', 'Entertainment')        AS is_eligible,
    (t_post - t_pre) - (c_post - c_pre)                       AS did_spend_per_cust,
    (t_post - t_pre) - (c_post - c_pre) - sig_z*sqrt(var_did) AS ci_low,
    (t_post - t_pre) - (c_post - c_pre) + sig_z*sqrt(var_did) AS ci_high,
    (abs((t_post - t_pre) - (c_post - c_pre)) > sig_z*sqrt(var_did)) AS significant_95
FROM w CROSS JOIN params;

-- -----------------------------------------------------------------------------
-- v_weekly_trend : weekly spend per customer by group, with window functions
--   * running_spend_per_customer : cumulative over the study
--   * wow_growth                 : week-over-week % change (LAG)
--   * spend_vs_control           : treatment minus control, same week
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_weekly_trend CASCADE;
CREATE VIEW v_weekly_trend AS
WITH n_by_group AS (
    SELECT "group", count(*) AS n_customers FROM customers GROUP BY "group"
),
wk AS (
    SELECT
        t.study_week,
        pc.week_start,
        pc.period,
        pc.promotion_active,
        t."group",
        sum(t.amount)                                  AS spend,
        count(*)                                       AS txns
    FROM transactions t
    JOIN promotion_calendar pc ON pc.study_week = t.study_week
    GROUP BY t.study_week, pc.week_start, pc.period, pc.promotion_active, t."group"
),
per_cust AS (
    SELECT
        wk.*,
        wk.spend / g.n_customers AS spend_per_customer
    FROM wk
    JOIN n_by_group g USING ("group")
)
SELECT
    study_week,
    week_start,
    period,
    promotion_active,
    "group",
    spend,
    txns,
    spend_per_customer,
    sum(spend_per_customer) OVER (
        PARTITION BY "group" ORDER BY study_week
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                              AS running_spend_per_customer,
    spend_per_customer
      - LAG(spend_per_customer) OVER (PARTITION BY "group" ORDER BY study_week)
      AS wow_change_per_customer,
    spend_per_customer
      - AVG(spend_per_customer) FILTER (WHERE period = 'pre')
            OVER (PARTITION BY "group")
      AS vs_own_pre_mean
FROM per_cust;

-- -----------------------------------------------------------------------------
-- v_customer_baseline_deciles : window functions on pre-period behaviour
-- Useful for asking "did heavy pre-period spenders respond differently?"
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_customer_baseline_deciles CASCADE;
CREATE VIEW v_customer_baseline_deciles AS
WITH pre AS (
    SELECT customer_id, segment, region, "group", spend AS pre_spend, eligible_spend AS pre_eligible
    FROM v_customer_period
    WHERE period = 'pre'
),
post AS (
    SELECT customer_id, spend AS post_spend
    FROM v_customer_period
    WHERE period = 'post'
)
SELECT
    pre.customer_id,
    pre.segment,
    pre.region,
    pre."group",
    pre.pre_spend,
    post.post_spend,
    post.post_spend - pre.pre_spend                                  AS spend_change,
    NTILE(5) OVER (PARTITION BY pre.segment ORDER BY pre.pre_spend)   AS pre_spend_quintile,
    PERCENT_RANK() OVER (ORDER BY pre.pre_spend)                      AS pre_spend_percentile,
    RANK()        OVER (PARTITION BY pre.segment ORDER BY pre.pre_spend DESC) AS pre_spend_rank_in_segment
FROM pre
JOIN post USING (customer_id);

-- -----------------------------------------------------------------------------
-- v_promotion_economics_by_segment : DiD  +  actual cashback cost  +  params
--   -> incremental spend, promo cost, incremental margin, ROI, break-even
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_promotion_economics_by_segment CASCADE;
CREATE VIEW v_promotion_economics_by_segment AS
WITH did AS (
    SELECT * FROM v_did_by_segment
),
cost AS (
    SELECT segment, sum(cashback_earned) AS promo_cost
    FROM transactions
    WHERE "group" = 'treatment' AND period = 'post'
    GROUP BY segment
),
params AS (
    SELECT
        max(param_value) FILTER (WHERE param_name = 'contribution_margin')    AS margin,
        max(param_value) FILTER (WHERE param_name = 'merchant_funding_share') AS funding
    FROM promo_params
),
calc AS (
    SELECT
        d.segment,
        d.treatment_customers,
        d.did_eligible_spend_per_cust,
        d.eligible_significant_95,
        d.eligible_lift_pct,
        d.did_eligible_spend_per_cust * d.treatment_customers          AS incremental_eligible_spend,
        d.eligible_ci_low  * d.treatment_customers                     AS incremental_eligible_spend_ci_low,
        d.eligible_ci_high * d.treatment_customers                     AS incremental_eligible_spend_ci_high,
        d.halo_spend_per_cust * d.treatment_customers                  AS halo_spend,
        d.counterfactual_eligible_spend_per_cust * d.treatment_customers AS counterfactual_eligible_spend,
        c.promo_cost * p.funding                                       AS promotion_cost,
        p.margin                                                       AS margin
    FROM did d
    JOIN cost c USING (segment)
    CROSS JOIN params p
)
SELECT
    segment,
    treatment_customers,
    did_eligible_spend_per_cust,
    eligible_significant_95,
    eligible_lift_pct,
    incremental_eligible_spend,
    incremental_eligible_spend_ci_low,
    incremental_eligible_spend_ci_high,
    halo_spend,
    counterfactual_eligible_spend,
    promotion_cost,
    margin * incremental_eligible_spend                               AS incremental_margin,
    margin * incremental_eligible_spend - promotion_cost              AS net_benefit,
    (margin * incremental_eligible_spend - promotion_cost)
        / NULLIF(promotion_cost, 0)                                   AS roi,
    (margin * incremental_eligible_spend_ci_low - promotion_cost)
        / NULLIF(promotion_cost, 0)                                   AS roi_ci_low,
    (margin * incremental_eligible_spend_ci_high - promotion_cost)
        / NULLIF(promotion_cost, 0)                                   AS roi_ci_high,
    (margin * (incremental_eligible_spend + GREATEST(halo_spend, 0)) - promotion_cost)
        / NULLIF(promotion_cost, 0)                                   AS roi_with_halo,
    promotion_cost / margin                                           AS breakeven_eligible_spend,
    (promotion_cost / margin) / NULLIF(counterfactual_eligible_spend, 0) AS breakeven_eligible_lift_pct,
    (eligible_significant_95 AND did_eligible_spend_per_cust > 0
        AND margin * incremental_eligible_spend - promotion_cost > 0) AS recommended_target,
    CASE
        WHEN NOT eligible_significant_95
            THEN 'No statistically reliable lift - do not target'
        WHEN (margin * incremental_eligible_spend - promotion_cost)
             / NULLIF(promotion_cost, 0) >= 0.15
            THEN 'Significant lift, positive ROI - target / expand'
        WHEN margin * incremental_eligible_spend - promotion_cost >= 0
            THEN 'Significant lift, ROI near break-even - optimise offer'
        ELSE 'Significant lift but negative ROI - do not expand'
    END                                                               AS recommendation
FROM calc;

-- -----------------------------------------------------------------------------
-- v_promotion_economics_overall : summed, plus the recommended-targets scenario
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_promotion_economics_overall CASCADE;
CREATE VIEW v_promotion_economics_overall AS
WITH e AS (SELECT * FROM v_promotion_economics_by_segment)
SELECT
    'All treated segments (as tested)'::text        AS scenario,
    sum(incremental_eligible_spend)                 AS incremental_eligible_spend,
    sum(GREATEST(halo_spend, 0))                    AS halo_spend,
    sum(promotion_cost)                             AS promotion_cost,
    sum(incremental_margin)                         AS incremental_margin,
    sum(net_benefit)                                AS net_benefit,
    sum(net_benefit) / NULLIF(sum(promotion_cost), 0) AS roi
FROM e
UNION ALL
SELECT
    'Targeted (recommended segments only)',
    sum(incremental_eligible_spend),
    sum(GREATEST(halo_spend, 0)),
    sum(promotion_cost),
    sum(incremental_margin),
    sum(net_benefit),
    sum(net_benefit) / NULLIF(sum(promotion_cost), 0)
FROM e
WHERE recommended_target;
