"""
Step 2 - Difference-in-differences analysis of the cashback experiment.

Reads  : data/customers.csv, data/transactions.csv
Writes : outputs/analysis/*.csv  (consumed by economics.py, the Excel model and Tableau)

Method
------
The transaction log is collapsed to a customer x period panel (two rows per
customer: pre and post) and the following model is estimated:

    spend_ip = b0 + b1*post + b2*treat + b3*(post x treat) + e

The coefficient b3 on the interaction term is the difference-in-differences
estimate: the change in the treatment group's spend, over and above the change
seen in the control group. Under the parallel-trends assumption it is the causal
effect of the promotion on spend per customer per period.

Reported:
  * the headline DiD on total spend and on eligible-category spend
  * heteroskedasticity-robust (HC1) standard errors and 95% confidence intervals
  * a placebo / parallel-trends check on the pre period only
  * the same regression run within each customer segment
  * a weekly time series of spend by group for the dashboard
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

import config as C

pd.set_option("display.width", 140)
pd.set_option("display.max_columns", 30)


# --------------------------------------------------------------------------------------
# Data prep
# --------------------------------------------------------------------------------------
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    customers = pd.read_csv(C.CUSTOMERS_CSV)
    txn = pd.read_csv(C.TRANSACTIONS_CSV, parse_dates=["txn_date"])
    return customers, txn


def build_customer_period_panel(customers: pd.DataFrame, txn: pd.DataFrame) -> pd.DataFrame:
    """Two rows per customer (pre, post) with spend / transaction aggregates.

    Customers with no transactions in a period still get a row with zeros, so the
    panel is balanced.
    """
    txn = txn.copy()
    txn["eligible_amount"] = txn["amount"].where(txn["is_eligible_category"], 0.0)
    agg = (
        txn.groupby(["customer_id", "period"])
        .agg(
            spend=("amount", "sum"),
            txns=("amount", "size"),
            eligible_spend=("eligible_amount", "sum"),
            cashback=("cashback_earned", "sum"),
        )
        .reset_index()
    )

    full_index = pd.MultiIndex.from_product(
        [customers["customer_id"], ["pre", "post"]], names=["customer_id", "period"]
    )
    panel = (
        agg.set_index(["customer_id", "period"])
        .reindex(full_index, fill_value=0.0)
        .reset_index()
    )

    panel = panel.merge(
        customers[["customer_id", "segment", "region", "group", "tenure_months"]],
        on="customer_id",
        how="left",
    )
    panel["post"] = (panel["period"] == "post").astype(int)
    panel["treat"] = (panel["group"] == "treatment").astype(int)
    return panel


# --------------------------------------------------------------------------------------
# DiD estimation
# --------------------------------------------------------------------------------------
def did_regression(panel: pd.DataFrame, outcome: str = "spend") -> dict:
    """Run the 2x2 DiD OLS with HC1 robust SEs; return a tidy result dict."""
    model = smf.ols(f"{outcome} ~ post * treat", data=panel).fit(cov_type="HC1")
    b = model.params["post:treat"]
    se = model.bse["post:treat"]
    ci_low, ci_high = model.conf_int().loc["post:treat"].tolist()
    p = model.pvalues["post:treat"]

    # Baseline (control pre) mean and treatment-group pre mean for lift framing.
    ctrl_pre = panel.query("treat == 0 and post == 0")[outcome].mean()
    treat_pre = panel.query("treat == 1 and post == 0")[outcome].mean()
    treat_post = panel.query("treat == 1 and post == 1")[outcome].mean()

    # Counterfactual treatment-post spend = treat_pre + control's pre->post change.
    ctrl_post = panel.query("treat == 0 and post == 1")[outcome].mean()
    counterfactual = treat_pre + (ctrl_post - ctrl_pre)
    lift_pct = b / counterfactual if counterfactual else np.nan

    return {
        "outcome": outcome,
        "n_obs": int(model.nobs),
        "did_estimate": b,
        "std_error": se,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "p_value": p,
        "significant_5pct": bool(p < C.SIG_LEVEL),
        "control_pre_mean": ctrl_pre,
        "control_post_mean": ctrl_post,
        "treat_pre_mean": treat_pre,
        "treat_post_mean": treat_post,
        "counterfactual_treat_post": counterfactual,
        "lift_pct": lift_pct,
    }


def parallel_trends_check(customers: pd.DataFrame, txn: pd.DataFrame) -> dict:
    """Placebo DiD using only the pre period.

    Split the 8 pre-period weeks into an early half and a late half and run the
    same DiD. A well-behaved experiment shows a small, non-significant estimate:
    treatment and control were already moving together before the promotion.
    """
    pre = txn[txn["study_week"] <= C.PRE_WEEKS].copy()
    half = C.PRE_WEEKS // 2
    pre["pseudo_post"] = (pre["study_week"] > half).astype(int)

    agg = (
        pre.groupby(["customer_id", "pseudo_post"])["amount"].sum().reset_index(name="spend")
    )
    idx = pd.MultiIndex.from_product(
        [customers["customer_id"], [0, 1]], names=["customer_id", "pseudo_post"]
    )
    agg = agg.set_index(["customer_id", "pseudo_post"]).reindex(idx, fill_value=0.0).reset_index()
    agg = agg.merge(customers[["customer_id", "group"]], on="customer_id")
    agg["treat"] = (agg["group"] == "treatment").astype(int)

    m = smf.ols("spend ~ pseudo_post * treat", data=agg).fit(cov_type="HC1")
    return {
        "placebo_did_estimate": m.params["pseudo_post:treat"],
        "placebo_std_error": m.bse["pseudo_post:treat"],
        "placebo_p_value": m.pvalues["pseudo_post:treat"],
        "placebo_passes": bool(m.pvalues["pseudo_post:treat"] > C.SIG_LEVEL),
    }


def did_by_segment(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for seg in C.SEGMENTS:
        sub = panel[panel["segment"] == seg]
        r_total = did_regression(sub, "spend")
        r_elig = did_regression(sub, "eligible_spend")
        n_treat = sub.query("treat == 1 and post == 0").shape[0]
        rows.append(
            {
                "segment": seg,
                "n_customers": sub["customer_id"].nunique(),
                "n_treatment_customers": n_treat,
                "did_spend_per_cust": r_total["did_estimate"],
                "ci_low": r_total["ci_low"],
                "ci_high": r_total["ci_high"],
                "p_value": r_total["p_value"],
                "significant_5pct": r_total["significant_5pct"],
                "lift_pct": r_total["lift_pct"],
                "counterfactual_spend_per_cust": r_total["counterfactual_treat_post"],
                # eligible-category spend is the PRIMARY outcome: the promotion acts
                # directly on Dining + Entertainment, so identification is cleanest and
                # power is highest there. Total spend (above) carries the halo effect
                # but is noisier.
                "did_eligible_spend_per_cust": r_elig["did_estimate"],
                "eligible_ci_low": r_elig["ci_low"],
                "eligible_ci_high": r_elig["ci_high"],
                "eligible_p_value": r_elig["p_value"],
                "eligible_significant_5pct": r_elig["significant_5pct"],
                "eligible_lift_pct": r_elig["lift_pct"],
                "counterfactual_eligible_spend_per_cust": r_elig["counterfactual_treat_post"],
                # halo = total effect minus eligible effect (spend moved in other categories)
                "halo_spend_per_cust": r_total["did_estimate"] - r_elig["did_estimate"],
            }
        )
    return pd.DataFrame(rows)


def did_by_dimension(panel: pd.DataFrame, dim: str) -> pd.DataFrame:
    rows = []
    for val in sorted(panel[dim].unique()):
        sub = panel[panel[dim] == val]
        r = did_regression(sub, "spend")
        rows.append(
            {
                dim: val,
                "n_customers": sub["customer_id"].nunique(),
                "did_spend_per_cust": r["did_estimate"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "p_value": r["p_value"],
                "significant_5pct": r["significant_5pct"],
                "lift_pct": r["lift_pct"],
                "counterfactual_spend_per_cust": r["counterfactual_treat_post"],
            }
        )
    return pd.DataFrame(rows)


def weekly_timeseries(txn: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    n_by_group = customers.groupby("group")["customer_id"].nunique()
    ts = (
        txn.groupby(["study_week", "group"])
        .agg(spend=("amount", "sum"), txns=("amount", "size"))
        .reset_index()
    )
    ts["spend_per_customer"] = ts.apply(
        lambda r: r["spend"] / n_by_group[r["group"]], axis=1
    )
    ts["period"] = np.where(ts["study_week"] <= C.PRE_WEEKS, "pre", "post")
    ts["promotion_active"] = ts["study_week"] > C.PRE_WEEKS
    return ts


# --------------------------------------------------------------------------------------
def main() -> None:
    customers, txn = load()
    panel = build_customer_period_panel(customers, txn)
    panel.to_csv(C.OUT_ANALYSIS / "customer_period_panel.csv", index=False)

    # ---- headline -------------------------------------------------------------------
    headline_total = did_regression(panel, "spend")
    headline_elig = did_regression(panel, "eligible_spend")
    placebo = parallel_trends_check(customers, txn)

    overall = {**headline_total, **placebo,
               "eligible_did_estimate": headline_elig["did_estimate"],
               "eligible_ci_low": headline_elig["ci_low"],
               "eligible_ci_high": headline_elig["ci_high"],
               "eligible_p_value": headline_elig["p_value"]}
    pd.DataFrame([overall]).to_csv(C.OUT_ANALYSIS / "did_overall.csv", index=False)

    seg = did_by_segment(panel)
    seg.to_csv(C.OUT_ANALYSIS / "did_by_segment.csv", index=False)

    reg = did_by_dimension(panel, "region")
    reg.to_csv(C.OUT_ANALYSIS / "did_by_region.csv", index=False)

    # category-level: DiD on spend within each merchant category (transaction panel)
    cat_rows = []
    for cat in C.CATEGORY_TICKET_FACTOR:
        cat_txn = txn[txn["merchant_category"] == cat]
        cat_agg = (
            cat_txn.groupby(["customer_id", "period"])["amount"].sum().reset_index(name="spend")
        )
        idx = pd.MultiIndex.from_product(
            [customers["customer_id"], ["pre", "post"]], names=["customer_id", "period"]
        )
        cat_agg = (
            cat_agg.set_index(["customer_id", "period"]).reindex(idx, fill_value=0.0).reset_index()
        )
        cat_agg = cat_agg.merge(customers[["customer_id", "group"]], on="customer_id")
        cat_agg["post"] = (cat_agg["period"] == "post").astype(int)
        cat_agg["treat"] = (cat_agg["group"] == "treatment").astype(int)
        r = did_regression(cat_agg, "spend")
        cat_rows.append(
            {
                "merchant_category": cat,
                "is_eligible": cat in C.ELIGIBLE_CATEGORIES,
                "did_spend_per_cust": r["did_estimate"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
                "p_value": r["p_value"],
                "significant_5pct": r["significant_5pct"],
                "lift_pct": r["lift_pct"],
            }
        )
    pd.DataFrame(cat_rows).to_csv(C.OUT_ANALYSIS / "did_by_category.csv", index=False)

    ts = weekly_timeseries(txn, customers)
    ts.to_csv(C.OUT_ANALYSIS / "weekly_timeseries.csv", index=False)

    # ---- console report ------------------------------------------------------------
    def money(x): return f"${x:,.2f}"
    print("=" * 78)
    print(f"DIFFERENCE-IN-DIFFERENCES  -  headline read (spend per customer, {C.POST_WEEKS} weeks)")
    print("=" * 78)
    print(f"  Control  : pre {money(headline_total['control_pre_mean'])}  ->  post {money(headline_total['control_post_mean'])}"
          f"   (+{money(headline_total['control_post_mean'] - headline_total['control_pre_mean'])})")
    print(f"  Treatment: pre {money(headline_total['treat_pre_mean'])}  ->  post {money(headline_total['treat_post_mean'])}"
          f"   (+{money(headline_total['treat_post_mean'] - headline_total['treat_pre_mean'])})")
    print(f"  DiD estimate (incremental spend) : {money(headline_total['did_estimate'])} per customer")
    print(f"  95% CI                           : [{money(headline_total['ci_low'])}, {money(headline_total['ci_high'])}]")
    print(f"  p-value                          : {headline_total['p_value']:.2e}")
    print(f"  implied lift vs. counterfactual  : {headline_total['lift_pct']*100:.1f}%")
    print()
    print(f"  Eligible-category DiD            : {money(headline_elig['did_estimate'])}  "
          f"(95% CI [{money(headline_elig['ci_low'])}, {money(headline_elig['ci_high'])}], p={headline_elig['p_value']:.2e})")
    print()
    print("PARALLEL-TRENDS / PLACEBO CHECK (pre period only)")
    print(f"  placebo DiD estimate : {money(placebo['placebo_did_estimate'])}  "
          f"(p={placebo['placebo_p_value']:.3f})  ->  "
          f"{'PASS - no pre-trend' if placebo['placebo_passes'] else 'FAIL - pre-trend present'}")
    print()
    print("BY SEGMENT  -  primary outcome = eligible-category spend (Dining + Entertainment)")
    show = pd.DataFrame({
        "segment": seg["segment"],
        "customers": seg["n_customers"],
        "elig_DiD_$": seg["did_eligible_spend_per_cust"].map(lambda v: f"{v:,.2f}"),
        "elig_95%CI": [f"[{lo:,.0f}, {hi:,.0f}]" for lo, hi in
                       zip(seg["eligible_ci_low"], seg["eligible_ci_high"])],
        "elig_p": seg["eligible_p_value"].map(lambda v: f"{v:.3f}"),
        "elig_sig": seg["eligible_significant_5pct"],
        "elig_lift": (seg["eligible_lift_pct"] * 100).map(lambda v: f"{v:.1f}%"),
        "halo_$": seg["halo_spend_per_cust"].map(lambda v: f"{v:,.0f}"),
        "total_DiD_$": seg["did_spend_per_cust"].map(lambda v: f"{v:,.0f}"),
    })
    print(show.to_string(index=False))
    print()
    print("Wrote:", ", ".join(p.name for p in sorted(C.OUT_ANALYSIS.glob("*.csv"))))
    print("\nNext: python src/economics.py")


if __name__ == "__main__":
    main()
