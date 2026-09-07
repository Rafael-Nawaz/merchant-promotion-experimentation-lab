"""
Step 4 - Build the Excel scenario model.

Reads  : outputs/analysis/economics_by_segment.csv, did_by_segment.csv
Writes : outputs/excel/promotion_scenario_model.xlsx

The workbook is a live model: the Scenario Model sheet is built from Excel
formulas that reference the Assumptions sheet, so changing the cashback rate,
margin, rollout size or lift estimate recalculates ROI and break-even.

Scenarios (all applied to the targeted / recommended segments only):
  Conservative : incremental eligible spend per customer = lower bound of 95% CI
  Base         : incremental eligible spend per customer = DiD point estimate
  Upside       : incremental eligible spend per customer = upper bound of 95% CI
Halo spend in non-eligible categories is shown as a separate upside line, not
baked into the headline ROI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xlsxwriter

import config as C


def targeted_inputs() -> dict:
    seg = pd.read_csv(C.OUT_ANALYSIS / "did_by_segment.csv")
    econ = pd.read_csv(C.OUT_ANALYSIS / "economics_by_segment.csv")

    keep = econ[econ["recommended_target"]].copy()
    if keep.empty:
        # fall back to any segment with a significant positive eligible-spend lift
        keep = econ[econ["eligible_significant_5pct"] & (econ["did_eligible_spend_per_cust"] > 0)].copy()
    keep_seg = seg[seg["segment"].isin(keep["segment"])]

    n_treat = keep["n_treatment_customers"].sum()
    tested_pop = seg["n_customers"].sum()
    targeted_share = keep_seg["n_customers"].sum() / tested_pop

    incr_base = keep["incremental_eligible_spend"].sum() / n_treat
    incr_low = keep["incremental_eligible_spend_ci_low"].sum() / n_treat
    incr_high = keep["incremental_eligible_spend_ci_high"].sum() / n_treat
    halo_per_cust = keep["halo_spend"].clip(lower=0).sum() / n_treat
    cost_per_cust = keep["promotion_cost"].sum() / n_treat
    cf_per_cust = keep["counterfactual_eligible_spend"].sum() / n_treat

    return {
        "segments": ", ".join(keep["segment"]),
        "targeted_share": targeted_share,
        "targeted_population": round(C.ROLLOUT_ELIGIBLE_CUSTOMERS * targeted_share),
        "windows_per_year": C.PROMO_PERIODS_PER_YEAR,
        "incr_per_cust_low": incr_low,
        "incr_per_cust_base": incr_base,
        "incr_per_cust_high": incr_high,
        "halo_per_cust": halo_per_cust,
        "cost_per_cust": cost_per_cust,
        "counterfactual_per_cust": cf_per_cust,
    }


def build() -> None:
    ti = targeted_inputs()
    path = C.OUT_EXCEL / "promotion_scenario_model.xlsx"
    wb = xlsxwriter.Workbook(path)

    money = wb.add_format({"num_format": "$#,##0"})
    pct = wb.add_format({"num_format": "0.0%"})
    pct0 = wb.add_format({"num_format": "0%"})
    num = wb.add_format({"num_format": "#,##0"})
    bold = wb.add_format({"bold": True})
    title = wb.add_format({"bold": True, "font_size": 14})
    hdr = wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white", "border": 1})
    inp_m = wb.add_format({"bg_color": "#FFF2CC", "border": 1, "num_format": "$#,##0.00"})
    inp_p = wb.add_format({"bg_color": "#FFF2CC", "border": 1, "num_format": "0.0%"})
    inp_n = wb.add_format({"bg_color": "#FFF2CC", "border": 1, "num_format": "#,##0"})
    money2 = wb.add_format({"num_format": "$#,##0.00"})

    # ---------------------------------------------------------------- Assumptions ----
    a = wb.add_worksheet("Assumptions")
    a.set_column("A:A", 46)
    a.set_column("B:B", 16)
    a.set_column("C:C", 58)
    a.write("A1", "Promotion Scenario Model - Assumptions", title)
    a.write("A2", "Yellow cells are inputs. The Scenario Model sheet is entirely formula-driven.")

    rows = [
        ("Cashback rate", C.CASHBACK_RATE, inp_p,
         "Cashback paid to cardholder on eligible spend"),
        ("Contribution margin on incremental spend", C.CONTRIBUTION_MARGIN, inp_p,
         "Rate at which incremental revenue becomes profit"),
        ("Merchant funding share of cashback", C.MERCHANT_FUNDING_SHARE, inp_p,
         "1.0 = merchant pays the entire cashback bill"),
        ("Targeted population (customers)", ti["targeted_population"], inp_n,
         f"Rollout base x targeted share ({ti['targeted_share']:.0%}); segments: {ti['segments']}"),
        ("Promo windows per year", ti["windows_per_year"], inp_n,
         f"Number of {C.POST_WEEKS}-week promotion windows run annually"),
        ("Counterfactual eligible spend / customer / window", ti["counterfactual_per_cust"], inp_m,
         "Dining+Entertainment spend WITHOUT the promo (from DiD)"),
        ("Promotion cost / customer / window", ti["cost_per_cust"], inp_m,
         "Actual cashback paid per treated customer in the pilot"),
        ("Incremental eligible spend / cust / window - CONSERVATIVE", ti["incr_per_cust_low"], inp_m,
         "Lower bound of the 95% CI on the DiD estimate"),
        ("Incremental eligible spend / cust / window - BASE", ti["incr_per_cust_base"], inp_m,
         "DiD point estimate"),
        ("Incremental eligible spend / cust / window - UPSIDE", ti["incr_per_cust_high"], inp_m,
         "Upper bound of the 95% CI on the DiD estimate"),
        ("Halo spend / customer / window (non-eligible categories)", ti["halo_per_cust"], inp_m,
         "Extra spend outside Dining+Entertainment - upside only, not in headline ROI"),
    ]
    a.write_row("A4", ["Assumption", "Value", "Note"], hdr)
    for i, (label, val, fmt, note) in enumerate(rows):
        r = 4 + i
        a.write(r, 0, label)
        a.write_number(r, 1, float(val), fmt)
        a.write(r, 2, note)

    A = {label: f"Assumptions!$B${5 + i}" for i, (label, *_ ) in enumerate(rows)}

    # -------------------------------------------------------------- Scenario Model ---
    s = wb.add_worksheet("Scenario Model")
    s.set_column("A:A", 46)
    s.set_column("B:D", 16)
    s.write("A1", "Annual Promotion Economics by Scenario", title)
    s.write_row("A3", ["Metric", "Conservative", "Base", "Upside"], hdr)

    scen_cell = {
        "Conservative": A["Incremental eligible spend / cust / window - CONSERVATIVE"],
        "Base": A["Incremental eligible spend / cust / window - BASE"],
        "Upside": A["Incremental eligible spend / cust / window - UPSIDE"],
    }
    cols = {"Conservative": "B", "Base": "C", "Upside": "D"}

    labels = [
        "Incremental eligible spend / customer / window",  # 4
        "Targeted population",                             # 5
        "Promo windows per year",                          # 6
        "Annual incremental eligible spend",               # 7
        "Annual promotion cost",                           # 8
        "Annual incremental margin",                       # 9
        "Annual net benefit",                              # 10
        "ROI (net benefit / promo cost)",                  # 11
        "Break-even incremental spend / cust / window",    # 12
        "Break-even eligible lift (% of counterfactual)",  # 13
        "Scenario eligible lift (% of counterfactual)",    # 14
        "Memo: annual halo spend (upside)",                # 15
        "Memo: ROI including halo upside",                 # 16
    ]
    for i, lab in enumerate(labels):
        s.write(3 + i, 0, lab, bold if lab.startswith(("Annual net", "ROI (")) else None)

    for name, col in cols.items():
        s.write_formula(f"{col}4", f"={scen_cell[name]}", money2)
        s.write_formula(f"{col}5", f"={A['Targeted population (customers)']}", num)
        s.write_formula(f"{col}6", f"={A['Promo windows per year']}", num)
        s.write_formula(f"{col}7", f"={col}4*{col}5*{col}6", money)
        s.write_formula(f"{col}8", f"={A['Promotion cost / customer / window']}*{col}5*{col}6", money)
        s.write_formula(f"{col}9", f"={A['Contribution margin on incremental spend']}*{col}7", money)
        s.write_formula(f"{col}10", f"={col}9-{col}8", money)
        s.write_formula(f"{col}11", f"={col}10/{col}8", pct)
        s.write_formula(
            f"{col}12",
            f"={A['Promotion cost / customer / window']}/{A['Contribution margin on incremental spend']}",
            money2,
        )
        s.write_formula(f"{col}13", f"={col}12/{A['Counterfactual eligible spend / customer / window']}", pct)
        s.write_formula(f"{col}14", f"={col}4/{A['Counterfactual eligible spend / customer / window']}", pct)
        s.write_formula(
            f"{col}15",
            f"={A['Halo spend / customer / window (non-eligible categories)']}*{col}5*{col}6", money,
        )
        s.write_formula(
            f"{col}16",
            f"=({A['Contribution margin on incremental spend']}*({col}7+{col}15)-{col}8)/{col}8", pct,
        )

    s.write("A19", "Reading the model", bold)
    s.write("A20", "Net benefit > 0 and ROI > 0 mean the promotion pays for itself after cashback cost.")
    s.write("A21", "If 'Scenario eligible lift' < 'Break-even eligible lift', that scenario loses money.")
    s.write("A22", "Conservative uses the low end of the 95% confidence interval - if it is still "
                   "positive, the program is robust to statistical uncertainty.")
    s.write("A23", "Halo rows show what happens if the (less certain) spillover to other categories holds up.")

    # ------------------------------------------------------------- Segment Detail ---
    econ = pd.read_csv(C.OUT_ANALYSIS / "economics_by_segment.csv")
    d = wb.add_worksheet("Segment Detail (pilot)")
    detail_cols = [
        ("segment", "Segment", 22, None),
        ("n_treatment_customers", "Treated customers", 15, num),
        ("did_eligible_spend_per_cust", "Eligible DiD $/cust", 17, money2),
        ("eligible_p_value", "p-value", 10, wb.add_format({"num_format": "0.000"})),
        ("eligible_significant_5pct", "Significant?", 12, None),
        ("incremental_eligible_spend", "Incr. eligible spend", 18, money),
        ("halo_spend", "Halo spend", 13, money),
        ("promotion_cost", "Promotion cost", 15, money),
        ("incremental_margin", "Incr. margin", 14, money),
        ("net_benefit", "Net benefit", 14, money),
        ("roi", "ROI", 9, pct0),
        ("roi_with_halo", "ROI incl. halo", 13, pct0),
        ("breakeven_eligible_lift_pct", "Break-even lift", 14, pct0),
        ("verdict", "Verdict", 66, None),
    ]
    for j, (_, label, width, _f) in enumerate(detail_cols):
        d.set_column(j, j, width)
        d.write(0, j, label, hdr)
    for i, (_, row) in enumerate(econ.iterrows(), start=1):
        for j, (key, _l, _w, fmt) in enumerate(detail_cols):
            v = row[key]
            if isinstance(v, (bool, np.bool_)):
                d.write(i, j, "Yes" if v else "No")
            elif isinstance(v, (int, float, np.integer, np.floating)) and pd.notna(v):
                d.write_number(i, j, float(v), fmt)
            else:
                d.write(i, j, str(v))

    # ------------------------------------------------------------------- Read Me ----
    rm = wb.add_worksheet("Read Me")
    rm.set_column("A:A", 100)
    for i, line in enumerate([
        "Merchant Promotion Experimentation Lab - Scenario Model",
        "",
        "Purpose: project the annual economics of the cashback promotion from the pilot read.",
        "",
        "Sheets:",
        "  Assumptions            - all inputs (yellow). Change these to test your own assumptions.",
        "  Scenario Model         - annual cost / revenue / ROI / break-even under 3 scenarios (formula-driven).",
        "  Segment Detail (pilot) - measured pilot economics for every segment tested.",
        "",
        "Scenario definitions (incremental ELIGIBLE-category spend per customer per window):",
        "  Conservative = lower bound of the 95% confidence interval on the difference-in-differences estimate",
        "  Base         = difference-in-differences point estimate",
        "  Upside       = upper bound of the 95% confidence interval",
        "",
        "Headline ROI is built on eligible-category spend only (the effect the promotion can be",
        "cleanly credited with). Halo spend in other categories is shown as a separate upside.",
        "",
        "Scenarios apply only to the TARGETED segments (significant positive eligible-spend lift AND",
        f"positive ROI in the pilot): {ti['segments']}",
        "",
        "Generated by src/build_excel_model.py - re-run the pipeline to refresh.",
    ]):
        rm.write(i, 0, line)

    wb.close()
    print(f"Wrote {path}")
    print(f"  targeted segments      : {ti['segments']}")
    print(f"  targeted population     : {ti['targeted_population']:,}")
    print(f"  incr eligible/cust base : ${ti['incr_per_cust_base']:,.2f}  "
          f"(CI ${ti['incr_per_cust_low']:,.2f} .. ${ti['incr_per_cust_high']:,.2f})")
    print(f"  halo/cust               : ${ti['halo_per_cust']:,.2f}")
    print(f"  promo cost/cust         : ${ti['cost_per_cust']:,.2f}")


if __name__ == "__main__":
    build()
