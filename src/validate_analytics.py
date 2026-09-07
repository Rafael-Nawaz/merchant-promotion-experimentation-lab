"""
Cross-check the SQL analytical layer against the Python analysis.

PostgreSQL is the target database for the SQL layer. DuckDB speaks almost the same
dialect and runs in-process, which makes it convenient for verification without a
server. This script:

  1. loads data/*.csv into DuckDB,
  2. executes the view definitions in sql/03_analytical_views.sql,
  3. queries the key views, and
  4. asserts they match outputs/analysis/*.csv (produced by the Python pipeline)
     to within a small tolerance.

A pass confirms the SQL logic in sql/ matches the Python analysis; the same files
run on PostgreSQL with `psql -f`.

    pip install duckdb
    python src/validate_analytics.py
"""

from __future__ import annotations

import re
import sys

import pandas as pd

import config as C

try:
    import duckdb
except ImportError:
    sys.exit("This check needs duckdb:  pip install duckdb")

VIEWS_SQL = C.ROOT / "sql" / "03_analytical_views.sql"


def load(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""
        CREATE TABLE promotion_calendar AS
            SELECT * FROM read_csv_auto('{C.PROMO_CALENDAR_CSV.as_posix()}');
        CREATE TABLE customers AS
            SELECT * FROM read_csv_auto('{C.CUSTOMERS_CSV.as_posix()}');
        CREATE TABLE transactions AS
            SELECT * FROM read_csv_auto('{C.TRANSACTIONS_CSV.as_posix()}');
        CREATE TABLE promo_params (param_name VARCHAR, param_value DOUBLE, note VARCHAR);
        INSERT INTO promo_params VALUES
            ('cashback_rate', {C.CASHBACK_RATE}, ''),
            ('contribution_margin', {C.CONTRIBUTION_MARGIN}, ''),
            ('merchant_funding_share', {C.MERCHANT_FUNDING_SHARE}, ''),
            ('sig_z', 1.96, '');
        """
    )


def run_view_ddl(con: duckdb.DuckDBPyConnection) -> None:
    sql = VIEWS_SQL.read_text()
    # strip line comments, then split on ';'
    sql = re.sub(r"--[^\n]*", "", sql)
    for stmt in (s.strip() for s in sql.split(";")):
        if stmt:
            con.execute(stmt)


def check(name: str, got: pd.DataFrame, want: pd.DataFrame, key: str, col_map: dict, tol: float = 1.0):
    got = got.set_index(key).sort_index()
    want = want.set_index(key).sort_index()
    ok = True
    for gcol, wcol in col_map.items():
        diff = (got[gcol].astype(float) - want[wcol].astype(float)).abs()
        worst = diff.max()
        flag = "OK " if worst <= tol else "XX "
        if worst > tol:
            ok = False
        print(f"  {flag}{name:28s} {gcol:24s} max abs diff = {worst:,.4f}")
    return ok


def main() -> None:
    con = duckdb.connect()
    load(con)
    run_view_ddl(con)

    all_ok = True

    # --- overall DiD ---------------------------------------------------------------
    sql_overall = con.execute("SELECT * FROM v_did_overall").df()
    py_overall = pd.read_csv(C.OUT_ANALYSIS / "did_overall.csv")
    d = abs(float(sql_overall["did_spend_per_customer"][0]) - float(py_overall["did_estimate"][0]))
    print(f"  {'OK ' if d < 1 else 'XX '}overall DiD                    max abs diff = {d:,.4f}")
    all_ok &= d < 1.0

    # --- DiD by segment ---------------------------------------------------------
    sql_seg = con.execute("SELECT * FROM v_did_by_segment").df()
    py_seg = pd.read_csv(C.OUT_ANALYSIS / "did_by_segment.csv")
    all_ok &= check(
        "segment", sql_seg, py_seg, "segment",
        {"did_spend_per_cust": "did_spend_per_cust",
         "counterfactual_spend_per_cust": "counterfactual_spend_per_cust"},
        tol=1.0,
    )

    # --- economics by segment -------------------------------------------------
    sql_econ = con.execute("SELECT * FROM v_promotion_economics_by_segment").df()
    py_econ = pd.read_csv(C.OUT_ANALYSIS / "economics_by_segment.csv")
    all_ok &= check(
        "economics", sql_econ, py_econ, "segment",
        {"incremental_eligible_spend": "incremental_eligible_spend",
         "promotion_cost": "promotion_cost",
         "net_benefit": "net_benefit",
         "halo_spend": "halo_spend"},
        tol=25.0,   # Python uses regression means, SQL uses cell means; tiny rounding gaps
    )

    print()
    if all_ok:
        print("PASS - SQL analytical layer matches the Python analysis.")
    else:
        print("FAIL - differences exceed tolerance (see XX rows above).")
        sys.exit(1)


if __name__ == "__main__":
    main()
