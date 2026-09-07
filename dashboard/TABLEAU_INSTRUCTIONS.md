# Tableau Executive Dashboard - Build Specification

The published dashboard is a single screen that answers "did the promotion work,
for whom, and should we scale it?". This document records how it is built from
the extracts in `outputs/tableau/`.

The packaged workbook is `outputs/tableau/Merchant_Promotion_Experimentation_Lab.twb`.
The source files are pre-aggregated and tidy - no Tableau-side data prep is needed
beyond joins on `segment` / `region`.

---

## 1. Connect the data

Add these as **separate data sources** (Text file connection):

| Data source | File | Primary key |
|---|---|---|
| Scorecard | `experiment_scorecard.csv` | (single row) |
| Segment results | `did_by_segment.csv` | `segment` |
| Region results | `did_by_region.csv` | `region` |
| Category results | `did_by_category.csv` | `merchant_category` |
| Segment × region grid | `did_segment_region_grid.csv` | `segment`, `region` |
| Weekly trend | `trend_weekly_by_group.csv` | `study_week`, `test_group` |
| Customer-period fact | `fact_customer_period.csv` | `customer_id`, `period` |

No cross-source joins are required for the core views; Tableau's per-sheet data
source selection is enough.

---

## 2. Calculated fields (Segment results source)

```
// Format ROI as a signed percentage
ROI %            = ROUND([roi] * 100, 0)

// Colour rule for the recommendation
Target Colour    = IF [recommended_target] THEN "Target"
                   ELSEIF [did_eligible_spend_per_cust] < 0 THEN "Exclude"
                   ELSE "Do not target" END

// Significance marker
Sig Label        = IF [eligible_significant_5pct] THEN "●" ELSE "○" END
```

On the weekly-trend source:

```
Promo Shading    = IF [promotion_active] THEN "Promotion live" ELSE "Baseline" END
```

---

## 3. Worksheets

### 3.1 KPI strip (Scorecard source)
Four text tiles across the top:

| Tile | Field | Format |
|---|---|---|
| Incremental eligible spend | `total_incremental_eligible_spend` | $, 0 dp |
| Promotion cost | `total_promotion_cost` | $, 0 dp |
| Net benefit (targeted) | `targeted_net_benefit` | $, 0 dp, red/green |
| ROI (targeted) | `targeted_roi` | %, 0 dp, red/green |

Add a caption: "Difference-in-differences on 10,000 randomised cardholders,
12 weeks pre / 12 weeks post. Parallel-trends check: PASS."

### 3.2 Treatment vs. Control - spend over time (Weekly trend source)
* Columns: `study_week`
* Rows: `spend_per_customer`
* Colour: `test_group`
* Detail/Shading: add a reference band from week 13 to 24 (`Promo Shading`), or a
  drop line at week 13 labelled "Promotion launch".
* This chart *is* the parallel-trends story: the two lines track each other for
  weeks 1–12, then diverge after launch.

### 3.3 Incremental lift by segment (Segment results source)
* Bar chart, Rows: `segment` (sorted by `did_eligible_spend_per_cust` desc)
* Columns: `did_eligible_spend_per_cust`
* Colour: `Target Colour` (green / grey / red)
* Add the 95% CI as an error bar using `eligible_ci_low` / `eligible_ci_high`
  (Measure Values on the detail shelf, or a Gantt/interval trick).
* Label each bar with `Sig Label` + `eligible_lift_pct`.

### 3.4 ROI by segment (Segment results source)
* Bar chart, Columns: `ROI %`, Rows: `segment`
* Colour: `Target Colour`
* Reference line at 0.
* Optional second bars for `roi_with_halo` in a lighter shade, labelled
  "with halo upside".

### 3.5 Where spend actually moved (Category results source)
* Bar chart, Rows: `merchant_category` sorted by `did_spend_per_cust`
* Colour: `is_eligible`
* Shows that the effect is concentrated in Dining + Entertainment and roughly
  zero elsewhere (individually).

### 3.6 Performance by region (Region results source)
* Filled map (`region` → state groups) or a simple bar of `did_spend_per_cust`
  with CI error bars.
* Expected read: all positive, none individually significant - "not a regional
  play."

### 3.7 Segment × region heatmap (Grid source)
* Rows: `segment`, Columns: `region`
* Colour: `did_spend_per_cust` (diverging, centred on 0)
* Text: the value.

### 3.8 Recommended targets (Segment results source)
* Text table: `segment`, `eligible_lift_pct`, `eligible_significant_5pct`,
  `ROI %`, `roi_with_halo`, `verdict`, `recommendation`.
* Filter or sort so TARGET rows sit on top.

---

## 4. Assemble the dashboard

Layout (1200 × 900 or "Automatic"):

```
┌─────────────────────────────────────────────────────────────┐
│  KPI strip (3.1)                                             │
├───────────────────────────────┬─────────────────────────────┤
│  Treatment vs Control          │  Incremental lift by        │
│  spend over time (3.2)         │  segment (3.3)              │
├───────────────────────────────┼─────────────────────────────┤
│  ROI by segment (3.4)          │  Where spend moved (3.5)    │
├───────────────────────────────┴─────────────────────────────┤
│  Region (3.6)  │  Segment×Region heatmap (3.7)               │
├─────────────────────────────────────────────────────────────┤
│  Recommended targets table (3.8)                            │
└─────────────────────────────────────────────────────────────┘
```

* Add a dashboard title: **"Merchant Cashback Promotion - Experiment Results"**.
* Add one **Segment** filter (apply to worksheets using the segment/fact
  sources) so a reader can drill into a single segment.
* Add a text box at the bottom with the one-line recommendation from
  `docs/executive_recommendation.md`.

---

## 5. Colour and formatting conventions

| Meaning | Colour |
|---|---|
| Treatment | `#1F77B4` (blue) |
| Control | `#7F7F7F` (grey) |
| Target / positive ROI | `#2CA02C` (green) |
| Do not target / neutral | `#BFBFBF` (light grey) |
| Exclude / negative ROI | `#D62728` (red) |

* Currency: `$#,##0` (no decimals on totals).
* Percentages: `0%` on bars, `0.0%` on break-even lines.
* Always show the 0 reference line on ROI and lift charts.
