# Methodology

This note covers how the experiment is designed, how the causal effect is
estimated, and how the economics are derived. The business conclusions are in
`executive_recommendation.md`.

---

## 1. Business question

A merchant (and its card-network partner) runs a **3% cashback promotion on
Dining and Entertainment spend**. Cashback is expensive, and most of it is paid
on spend that would have happened anyway. The question is not "did spend go up?"
- spend usually drifts up - but:

> **Does the promotion cause enough *incremental* spend to cover its cost, and for
> which customers?**

---

## 2. Experiment design

| Element | Choice | Why |
|---|---|---|
| Unit | Cardholder | The promotion is assigned at the card level. |
| Assignment | Randomised ~50/50 into treatment / control | Randomisation makes the control group a valid counterfactual. |
| Treatment | 3% cashback on Dining + Entertainment | The offer under evaluation. |
| Pre period | 12 weeks before launch | Establishes each customer's baseline and lets us test parallel trends. |
| Post period | 12 weeks from launch | The promotion window. |
| Population | 10,000 customers, 5 segments, 5 regions | Enough power for segment-level reads. |
| Outcome (primary) | Eligible-category spend per customer per period | Where the promotion acts directly - cleanest identification, highest power. |
| Outcome (secondary) | Total spend per customer per period | Captures "halo" spend in other categories, but noisier. |

The synthetic data (`src/generate_data.py`) also bakes in a **+3% seasonal lift
that hits treatment and control equally** in the post period. A naive
before/after comparison on the treatment group alone would wrongly count that 3%
as promotion impact. Difference-in-differences removes it.

---

## 3. Difference-in-differences (DiD)

Collapse the transaction log to a **customer x period panel** (two rows per
customer). Estimate, by OLS:

```
spend_ip = β0 + β1·post + β2·treat + β3·(post × treat) + ε_ip
```

* `β1` picks up anything that changed for everyone between the two periods
  (the seasonal drift).
* `β2` picks up any fixed difference between the groups (small, because of
  randomisation).
* **`β3` - the coefficient on the interaction - is the DiD estimate:** the extra
  movement in the treatment group that the control group did *not* see. Under
  parallel trends it is the causal effect of the promotion.

Equivalently, using the four cell means:

```
DiD = (treat_post − treat_pre) − (control_post − control_pre)
```

The SQL layer (`sql/03_analytical_views.sql`) computes it the second way; the two
approaches agree to the cent (`src/validate_analytics.py` checks this).

### Standard errors and confidence intervals

* **Python:** heteroskedasticity-robust (HC1) standard errors from `statsmodels`,
  95% CI from the t-distribution.
* **SQL:** the textbook 2x2 DiD standard error,
  `SE = sqrt( Σ over the 4 cells of sd² / n )`, and a normal-approximation CI.

A segment is called **statistically significant** when its 95% CI on the
*eligible-spend* DiD excludes zero.

### Parallel-trends / placebo check

The DiD assumption is that, absent the promotion, treatment and control spend
would have moved in parallel. We can't test the future, but we can test the past:
split the 12 pre-period weeks into an early and a late half and run the same DiD
on that split. The estimate should be small and non-significant.

Result: **placebo DiD = −$5.30 per customer, p = 0.81** - no meaningful pre-trend,
so the design is credible.

---

## 4. Segment-level lift

The same regression is run within each of the five customer segments, on both
outcomes. This is where the promotion's real shape shows up: the average effect
hides the fact that a couple of segments drive almost all of the incremental
spend while others contribute nothing.

The generator gives each segment its own hidden true response. The analysis never
sees those numbers - it recovers them from the data, with sampling noise. The
recovered eligible-spend lifts track the ground truth closely (e.g. Digital
Native true 26% / estimated ~25%; Dormant true 9% / estimated ~1% and not
significant), which is the sanity check that the method works.

---

## 5. Promotion economics

For each segment, three numbers are combined (`src/economics.py`):

| Quantity | Definition |
|---|---|
| **Incremental eligible spend** | `DiD(eligible spend) × treated customers` - spend the promotion *caused* in Dining + Entertainment. |
| **Promotion cost** | Actual cashback dollars paid to treated customers in the post period, straight from the transaction log. |
| **Incremental margin** | `contribution margin (25%) × incremental eligible spend` - the profit that incremental spend produces. |

Then:

```
net benefit      = incremental margin − promotion cost
ROI              = net benefit / promotion cost
break-even lift  = the eligible-spend lift at which net benefit = 0
```

**Why eligible spend is the basis for ROI.** Cashback is paid on eligible spend,
so that is the effect the promotion can be cleanly *credited* with. The "halo"
(extra spend in other categories) is real in the point estimates but is **not
individually statistically reliable** in this test, and a merchant should not
fund a promotion on the strength of it. It is reported as a separate upside line
(`roi_with_halo`), not baked into the headline.

ROI is also recomputed at the 95% CI bounds of the DiD estimate, so the decision
is made on a *range* of plausible outcomes, not a single point.

### Break-even intuition

With a 3% cashback rate and a 25% margin, net benefit is zero when

```
0.25 × incremental − 0.03 × (counterfactual + incremental) = 0
⇒ incremental / counterfactual ≈ 13.6%
```

So a segment needs roughly a **14% lift in eligible spend** just to break even.
Segments below that line destroy value even though their lift is genuine and
statistically significant.

---

## 6. Scenario model (Excel)

`src/build_excel_model.py` projects the pilot read to an annual national program
for the **targeted** segments only. Three scenarios vary the one uncertain input -
incremental eligible spend per customer:

| Scenario | Incremental eligible spend / customer / window |
|---|---|
| Conservative | lower bound of the 95% CI |
| Base | DiD point estimate |
| Upside | upper bound of the 95% CI |

The workbook is formula-driven off an `Assumptions` sheet: changing the cashback
rate, margin, rollout size or lift recalculates ROI and break-even.

---

## 7. Limitations

* **Synthetic data.** Behaviour is generated from a model, not observed. The
  segment responses are exogenous parameters, not calibrated to the 3% offer, so
  "what if we offered 2%?" cannot be answered from this data - only re-tested.
* **One promotion window.** Novelty effects, fatigue and seasonality across
  multiple windows are not modelled.
* **Halo is under-powered.** The test was sized for the eligible-spend effect;
  the cross-category spillover would need a larger sample or a longer window to
  pin down.
* **No customer-acquisition or retention value.** The economics are purely
  incremental-spend vs. cashback-cost within the window. A fuller model would add
  lifetime-value effects, especially for the Dormant Reactivation segment.
