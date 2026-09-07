"""
Central configuration for the Merchant Promotion Experimentation Lab.

Every business and design parameter - the cashback rate, the merchant margin, the
segment mix, the size of the test - lives here so the rest of the pipeline stays
readable.

The `true_*` fields in SEGMENTS are the ground-truth responses used only by the
synthetic data generator. The analysis code never reads them; it recovers the
effect from the data and derives the economics from that estimate.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "outputs"
OUT_ANALYSIS = OUT_DIR / "analysis"
OUT_EXCEL = OUT_DIR / "excel"
OUT_TABLEAU = OUT_DIR / "tableau"

for _p in (DATA_DIR, OUT_ANALYSIS, OUT_EXCEL, OUT_TABLEAU):
    _p.mkdir(parents=True, exist_ok=True)

CUSTOMERS_CSV = DATA_DIR / "customers.csv"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"
PROMO_CALENDAR_CSV = DATA_DIR / "promotion_calendar.csv"

# --------------------------------------------------------------------------------------
# Experiment design
# --------------------------------------------------------------------------------------
SEED = 20260906

N_CUSTOMERS = 10_000
TREATMENT_SHARE = 0.50           # randomised assignment, ~50/50

PRE_WEEKS = 12
POST_WEEKS = 12
PROMO_START = date(2025, 4, 7)    # Monday; first day of the post / promotion period
STUDY_START = date(2025, 1, 13)   # Monday; first day of the pre period (12 weeks earlier)

# A calendar / seasonality effect that hits treatment AND control equally in the post
# period. This is exactly the kind of "normal spending change" that a raw
# before/after comparison would wrongly attribute to the promotion, and that DiD is
# designed to net out.
COMMON_POST_TREND = 1.03

# --------------------------------------------------------------------------------------
# Promotion mechanics
# --------------------------------------------------------------------------------------
CASHBACK_RATE = 0.03             # 3% cashback to the cardholder on eligible spend
ELIGIBLE_CATEGORIES = ("Dining", "Entertainment")

# Merchant contribution margin on incremental spend. This is the rate at which
# incremental revenue converts into profit that can be used to pay for the promotion.
# Dining and entertainment merchants run relatively high contribution margins.
CONTRIBUTION_MARGIN = 0.25

# Share of the cashback funded by the merchant vs. the card issuer / network.
# 1.0 => the merchant pays the full cashback bill (most conservative view).
MERCHANT_FUNDING_SHARE = 1.00

# --------------------------------------------------------------------------------------
# Geography
# --------------------------------------------------------------------------------------
REGIONS = {
    "Northeast": 0.22,
    "Southeast": 0.24,
    "Midwest": 0.20,
    "West": 0.22,
    "Southwest": 0.12,
}
# Mild regional spend-level differences (nets out in DiD; useful for the dashboard).
REGION_SPEND_FACTOR = {
    "Northeast": 1.08,
    "Southeast": 0.94,
    "Midwest": 0.97,
    "West": 1.10,
    "Southwest": 0.91,
}

# --------------------------------------------------------------------------------------
# Merchant categories
# --------------------------------------------------------------------------------------
# Relative average ticket size by category (multiplies the segment's base ticket).
CATEGORY_TICKET_FACTOR = {
    "Grocery": 0.70,
    "Dining": 0.60,
    "Fuel": 0.50,
    "Apparel": 1.10,
    "Electronics": 2.20,
    "Entertainment": 0.80,
    "Travel": 3.00,
    "OnlineRetail": 1.00,
}
NON_ELIGIBLE_CATEGORIES = tuple(
    c for c in CATEGORY_TICKET_FACTOR if c not in ELIGIBLE_CATEGORIES
)
# How the non-eligible wallet is split across the remaining categories.
NON_ELIGIBLE_MIX = {
    "Grocery": 0.30,
    "Fuel": 0.15,
    "OnlineRetail": 0.20,
    "Apparel": 0.15,
    "Electronics": 0.10,
    "Travel": 0.10,
}

# --------------------------------------------------------------------------------------
# Customer segments
# --------------------------------------------------------------------------------------
# Fields:
#   share                 - fraction of the 10k customers in this segment
#   base_weekly_txn       - expected card transactions per week (pre period)
#   base_ticket           - average transaction amount ($) before category scaling
#   eligible_wallet_share - fraction of transactions in Dining + Entertainment
#   true_lift_eligible    - GROUND TRUTH promo lift on eligible-category frequency,
#                           i.e. the behavioural response to THIS cashback rate
#   true_halo_other       - GROUND TRUTH promo lift on all other categories
#
# The design deliberately spans the ROI spectrum:
#   - Affluent Frequent & Digital Native  -> large lift, clearly positive ROI
#   - Mainstream                          -> moderate lift, roughly break-even
#   - Budget Occasional & Dormant         -> small lift, negative ROI (cashback paid
#                                            on mostly inframarginal spend)
SEGMENTS = {
    "Affluent Frequent": dict(
        share=0.18, base_weekly_txn=3.0, base_ticket=95.0,
        eligible_wallet_share=0.30, true_lift_eligible=0.22, true_halo_other=0.04,
    ),
    "Digital Native": dict(
        share=0.16, base_weekly_txn=2.6, base_ticket=42.0,
        eligible_wallet_share=0.34, true_lift_eligible=0.26, true_halo_other=0.06,
    ),
    "Mainstream": dict(
        share=0.30, base_weekly_txn=1.8, base_ticket=58.0,
        eligible_wallet_share=0.22, true_lift_eligible=0.12, true_halo_other=0.01,
    ),
    "Budget Occasional": dict(
        share=0.24, base_weekly_txn=0.9, base_ticket=34.0,
        eligible_wallet_share=0.18, true_lift_eligible=0.06, true_halo_other=0.00,
    ),
    "Dormant Reactivation": dict(
        share=0.12, base_weekly_txn=0.5, base_ticket=40.0,
        eligible_wallet_share=0.16, true_lift_eligible=0.09, true_halo_other=0.00,
    ),
}

# Individual heterogeneity: per-customer multiplier ~ Gamma(shape, 1/shape) (mean 1).
CUSTOMER_HETEROGENEITY_SHAPE = 4.0

# Lognormal sigma for transaction amounts.
TICKET_LOGNORMAL_SIGMA = 0.5

# --------------------------------------------------------------------------------------
# Scenario model (Excel)
# --------------------------------------------------------------------------------------
# Rollout assumptions for projecting a national program from the pilot read.
ROLLOUT_ELIGIBLE_CUSTOMERS = 750_000   # size of the addressable population
ROLLOUT_MONTHS = 12
PROMO_PERIODS_PER_YEAR = 12 / (POST_WEEKS / 4.0)  # promotion windows per year

SIG_LEVEL = 0.05
