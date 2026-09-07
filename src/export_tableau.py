"""
Step 5 - Prepare clean, Tableau-ready extracts.

Reads  : data/*.csv, outputs/analysis/*.csv
Writes : outputs/tableau/*.csv

Each file is tidy (one row per observation, no merged headers, no totals rows) so it
can be dropped straight into Tableau Public. See dashboard/TABLEAU_INSTRUCTIONS.md
for how the sheets and dashboard are built from these.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as C


def main() -> None:
    customers = pd.read_csv(C.CUSTOMERS_CSV)
    txn = pd.read_csv(C.TRANSACTIONS_CSV, parse_dates=["txn_date"])
    panel = pd.read_csv(C.OUT_ANALYSIS / "customer_period_panel.csv")
    seg_did = pd.read_csv(C.OUT_ANALYSIS / "did_by_segment.csv")
    seg_econ = pd.read_csv(C.OUT_ANALYSIS / "economics_by_segment.csv")
    region_did = pd.read_csv(C.OUT_ANALYSIS / "did_by_region.csv")
    cat_did = pd.read_csv(C.OUT_ANALYSIS / "did_by_category.csv")
    ts = pd.read_csv(C.OUT_ANALYSIS / "weekly_timeseries.csv")
    overall = pd.read_csv(C.OUT_ANALYSIS / "did_overall.csv").iloc[0]

    T = C.OUT_TABLEAU

    # 1) Customer x period panel - the workhorse extract for most views ---------------
    panel_out = panel[[
        "customer_id", "period", "segment", "region", "group",
        "spend", "txns", "eligible_spend",
    ]].copy()
    panel_out.rename(columns={"group": "test_group"}, inplace=True)
    panel_out.to_csv(T / "fact_customer_period.csv", index=False)

    # 2) Transaction extract (sampled to keep Tableau Public happy) -------------------
    sample = txn.sample(n=min(60_000, len(txn)), random_state=C.SEED)
    sample = sample[[
        "txn_date", "customer_id", "segment", "region", "group",
        "merchant_category", "is_eligible_category", "period",
        "study_week", "amount", "cashback_earned",
    ]].rename(columns={"group": "test_group"})
    sample.sort_values("txn_date").to_csv(T / "fact_transactions_sample.csv", index=False)

    # 3) Weekly time series by group (parallel-trends + lift-over-time visual) --------
    ts_out = ts.rename(columns={"group": "test_group"})[
        ["study_week", "test_group", "period", "promotion_active",
         "spend", "txns", "spend_per_customer"]
    ]
    ts_out.to_csv(T / "trend_weekly_by_group.csv", index=False)

    # 4) DiD by segment -------------------------------------------------------------
    seg = seg_did.merge(
        seg_econ[["segment", "incremental_eligible_spend", "halo_spend", "promotion_cost",
                  "incremental_margin", "net_benefit", "roi", "roi_ci_low", "roi_ci_high",
                  "roi_with_halo", "breakeven_eligible_lift_pct",
                  "recommended_target", "verdict"]],
        on="segment", how="left",
    )
    seg["recommendation"] = np.where(
        seg["recommended_target"], "TARGET",
        np.where(seg["did_eligible_spend_per_cust"] < 0, "EXCLUDE", "DO NOT TARGET"),
    )
    seg.to_csv(T / "did_by_segment.csv", index=False)

    # 5) DiD by region ------------------------------------------------------------
    region_did.to_csv(T / "did_by_region.csv", index=False)

    # 6) DiD by merchant category ------------------------------------------------
    cat_did.to_csv(T / "did_by_category.csv", index=False)

    # 7) Segment x region incremental spend heat grid --------------------------
    grid = []
    for seg_name in C.SEGMENTS:
        for reg in C.REGIONS:
            sub = panel[(panel["segment"] == seg_name) & (panel["region"] == reg)]
            wide = sub.pivot_table(index="group", columns="period", values="spend", aggfunc="mean")
            if wide.shape != (2, 2):
                continue
            did = (wide.loc["treatment", "post"] - wide.loc["treatment", "pre"]) - (
                wide.loc["control", "post"] - wide.loc["control", "pre"]
            )
            grid.append({"segment": seg_name, "region": reg, "did_spend_per_cust": did})
    pd.DataFrame(grid).to_csv(T / "did_segment_region_grid.csv", index=False)

    # 8) One-row experiment scorecard for KPI tiles ----------------------------
    tested = seg_econ
    targeted = tested[tested["recommended_target"]]

    def roi(df):
        c = df["promotion_cost"].sum()
        return float((C.CONTRIBUTION_MARGIN * df["incremental_eligible_spend"].sum() - c) / c) if c else np.nan

    scorecard = pd.DataFrame([{
        "customers_in_test": int(customers.shape[0]),
        "transactions_analysed": int(len(txn)),
        "did_spend_per_customer": float(overall["did_estimate"]),
        "did_ci_low": float(overall["ci_low"]),
        "did_ci_high": float(overall["ci_high"]),
        "did_p_value": float(overall["p_value"]),
        "did_significant": bool(overall["significant_5pct"]),
        "eligible_did_per_customer": float(overall["eligible_did_estimate"]),
        "eligible_did_p_value": float(overall["eligible_p_value"]),
        "parallel_trends_pass": bool(overall["placebo_passes"]),
        "total_incremental_eligible_spend": float(tested["incremental_eligible_spend"].sum()),
        "total_halo_spend": float(tested["halo_spend"].clip(lower=0).sum()),
        "total_promotion_cost": float(tested["promotion_cost"].sum()),
        "overall_net_benefit": float(tested["net_benefit"].sum()),
        "overall_roi": roi(tested),
        "targeted_net_benefit": float(targeted["net_benefit"].sum()),
        "targeted_roi": roi(targeted),
        "n_segments_recommended": int(targeted.shape[0]),
        "segments_recommended": ", ".join(targeted["segment"]) or "(none)",
    }])
    scorecard.to_csv(T / "experiment_scorecard.csv", index=False)

    print("Tableau extracts written to", T)
    for p in sorted(T.glob("*.csv")):
        print(f"  {p.name:36s} {p.stat().st_size/1024:8.1f} KB")


if __name__ == "__main__":
    main()
