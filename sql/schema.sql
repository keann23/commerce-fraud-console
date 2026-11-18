-- Warehouse schema for the synthetic Adobe-style subscription business.
-- All money is stored in USD (regional price tiers are already applied).
-- ground_truth is written by attack injectors and read ONLY by evaluation and tests.

CREATE TABLE users (
    user_id            VARCHAR PRIMARY KEY,
    email              VARCHAR NOT NULL,
    email_normalized   VARCHAR,          -- filled by normalize_email() macro after load
    signup_ts          TIMESTAMP NOT NULL,
    country            VARCHAR NOT NULL,
    signup_ip          VARCHAR,
    signup_device_id   VARCHAR,
    account_age_days   INTEGER           -- as of the end of the simulation window
);

CREATE TABLE devices (
    device_id          VARCHAR PRIMARY KEY,
    fingerprint_hash   VARCHAR NOT NULL,
    os                 VARCHAR,
    browser            VARCHAR,
    first_seen_ts      TIMESTAMP
);

CREATE TABLE logins (
    login_id           VARCHAR PRIMARY KEY,
    user_id            VARCHAR NOT NULL,
    ts                 TIMESTAMP NOT NULL,
    ip                 VARCHAR,
    country            VARCHAR,
    lat                DOUBLE,
    lon                DOUBLE,
    device_id          VARCHAR,
    success            BOOLEAN,
    mfa_used           BOOLEAN
);

CREATE TABLE account_events (
    event_id           VARCHAR PRIMARY KEY,
    user_id            VARCHAR NOT NULL,
    ts                 TIMESTAMP NOT NULL,
    event_type         VARCHAR NOT NULL,  -- password_reset, email_change, payment_method_add, plan_change, cancel
    device_id          VARCHAR,
    ip                 VARCHAR
);

CREATE TABLE payment_methods (
    pm_id                  VARCHAR PRIMARY KEY,
    user_id                VARCHAR NOT NULL,
    card_fingerprint       VARCHAR NOT NULL,  -- same physical card => same fingerprint, even across users
    bin                    VARCHAR,
    last4                  VARCHAR,
    card_country           VARCHAR,
    is_virtual_or_prepaid  BOOLEAN,
    added_ts               TIMESTAMP
);

CREATE TABLE subscriptions (
    sub_id               VARCHAR PRIMARY KEY,
    user_id              VARCHAR NOT NULL,
    plan                 VARCHAR NOT NULL,  -- single_app, photography, all_apps, student
    price_tier_country   VARCHAR,
    is_trial             BOOLEAN,
    trial_start_ts       TIMESTAMP,
    trial_end_ts         TIMESTAMP,
    converted            BOOLEAN,           -- NULL while a trial is still running
    status               VARCHAR,           -- trialing, active, canceled
    canceled_ts          TIMESTAMP
);

CREATE TABLE transactions (
    txn_id           VARCHAR PRIMARY KEY,
    user_id          VARCHAR,
    pm_id            VARCHAR,
    ts               TIMESTAMP NOT NULL,
    amount           DECIMAL(10, 2),
    currency         VARCHAR,
    txn_type         VARCHAR,   -- auth, charge, refund
    result           VARCHAR,   -- approved, declined
    decline_reason   VARCHAR,
    ip               VARCHAR,
    device_id        VARCHAR
);

CREATE TABLE usage_events (
    user_id    VARCHAR NOT NULL,
    date       DATE NOT NULL,
    app        VARCHAR NOT NULL,
    sessions   INTEGER,
    minutes    INTEGER
);

CREATE TABLE disputes (
    dispute_id        VARCHAR PRIMARY KEY,
    txn_id            VARCHAR NOT NULL,
    filed_ts          TIMESTAMP NOT NULL,
    reason_category   VARCHAR,   -- unauthorized, not_as_described, canceled_subscription, duplicate
    status            VARCHAR,   -- open, closed
    responded_ts      TIMESTAMP,
    outcome           VARCHAR    -- won, lost, pending
);

CREATE TABLE ground_truth (
    entity_type   VARCHAR NOT NULL,   -- user, ip, device, card, txn
    entity_id     VARCHAR NOT NULL,
    campaign_id   VARCHAR NOT NULL,
    attack_type   VARCHAR NOT NULL,
    injected_ts   TIMESTAMP,
    label         VARCHAR NOT NULL DEFAULT 'attack'  -- attack, or lookalike (legit entity built to resemble it)
);

-- Lookup used by email normalization. Small on purpose; a real team would sync a maintained list.
CREATE TABLE disposable_domains (domain VARCHAR PRIMARY KEY);
INSERT INTO disposable_domains VALUES
    ('mailinator.com'), ('guerrillamail.com'), ('10minutemail.com'), ('tempmail.com'),
    ('yopmail.com'), ('trashmail.com'), ('sharklasers.com'), ('getnada.com'),
    ('dispostable.com'), ('maildrop.cc');

-- List prices, loaded from src/config.py at build time so Python and SQL share one source.
CREATE TABLE plan_prices (plan VARCHAR PRIMARY KEY, monthly_usd DECIMAL(10, 2));

-- Analyst decisions from the Case File screen (Approve / Step-up / Review / Block).
CREATE TABLE case_decisions (
    decided_ts    TIMESTAMP DEFAULT current_timestamp,
    pattern       VARCHAR,
    entity_type   VARCHAR,
    entity_id     VARCHAR,
    decision      VARCHAR,
    note          VARCHAR
);
