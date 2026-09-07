# Data Dictionary

All files are UTF-8 CSV with a header row.

---

## Raw data - `data/`

### `customers.csv` - 10,000 rows, one per cardholder

| Column | Type | Description |
|---|---|---|
| `customer_id` | int | Primary key. |
| `segment` | text | One of: Affluent Frequent, Digital Native, Mainstream, Budget Occasional, Dormant Reactivation. |
| `region` | text | Northeast, Southeast, Midwest, West, Southwest. |
| `group` | text | `treatment` (receives cashback) or `control`. Randomised ~50/50. |
| `tenure_months` | int | Months the customer has held the card (3–120). |
| `activity_index` | float | Per-customer spend-propensity multiplier, mean ≈ 1.0. Drives how active a cardholder is relative to the segment average. |

### `transactions.csv` - ~448,000 rows, one per card transaction

| Column | Type | Description |
|---|---|---|
| `transaction_id` | int | Primary key. |
| `customer_id` | int | FK to `customers`. |
| `txn_date` | date | Transaction date (YYYY-MM-DD). |
| `merchant_category` | text | Grocery, Dining, Fuel, Apparel, Electronics, Entertainment, Travel, OnlineRetail. |
| `amount` | float | Transaction amount in USD. |
| `cashback_earned` | float | Cashback paid on this transaction. Non-zero only for treatment customers, in the post period, in an eligible category. |
| `period` | text | `pre` (weeks 1–12) or `post` (weeks 13–24). |
| `study_week` | int | 1–24. |
| `segment` | text | Denormalised from `customers`. |
| `region` | text | Denormalised from `customers`. |
| `group` | text | Denormalised from `customers`. |
| `is_eligible_category` | bool | True for Dining and Entertainment. |

### `promotion_calendar.csv` - 24 rows

| Column | Type | Description |
|---|---|---|
| `study_week` | int | 1–24. |
| `week_start` | date | Monday of that week. |
| `period` | text | `pre` / `post`. |
| `promotion_active` | bool | True for weeks 13–24. |

---

## Analysis outputs - `outputs/analysis/`

| File | Grain | Notes |
|---|---|---|
| `customer_period_panel.csv` | customer × period | The DiD regression input. `post`, `treat` are 0/1 dummies. |
| `did_overall.csv` | 1 row | Headline DiD on total and eligible spend, plus the parallel-trends placebo result. |
| `did_by_segment.csv` | segment | DiD on total spend and (primary) eligible spend, each with 95% CI, p-value, significance flag, implied lift, plus the halo (`total − eligible`). |
| `did_by_region.csv` | region | DiD on total spend. |
| `did_by_category.csv` | merchant category | DiD on spend within each category. Shows the effect is concentrated in Dining + Entertainment. |
| `economics_by_segment.csv` | segment | Incremental eligible spend, halo, promotion cost, margin, net benefit, ROI (point + CI + with-halo), break-even lift, `recommended_target`, plain-English `verdict`. |
| `economics_overall.csv` | 2 rows | "All treated segments" vs. "Targeted (recommended segments only)". |
| `weekly_timeseries.csv` | week × group | Spend and spend-per-customer by week; drives the trend / parallel-trends chart. |

### Key fields in `economics_by_segment.csv`

| Column | Meaning |
|---|---|
| `did_eligible_spend_per_cust` | Causal effect on Dining+Entertainment spend, per treated customer, per 12-week window. |
| `eligible_significant_5pct` | Does the 95% CI on that estimate exclude zero? |
| `incremental_eligible_spend` | `did_eligible_spend_per_cust × treated customers`. |
| `halo_spend` | Estimated spend moved into non-eligible categories (point estimate; not individually significant). |
| `promotion_cost` | Actual cashback paid to treated customers in the window. |
| `incremental_margin` | `0.25 × incremental_eligible_spend`. |
| `net_benefit` | `incremental_margin − promotion_cost`. |
| `roi` | `net_benefit / promotion_cost`. |
| `roi_ci_low`, `roi_ci_high` | ROI recomputed at the DiD confidence-interval bounds. |
| `roi_with_halo` | ROI if the (unproven) halo spend is included. |
| `breakeven_eligible_lift_pct` | Eligible-spend lift at which `net_benefit = 0` (~14%). |
| `recommended_target` | `True` only if significant **and** ROI-positive on the identified effect. |

---

## Tableau extracts - `outputs/tableau/`

| File | Grain | Use in the dashboard |
|---|---|---|
| `experiment_scorecard.csv` | 1 row | KPI tiles (incremental spend, cost, net benefit, ROI, significance flags). |
| `fact_customer_period.csv` | customer × period | Flexible base for treatment-vs-control bar charts and distributions. Columns: `customer_id, period, segment, region, test_group, spend, txns, eligible_spend`. |
| `fact_transactions_sample.csv` | transaction (60k sample) | Category / time detail views. Columns: `txn_date, customer_id, segment, region, test_group, merchant_category, is_eligible_category, period, study_week, amount, cashback_earned`. |
| `trend_weekly_by_group.csv` | week × group | The spend-over-time line chart and the visual parallel-trends check. |
| `did_by_segment.csv` | segment | Segment lift bars, ROI bars, the recommended-targets table. Includes `recommendation` = TARGET / DO NOT TARGET / EXCLUDE. |
| `did_by_region.csv` | region | Region map / bar. |
| `did_by_category.csv` | category | "Where did spend actually move" bar. |
| `did_segment_region_grid.csv` | segment × region | Heatmap of incremental spend. |
