"""
Run the whole pipeline end to end.

    python src/run_all.py            # regenerate data + all analysis + model + extracts
    python src/run_all.py --skip-data   # keep existing data/, rerun analysis onward

The PostgreSQL layer (sql/) is optional and run separately - see README.
"""

from __future__ import annotations

import argparse
import runpy
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

STEPS = [
    ("generate_data", "Generate synthetic customers + transactions"),
    ("analysis_did", "Difference-in-differences analysis"),
    ("economics", "Promotion economics / ROI / break-even"),
    ("build_excel_model", "Excel scenario model"),
    ("export_tableau", "Tableau-ready extracts"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-data", action="store_true", help="do not regenerate data/")
    args = ap.parse_args()

    steps = STEPS[1:] if args.skip_data else STEPS
    for i, (mod, desc) in enumerate(steps, 1):
        print("\n" + "#" * 88)
        print(f"# STEP {i}/{len(steps)}: {desc}  ({mod}.py)")
        print("#" * 88)
        t0 = time.time()
        runpy.run_path(str(SRC / f"{mod}.py"), run_name="__main__")
        print(f"\n[{mod}] done in {time.time() - t0:.1f}s")

    print("\nAll steps complete. See outputs/ and docs/executive_recommendation.md")


if __name__ == "__main__":
    main()
