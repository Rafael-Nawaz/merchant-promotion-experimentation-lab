-- =============================================================================
-- Merchant Promotion Experimentation Lab
-- 01_schema.sql  -  create the analytical schema
--
-- Usage:
--   createdb promo_lab
--   psql -d promo_lab -f sql/01_schema.sql
-- =============================================================================

DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
DROP TABLE IF EXISTS promotion_calendar CASCADE;
DROP TABLE IF EXISTS promo_params CASCADE;

-- -----------------------------------------------------------------------------
-- Reference: study calendar (8 pre-promo weeks + 8 promo weeks)
-- -----------------------------------------------------------------------------
CREATE TABLE promotion_calendar (
    study_week       INTEGER PRIMARY KEY,
    week_start       DATE    NOT NULL,
    period           TEXT    NOT NULL CHECK (period IN ('pre', 'post')),
    promotion_active BOOLEAN NOT NULL
);

-- -----------------------------------------------------------------------------
-- Dimension: customers (randomised into treatment / control)
-- -----------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id    INTEGER      PRIMARY KEY,
    segment        TEXT         NOT NULL,
    region         TEXT         NOT NULL,
    "group"        TEXT         NOT NULL CHECK ("group" IN ('treatment', 'control')),
    tenure_months  INTEGER      NOT NULL,
    activity_index NUMERIC(10,4) NOT NULL
);

-- -----------------------------------------------------------------------------
-- Fact: card transactions
-- (segment / region / group are denormalised on for convenient slicing)
-- -----------------------------------------------------------------------------
CREATE TABLE transactions (
    transaction_id       BIGINT        PRIMARY KEY,
    customer_id          INTEGER       NOT NULL REFERENCES customers (customer_id),
    txn_date             DATE          NOT NULL,
    merchant_category    TEXT          NOT NULL,
    amount               NUMERIC(12,2) NOT NULL CHECK (amount >= 0),
    cashback_earned      NUMERIC(12,2) NOT NULL DEFAULT 0,
    period               TEXT          NOT NULL CHECK (period IN ('pre', 'post')),
    study_week           INTEGER       NOT NULL REFERENCES promotion_calendar (study_week),
    segment              TEXT          NOT NULL,
    region               TEXT          NOT NULL,
    "group"              TEXT          NOT NULL,
    is_eligible_category BOOLEAN       NOT NULL
);

CREATE INDEX ix_txn_customer  ON transactions (customer_id);
CREATE INDEX ix_txn_period    ON transactions (period);
CREATE INDEX ix_txn_segment   ON transactions (segment);
CREATE INDEX ix_txn_category  ON transactions (merchant_category);
CREATE INDEX ix_txn_group     ON transactions ("group");

-- -----------------------------------------------------------------------------
-- Reference: promotion economics parameters
-- Keep the business assumptions in one editable place so the economics views
-- (03_analytical_views.sql) stay declarative.
-- -----------------------------------------------------------------------------
CREATE TABLE promo_params (
    param_name  TEXT PRIMARY KEY,
    param_value NUMERIC NOT NULL,
    note        TEXT
);

INSERT INTO promo_params (param_name, param_value, note) VALUES
    ('cashback_rate',           0.03, '3% cashback to cardholder on eligible spend'),
    ('contribution_margin',     0.25, 'Merchant contribution margin on incremental spend'),
    ('merchant_funding_share',  1.00, 'Share of cashback funded by the merchant'),
    ('sig_z',                   1.96, 'z for a 95% confidence interval');
