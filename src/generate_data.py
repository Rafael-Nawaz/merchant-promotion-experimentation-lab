"""
Step 1 - Generate synthetic card-transaction data for the experiment.

Output files (written to ./data):
  - customers.csv            one row per customer (10,000 rows)
  - transactions.csv         one row per transaction (~448,000 rows)
  - promotion_calendar.csv   reference table describing the study periods

Overview
--------
10,000 cardholders are randomised ~50/50 into a treatment and a control group.
The data covers 12 weeks of spend before a cashback promotion launches ("pre")
and 12 weeks after ("post"). During the post period, treatment-group customers
earn 3% cashback on Dining and Entertainment. Every customer also experiences a
common +3% seasonal lift in the post period regardless of group - the confound
that difference-in-differences removes. Each customer segment has its own true
response to the promotion, ranging from strong (Digital Native) to negligible
(Budget Occasional).

The true segment responses are parameters in config.py and are not referenced
anywhere in the analysis; the analysis recovers them from the data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as C


def _rng() -> np.random.Generator:
    return np.random.default_rng(C.SEED)


# --------------------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------------------
def build_customers(rng: np.random.Generator) -> pd.DataFrame:
    seg_names = list(C.SEGMENTS)
    seg_probs = np.array([C.SEGMENTS[s]["share"] for s in seg_names])
    seg_probs = seg_probs / seg_probs.sum()

    region_names = list(C.REGIONS)
    region_probs = np.array([C.REGIONS[r] for r in region_names])
    region_probs = region_probs / region_probs.sum()

    n = C.N_CUSTOMERS
    segment = rng.choice(seg_names, size=n, p=seg_probs)
    region = rng.choice(region_names, size=n, p=region_probs)

    # Randomised assignment. Treatment is a coin flip, independent of everything else,
    # so the pre-period groups are balanced by construction.
    group = np.where(rng.random(n) < C.TREATMENT_SHARE, "treatment", "control")

    # Per-customer activity multiplier (some people just spend more).
    shape = C.CUSTOMER_HETEROGENEITY_SHAPE
    activity = rng.gamma(shape=shape, scale=1.0 / shape, size=n)

    tenure_months = rng.integers(3, 121, size=n)

    customers = pd.DataFrame(
        {
            "customer_id": np.arange(1, n + 1),
            "segment": segment,
            "region": region,
            "group": group,
            "tenure_months": tenure_months,
            "activity_index": activity.round(4),
        }
    )
    return customers


# --------------------------------------------------------------------------------------
# Category weights per segment
# --------------------------------------------------------------------------------------
def category_weights(seg: str) -> dict[str, float]:
    """Transaction-share weights across all 8 categories for a segment."""
    p = C.SEGMENTS[seg]
    elig = p["eligible_wallet_share"]
    weights = {
        "Dining": elig * 0.60,
        "Entertainment": elig * 0.40,
    }
    non_elig_total = 1.0 - elig
    for cat, frac in C.NON_ELIGIBLE_MIX.items():
        weights[cat] = non_elig_total * frac
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


# --------------------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------------------
def build_transactions(customers: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    weeks = C.PRE_WEEKS + C.POST_WEEKS
    categories = list(C.CATEGORY_TICKET_FACTOR)

    seg_cat_w = {s: category_weights(s) for s in C.SEGMENTS}

    rows_cust, rows_date, rows_cat, rows_amt, rows_cb = [], [], [], [], []
    rows_period, rows_week = [], []

    study_start = pd.Timestamp(C.STUDY_START)
    promo_start = pd.Timestamp(C.PROMO_START)

    # Vectorise per (segment, group) block for speed; still one Poisson draw per
    # customer-week-category which keeps the data believable.
    for cust in customers.itertuples(index=False):
        seg = cust.segment
        p = C.SEGMENTS[seg]
        base_rate = (
            p["base_weekly_txn"]
            * cust.activity_index
            * C.REGION_SPEND_FACTOR[cust.region]
        )
        cat_w = seg_cat_w[seg]
        base_ticket = p["base_ticket"] * C.REGION_SPEND_FACTOR[cust.region]
        is_treat = cust.group == "treatment"
        lift_e = p["true_lift_eligible"]
        halo = p["true_halo_other"]

        for wk in range(weeks):
            is_post = wk >= C.PRE_WEEKS
            week_start = study_start + pd.Timedelta(weeks=wk)
            period = "post" if is_post else "pre"

            for cat in categories:
                rate = base_rate * cat_w[cat]
                if is_post:
                    rate *= C.COMMON_POST_TREND
                    if is_treat:
                        if cat in C.ELIGIBLE_CATEGORIES:
                            rate *= 1.0 + lift_e
                        else:
                            rate *= 1.0 + halo

                n_txn = rng.poisson(rate)
                if n_txn == 0:
                    continue

                mean_ticket = base_ticket * C.CATEGORY_TICKET_FACTOR[cat]
                mu = np.log(mean_ticket) - 0.5 * C.TICKET_LOGNORMAL_SIGMA ** 2
                amounts = rng.lognormal(mu, C.TICKET_LOGNORMAL_SIGMA, size=n_txn)
                amounts = np.round(amounts, 2)

                # Spread the transactions across the 7 days of the week.
                day_offsets = rng.integers(0, 7, size=n_txn)

                eligible_now = is_treat and is_post and cat in C.ELIGIBLE_CATEGORIES
                cashback = (
                    np.round(amounts * C.CASHBACK_RATE, 2)
                    if eligible_now
                    else np.zeros(n_txn)
                )

                for j in range(n_txn):
                    rows_cust.append(cust.customer_id)
                    rows_date.append(week_start + pd.Timedelta(days=int(day_offsets[j])))
                    rows_cat.append(cat)
                    rows_amt.append(amounts[j])
                    rows_cb.append(cashback[j])
                    rows_period.append(period)
                    rows_week.append(wk + 1)

    txn = pd.DataFrame(
        {
            "customer_id": rows_cust,
            "txn_date": rows_date,
            "merchant_category": rows_cat,
            "amount": rows_amt,
            "cashback_earned": rows_cb,
            "period": rows_period,
            "study_week": rows_week,
        }
    )
    txn = txn.sort_values(["txn_date", "customer_id"]).reset_index(drop=True)
    txn.insert(0, "transaction_id", np.arange(1, len(txn) + 1))

    # Denormalise a few customer attributes onto the transaction table. A warehouse
    # would keep these on a dimension table; a flat file keeps the CSV and Tableau
    # workflow simple.
    txn = txn.merge(
        customers[["customer_id", "segment", "region", "group"]],
        on="customer_id",
        how="left",
    )
    txn["is_eligible_category"] = txn["merchant_category"].isin(C.ELIGIBLE_CATEGORIES)
    return txn


def build_promo_calendar() -> pd.DataFrame:
    rows = []
    study_start = pd.Timestamp(C.STUDY_START)
    for wk in range(C.PRE_WEEKS + C.POST_WEEKS):
        ws = study_start + pd.Timedelta(weeks=wk)
        rows.append(
            {
                "study_week": wk + 1,
                "week_start": ws.date(),
                "period": "post" if wk >= C.PRE_WEEKS else "pre",
                "promotion_active": wk >= C.PRE_WEEKS,
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
def main() -> None:
    rng = _rng()
    print("Generating customers ...")
    customers = build_customers(rng)
    customers.to_csv(C.CUSTOMERS_CSV, index=False)

    print("Generating transactions (this takes ~20-40s) ...")
    txn = build_transactions(customers, rng)
    txn.to_csv(C.TRANSACTIONS_CSV, index=False)

    build_promo_calendar().to_csv(C.PROMO_CALENDAR_CSV, index=False)

    # ---- quick sanity summary (not the analysis) -------------------------------------
    n = len(txn)
    print("\n=== Data generated ===")
    print(f"customers        : {len(customers):,}")
    print(f"transactions     : {n:,}")
    print(f"date range       : {txn.txn_date.min().date()} -> {txn.txn_date.max().date()}")
    print(f"total spend      : ${txn.amount.sum():,.0f}")
    print(f"total cashback   : ${txn.cashback_earned.sum():,.0f}")
    print("\ngroup balance (customers):")
    print(customers.group.value_counts().to_string())
    print("\nnaive before/after by group ($ spend per customer per period):")
    piv = (
        txn.groupby(["group", "period"])["amount"].sum()
        / customers.groupby("group").size().reindex(["control", "treatment"]).repeat(2).values
    )
    print(piv.to_string())
    print("\nNext step: python src/analysis_did.py")


if __name__ == "__main__":
    main()
