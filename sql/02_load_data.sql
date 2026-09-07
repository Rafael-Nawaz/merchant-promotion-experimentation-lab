-- =============================================================================
-- 02_load_data.sql  -  load the generated CSVs
--
-- Run from the project root so the relative paths resolve:
--   psql -d promo_lab -v ON_ERROR_STOP=1 -f sql/02_load_data.sql
--
-- \copy runs client-side, so it works without superuser / server file access.
-- Generate the CSVs first with:  python src/generate_data.py
-- =============================================================================

TRUNCATE transactions, customers, promotion_calendar RESTART IDENTITY;

\copy promotion_calendar (study_week, week_start, period, promotion_active) FROM 'data/promotion_calendar.csv' WITH (FORMAT csv, HEADER true)

\copy customers (customer_id, segment, region, "group", tenure_months, activity_index) FROM 'data/customers.csv' WITH (FORMAT csv, HEADER true)

\copy transactions (transaction_id, customer_id, txn_date, merchant_category, amount, cashback_earned, period, study_week, segment, region, "group", is_eligible_category) FROM 'data/transactions.csv' WITH (FORMAT csv, HEADER true)

ANALYZE promotion_calendar;
ANALYZE customers;
ANALYZE transactions;

-- Sanity checks -------------------------------------------------------------------
SELECT 'customers'    AS table_name, count(*) FROM customers
UNION ALL
SELECT 'transactions', count(*) FROM transactions
UNION ALL
SELECT 'calendar',     count(*) FROM promotion_calendar;

SELECT "group", count(*) AS customers
FROM customers
GROUP BY "group"
ORDER BY "group";
