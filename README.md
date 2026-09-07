# Merchant Promotion Experimentation Lab

An end-to-end analysis of a card cashback promotion: did it cause enough
incremental customer spending to pay for itself, and which customer segments
should receive it?

The project runs a full experimentation workflow - randomised test design,
causal inference with difference-in-differences, a SQL analytics layer,
promotion economics and break-even analysis, an Excel scenario model, and a
Tableau executive dashboard - and ends with a segment-level business
recommendation.

**Stack:** Python (pandas, statsmodels, NumPy) · PostgreSQL / SQL · Excel · Tableau

---

## Interactive Tableau Dashboard

[**View the Interactive Tableau Dashboard**](https://public.tableau.com/views/Merchant_Promotion_Experimentation_Lab/MerchantCashbackPromotion-ExperimentResults?:language=en-US&:sid=&:redirect=auth&publish=yes&showOnboarding=true&:display_count=n&:origin=viz_share_link)

Treatment vs. control performance, incremental lift and ROI by customer segment,
merchant category and region, and the recommended segments to target.

---

## Business problem

A merchant and its card-network partner run a **3% cashback promotion on Dining
and Entertainment**. Cashback is expensive, and most of it is paid on spend that
would have happened anyway. Three questions:

1. Does the promotion **cause** incremental spend, or is spend just drifting up?
2. Is the incremental spend worth more (at margin) than the cashback it costs?
3. **Which customer segments** should get the offer - and which should not?

## Experiment design

| | |
|---|---|
| **Design** | Randomised controlled trial, cardholder-level, ~50/50 treatment vs. control |
| **Population** | 10,000 customers · 5 segments · 5 US regions |
| **Timeline** | 12 weeks pre-promotion + 12 weeks promotion |
| **Data** | ~448,000 synthetic card transactions |
| **Treatment** | 3% cashback on Dining + Entertainment during the promotion window |
| **Primary outcome** | Eligible-category spend per customer per period |
| **Method** | Difference-in-differences (DiD), HC1-robust standard errors, parallel-trends placebo test, segment-level lift, promotion ROI and break-even |

A **+3% seasonal lift is built into both groups** during the promotion period. A
naïve before/after comparison would count it as promotion impact;
difference-in-differences removes it.

## Dataset

Fully synthetic and reproducible (`python src/generate_data.py`, fixed seed).
Each segment is given its own response to the promotion, spanning the ROI
spectrum; the analysis estimates those responses from the data.

| Segment | Designed eligible-spend response | Expected economics |
|---|---|---|
| Digital Native | ~26% lift | Strong positive ROI |
| Affluent Frequent | ~22% lift | Positive ROI |
| Mainstream | ~12% lift | Around / below break-even |
| Budget Occasional | ~6% lift | Negative ROI |
| Dormant Reactivation | ~9% lift, low base | Negative ROI / no measurable effect |

Column-level detail: `docs/data_dictionary.md`.

## Methodology

Difference-in-differences on a customer × period panel:

```
spend_ip = β0 + β1·post + β2·treat + β3·(post × treat) + ε
```

`β3` is the causal estimate - the movement in the treatment group beyond the
control group's movement. The same quantity is computed independently in SQL from
the four group × period cell means; `src/validate_analytics.py` confirms the two
match to the cent. Full detail in `docs/methodology.md`.

## Key findings

- **The promotion works on average, but only marginally.** Overall DiD =
  **+$91.75 per customer** over 12 weeks (95% CI $3.85–$179.66, p = 0.04). On the
  primary outcome (eligible-category spend) it is **+$49.23, p < 0.001**.
- **The parallel-trends placebo test passes** (placebo DiD = −$5.30, p = 0.81):
  treatment and control moved together before launch.
- **Blended ROI is +30%, but the 95% CI runs −30% to +89%** - not a reliable win
  as currently run.
- **The effect is concentrated in two segments:**

  | Segment | Eligible-spend lift | Significant | ROI | Verdict |
  |---|---|---|---|---|
  | Digital Native | **+24.5%** | p < 0.001 | **+64%** | Target |
  | Affluent Frequent | **+20.7%** | p < 0.001 | **+43%** | Target |
  | Mainstream | +10.1% | p = 0.009 | −23% | Exclude – real lift, below break-even |
  | Budget Occasional | +12.1% | p = 0.03 | −10% | Exclude |
  | Dormant Reactivation | +0.9% | p = 0.93 | −93% | Exclude – no measurable response |

- **Break-even is a ~14% lift in eligible spend** (3% cashback ÷ 25% margin, net
  of cashback paid on incremental spend). Only the top two segments clear it.
- **Heavier spenders respond more** - top-quintile DiD ≈ $160 vs. ≈ $35 for the
  bottom quintile.
- **Halo spend** (spillover into other categories) is positive in the point
  estimates but the test was not powered to confirm it, so it is treated as
  upside only.

## Recommendation

**Narrow the promotion to Affluent Frequent and Digital Native customers**,
skewing to higher spenders within those segments. Remove it from Mainstream,
Budget Occasional and Dormant Reactivation.

Targeting moves ROI from **~30% (confidence interval crossing zero)** to
**~49%, with net benefit of ~$17k per 12-week window** on the tested base, and
cuts the cashback spend that destroys value. Before a national rollout: run a
scaled confirmatory test to tighten the confidence interval, run a dedicated
halo test, and test a lower or spend-thresholded offer for Mainstream.

Segment-by-segment reasoning: `docs/executive_recommendation.md`.

## Project structure

```
merchant-promotion-experimentation-lab/
├── src/
│   ├── config.py              # business and design parameters
│   ├── generate_data.py       # 1. synthetic customers + transactions
│   ├── analysis_did.py        # 2. difference-in-differences, placebo test, segment lift
│   ├── economics.py           # 3. incremental spend, cost, ROI, break-even
│   ├── build_excel_model.py   # 4. formula-driven scenario workbook
│   ├── export_tableau.py      # 5. Tableau extracts
│   ├── validate_analytics.py  # SQL views vs. Python cross-check (DuckDB)
│   └── run_all.py             # run the full pipeline
├── sql/
│   ├── 01_schema.sql          # tables, indexes, parameters
│   ├── 02_load_data.sql       # load the CSVs
│   ├── 03_analytical_views.sql# views: CTEs, window functions, DiD, economics
│   └── 04_analysis_queries.sql# business questions answered from the views
├── data/                      # generated CSVs (transactions.csv is git-ignored)
├── outputs/
│   ├── analysis/              # DiD and economics result tables
│   ├── excel/                 # promotion_scenario_model.xlsx
│   └── tableau/               # dashboard workbook + extracts
├── dashboard/
│   └── TABLEAU_INSTRUCTIONS.md# dashboard build specification
└── docs/
    ├── methodology.md
    ├── executive_recommendation.md
    └── data_dictionary.md
```

## Running the project

### Python analysis

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python src/run_all.py               # data + analysis + Excel model + Tableau extracts
```

Individual steps can also be run in order (`generate_data.py`, `analysis_did.py`,
`economics.py`, `build_excel_model.py`, `export_tableau.py`). Results are written
to `outputs/`. `python src/run_all.py --skip-data` reruns everything except data
generation.

### PostgreSQL layer

```bash
createdb promo_lab
psql -d promo_lab -f sql/01_schema.sql
psql -d promo_lab -v ON_ERROR_STOP=1 -f sql/02_load_data.sql   # run from the project root
psql -d promo_lab -f sql/03_analytical_views.sql
psql -d promo_lab -f sql/04_analysis_queries.sql
```

Without a Postgres server, `pip install duckdb && python src/validate_analytics.py`
runs the same view layer in-process and checks it against the Python analysis.

### Excel model

Open `outputs/excel/promotion_scenario_model.xlsx`. The yellow cells on the
**Assumptions** sheet (cashback rate, margin, rollout size, lift) drive the
**Scenario Model** sheet, which recalculates ROI and break-even for Conservative,
Base and Upside cases.

### Tableau

`outputs/tableau/` contains the packaged workbook and the CSV extracts behind it.
`dashboard/TABLEAU_INSTRUCTIONS.md` documents how each view and the dashboard are
built.

## Notes

- The analysis is seeded and reproducible. Segment responses are set in
  `src/config.py` and are not referenced by any analysis code; changing the seed
  changes the exact figures but not the conclusions.
- Data is synthetic. Segment responses are fixed parameters rather than a
  calibrated model of price elasticity, so alternative offer designs need to be
  re-tested rather than read off this dataset.
