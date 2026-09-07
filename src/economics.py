"""
Step 3 - Promotion economics.

Reads  : outputs/analysis/did_by_segment.csv, did_overall.csv, data/transactions.csv
Writes : outputs/analysis/economics_by_segment.csv, economics_overall.csv

Framing
-------
The promotion pays 3% cashback on Dining + Entertainment, so the effect it can be
credited with, cleanly, is the difference-in-differences estimate on
eligible-category spend. The economics are built on that number:

    incremental eligible spend  = DiD(eligible spend) x treated customers
    promotion cost              = actual cashback paid to treated customers
    incremental margin          = contribution margin x incremental eligible spend
    net benefit                 = incremental margin - promotion cost
    ROI                         = net benefit / promotion cost
    break-even lift             = the eligible-spend lift at which net benefit = 0

The "halo" - extra spend in non-eligible categories - is reported separately as
upside, because in this experiment it is not individually statistically reliable
and a merchant should not fund a promotion on the strength of it.

A segment is only recommended for targeting if its eligible-spend DiD is
statistically significant (95%) AND its identified ROI is positive.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as C


def promo_cost_by_segment(txn: pd.DataFrame) -> pd.Series:
    paid = txn[(txn["group"] == "treatment") & (txn["period"] == "post")]
    return paid.groupby("segment")["cashback_earned"].sum() * C.MERCHANT_FUNDING_SHARE


def _roi(incr_spend: float, promo_cost: float) -> dict:
    margin = C.CONTRIBUTION_MARGIN * incr_spend
    net = margin - promo_cost
    return {
        "incremental_margin": margin,
        "net_benefit": net,
        "roi": net / promo_cost if promo_cost > 0 else np.nan,
    }


def _verdict(elig_sig: bool, roi_identified: float) -> str:
    if not elig_sig:
        return "No statistically reliable lift - cashback would fund inframarginal spend"
    if roi_identified >= 0.15:
        return "Significant lift, clearly positive ROI - target / expand"
    if roi_identified >= 0.0:
        return "Significant lift, ROI near break-even - optimise offer before scaling"
    return "Significant lift but negative ROI at this cashback rate - do not expand"


def build_segment_economics() -> pd.DataFrame:
    seg = pd.read_csv(C.OUT_ANALYSIS / "did_by_segment.csv")
    txn = pd.read_csv(C.TRANSACTIONS_CSV)
    cost = promo_cost_by_segment(txn)

    rows = []
    for _, r in seg.iterrows():
        s = r["segment"]
        n = r["n_treatment_customers"]
        promo_cost = float(cost.get(s, 0.0))

        incr_elig = r["did_eligible_spend_per_cust"] * n
        incr_elig_low = r["eligible_ci_low"] * n
        incr_elig_high = r["eligible_ci_high"] * n
        halo = r["halo_spend_per_cust"] * n

        cf_elig_total = r["counterfactual_eligible_spend_per_cust"] * n

        base = _roi(incr_elig, promo_cost)
        low = _roi(incr_elig_low, promo_cost)
        high = _roi(incr_elig_high, promo_cost)
        with_halo = _roi(incr_elig + max(halo, 0.0), promo_cost)

        be_spend = promo_cost / C.CONTRIBUTION_MARGIN
        be_lift = be_spend / cf_elig_total if cf_elig_total else np.nan

        rows.append(
            {
                "segment": s,
                "n_treatment_customers": int(n),
                "did_eligible_spend_per_cust": r["did_eligible_spend_per_cust"],
                "eligible_p_value": r["eligible_p_value"],
                "eligible_significant_5pct": bool(r["eligible_significant_5pct"]),
                "eligible_lift_pct": r["eligible_lift_pct"],
                "incremental_eligible_spend": incr_elig,
                "incremental_eligible_spend_ci_low": incr_elig_low,
                "incremental_eligible_spend_ci_high": incr_elig_high,
                "halo_spend": halo,
                "counterfactual_eligible_spend": cf_elig_total,
                "promotion_cost": promo_cost,
                "cashback_rate": C.CASHBACK_RATE,
                "contribution_margin": C.CONTRIBUTION_MARGIN,
                "incremental_margin": base["incremental_margin"],
                "net_benefit": base["net_benefit"],
                "roi": base["roi"],
                "roi_ci_low": low["roi"],
                "roi_ci_high": high["roi"],
                "roi_with_halo": with_halo["roi"],
                "net_benefit_with_halo": with_halo["net_benefit"],
                "breakeven_eligible_spend": be_spend,
                "breakeven_eligible_lift_pct": be_lift,
                "recommended_target": bool(r["eligible_significant_5pct"]
                                           and r["did_eligible_spend_per_cust"] > 0
                                           and base["roi"] > 0),
                "verdict": _verdict(bool(r["eligible_significant_5pct"]), base["roi"]),
            }
        )
    return pd.DataFrame(rows)


def build_overall_economics(seg_econ: pd.DataFrame) -> pd.DataFrame:
    def block(df: pd.DataFrame, label: str) -> dict:
        incr = df["incremental_eligible_spend"].sum()
        incr_low = df["incremental_eligible_spend_ci_low"].sum()
        incr_high = df["incremental_eligible_spend_ci_high"].sum()
        halo = df["halo_spend"].clip(lower=0).sum()
        cost = df["promotion_cost"].sum()
        b = _roi(incr, cost)
        return {
            "scenario": label,
            "segments": ", ".join(df["segment"]),
            "incremental_eligible_spend": incr,
            "incremental_eligible_spend_ci_low": incr_low,
            "incremental_eligible_spend_ci_high": incr_high,
            "halo_spend": halo,
            "promotion_cost": cost,
            "incremental_margin": b["incremental_margin"],
            "net_benefit": b["net_benefit"],
            "roi": b["roi"],
            "roi_ci_low": _roi(incr_low, cost)["roi"],
            "roi_ci_high": _roi(incr_high, cost)["roi"],
            "roi_with_halo": _roi(incr + halo, cost)["roi"],
        }

    targeted = seg_econ[seg_econ["recommended_target"]]
    return pd.DataFrame([
        block(seg_econ, "All treated segments (as tested)"),
        block(targeted if len(targeted) else seg_econ.iloc[0:0], "Targeted (recommended segments only)"),
    ])


def main() -> None:
    seg_econ = build_segment_economics()
    seg_econ.to_csv(C.OUT_ANALYSIS / "economics_by_segment.csv", index=False)
    overall = build_overall_economics(seg_econ)
    overall.to_csv(C.OUT_ANALYSIS / "economics_overall.csv", index=False)

    def m(x): return f"${x:,.0f}"
    def p(x): return f"{x*100:,.0f}%" if pd.notna(x) else "n/a"

    print("=" * 100)
    print(f"PROMOTION ECONOMICS  -  per treated customer group, one {C.POST_WEEKS}-week promo window")
    print("  (identified effect = difference-in-differences on eligible-category spend)")
    print("=" * 100)
    cols = ["segment", "eligible_significant_5pct", "incremental_eligible_spend", "halo_spend",
            "promotion_cost", "incremental_margin", "net_benefit", "roi",
            "roi_with_halo", "breakeven_eligible_lift_pct"]
    disp = seg_econ[cols].copy()
    for c in ["incremental_eligible_spend", "halo_spend", "promotion_cost",
              "incremental_margin", "net_benefit"]:
        disp[c] = disp[c].map(m)
    disp["roi"] = seg_econ["roi"].map(p)
    disp["roi_with_halo"] = seg_econ["roi_with_halo"].map(p)
    disp["breakeven_eligible_lift_pct"] = seg_econ["breakeven_eligible_lift_pct"].map(p)
    print(disp.to_string(index=False))
    print()
    for _, r in overall.iterrows():
        print(f"  {r['scenario']}  [{r['segments']}]")
        print(f"     incremental eligible spend : {m(r['incremental_eligible_spend'])}  "
              f"(95% CI {m(r['incremental_eligible_spend_ci_low'])} .. {m(r['incremental_eligible_spend_ci_high'])})")
        print(f"     promotion cost             : {m(r['promotion_cost'])}")
        print(f"     incremental margin         : {m(r['incremental_margin'])}")
        print(f"     net benefit                : {m(r['net_benefit'])}")
        print(f"     ROI (identified)           : {p(r['roi'])}   "
              f"(95% CI {p(r['roi_ci_low'])} .. {p(r['roi_ci_high'])})")
        print(f"     ROI (incl. halo upside)    : {p(r['roi_with_halo'])}")
        print()
    print("Verdicts:")
    for _, r in seg_econ.iterrows():
        print(f"   {r['segment']:22s} {r['verdict']}")
    print("\nWrote economics_by_segment.csv, economics_overall.csv")


if __name__ == "__main__":
    main()
