-- RESPONSE LADDER
-- Every detection maps its score to one step: allow -> step_up -> review -> block.
-- Each step has an assumed friction cost: the share of LEGIT customers on that step who are lost
-- (they abandon a 3DS/MFA/CAPTCHA challenge, give up while a manual review is pending, or are
-- blocked outright). These rates are assumptions, stated here so they can be argued with.
--
-- This file also puts a dollar figure on every scored entity, without looking at any labels:
--   fraud_usd_if_true     what we lose if this entity IS an attack and we let it through
--   monthly_revenue_usd   what we lose per month if it is a LEGIT customer and we lose them
-- The Friction Tradeoff screen weighs the first against the second times the friction rate.

CREATE OR REPLACE TABLE ladder_steps AS
-- fraud_stop_rate: share of attacks the step actually stops (step-up is beaten sometimes:
-- a fraudster with the victim's phone passes MFA, a CAPTCHA farm solves CAPTCHAs).
SELECT * FROM (VALUES
    ('allow',   0, 0.00, 0.00, 'No action'),
    ('step_up', 1, 0.05, 0.90, '3DS for payments, MFA for logins, CAPTCHA at checkout: ~5% of legit users abandon'),
    ('review',  2, 0.10, 1.00, 'Held for an analyst: ~10% of legit users give up during the delay'),
    ('block',   3, 1.00, 1.00, 'Blocked: a legit customer caught here is lost')
) AS t(step, severity, friction_rate, fraud_stop_rate, description);

-- Monthly revenue per user: approved charges minus refunds over the window, divided by its length.
CREATE OR REPLACE TABLE user_monthly_revenue AS
WITH span AS (SELECT greatest(date_diff('day', min(ts), max(ts)), 30) / 30.0 AS months FROM transactions)
SELECT t.user_id,
       (sum(CASE WHEN t.txn_type = 'charge' AND t.result = 'approved' THEN t.amount ELSE 0 END)
        - sum(CASE WHEN t.txn_type = 'refund' THEN t.amount ELSE 0 END)) / any_value(span.months) AS monthly_usd
FROM transactions t, span
GROUP BY t.user_id;

CREATE OR REPLACE TABLE scored_entities AS
WITH card_testing AS (
    SELECT 'card_testing' AS pattern, d.entity_type, d.entity_id, d.risk_score, d.reason_codes,
           d.recommended_action, d.action_detail, d.window_end AS event_ts,
           -- cash-out charges on cards this burst validated, plus ~$0.10 network fee per attempt
           coalesce(v.later_usd, 0) + 0.10 * d.attempts_10m AS fraud_usd_if_true,
           coalesce(r.monthly_usd, 0) AS monthly_revenue_usd
    FROM detect_card_testing d
    LEFT JOIN (SELECT tested_from, sum(later_charge_amount) AS later_usd
               FROM card_testing_validated_cards GROUP BY 1) v
           ON v.tested_from = d.entity_type || ':' || d.entity_id
    LEFT JOIN (SELECT a.ip AS entity_id, 'ip' AS entity_type, sum(u.monthly_usd) AS monthly_usd
               FROM (SELECT DISTINCT ip, user_id FROM payment_attempts WHERE result = 'approved') a
               JOIN user_monthly_revenue u USING (user_id) GROUP BY a.ip
               UNION ALL
               SELECT a.device_id, 'device', sum(u.monthly_usd)
               FROM (SELECT DISTINCT device_id, user_id FROM payment_attempts WHERE result = 'approved') a
               JOIN user_monthly_revenue u USING (user_id) GROUP BY a.device_id) r
           USING (entity_type, entity_id)
),
trial_abuse AS (
    SELECT 'trial_abuse', d.entity_type, d.entity_id, d.risk_score, d.reason_codes,
           d.recommended_action, d.action_detail, s.trial_start_ts,
           -- a free month of the plan they trialed
           CASE WHEN s.is_trial AND NOT coalesce(s.converted, false) THEN p.monthly_usd ELSE 0 END,
           coalesce(r.monthly_usd, 0)
    FROM detect_trial_abuse d
    LEFT JOIN subscriptions s ON s.user_id = d.entity_id
    LEFT JOIN plan_prices p ON p.plan = s.plan
    LEFT JOIN user_monthly_revenue r ON r.user_id = d.entity_id
),
ato AS (
    SELECT 'ato', d.entity_type, d.entity_id, d.risk_score, d.reason_codes,
           d.recommended_action, d.action_detail, d.anchor_ts,
           -- fraudulent spend + $15 chargeback fee
           d.charged_after_usd + CASE WHEN d.charged_after_usd > 0 THEN 15 ELSE 0 END,
           coalesce(r.monthly_usd, 0)
    FROM detect_ato d
    LEFT JOIN user_monthly_revenue r ON r.user_id = d.entity_id
),
friendly_fraud AS (
    SELECT 'friendly_fraud', d.entity_type, d.entity_id, d.risk_score, d.reason_codes,
           d.recommended_action, d.action_detail, d.filed_ts,
           d.amount + 15,
           coalesce(r.monthly_usd, 0)
    FROM detect_friendly_fraud d
    LEFT JOIN user_monthly_revenue r ON r.user_id = d.user_id
)
SELECT s.*, l.severity, l.friction_rate, l.fraud_stop_rate
FROM (SELECT * FROM card_testing UNION ALL SELECT * FROM trial_abuse
      UNION ALL SELECT * FROM ato UNION ALL SELECT * FROM friendly_fraud) s
JOIN ladder_steps l ON l.step = s.recommended_action;

CREATE OR REPLACE VIEW alerts AS
SELECT * FROM scored_entities WHERE recommended_action <> 'allow';
