-- FRIENDLY FRAUD
-- Attack: a real customer makes a purchase, keeps using what they bought, then tells their bank the
-- charge was "unauthorized" to get a refund. The account is genuine; the dispute claim is not.
--
-- Only disputes filed as 'unauthorized' are scored. For each one we ask: did the purchase look like
-- the customer themselves?
--   same device as earlier approved purchases    the "thief" used the owner's own laptop
--   same IP as earlier approved purchases        ...from the owner's home network
--   account tenure                               long-standing accounts rarely get hijacked silently
--   clean purchase history                       several approved charges, no earlier disputes
--   usage after the purchase                     the product was used heavily after the "theft"
--   logins from the purchase device afterwards   the owner kept using the same device
-- Honest unauthorized disputes (stolen card on a fresh account, ATO purchases) fail most of these:
-- new device, new IP, often a new account.
--
-- Score (0 to 100): device 25 + IP 15 + tenure 10 + history 10 + usage 25 + later logins 15.
-- Action: 60+ -> 'review' = represent the dispute with the evidence pack. Never block the customer.

CREATE OR REPLACE TABLE detect_friendly_fraud AS
WITH unauthorized AS (
    SELECT d.dispute_id, d.filed_ts, d.status, d.outcome, t.txn_id, t.user_id, t.ts AS txn_ts, t.amount,
           t.device_id, t.ip
    FROM disputes d
    JOIN transactions t USING (txn_id)
    WHERE d.reason_category = 'unauthorized'
),
prior AS (
    SELECT u.dispute_id,
           count(p.txn_id)                                         AS prior_approved_charges,
           count(p.txn_id) FILTER (WHERE p.device_id = u.device_id) AS prior_same_device,
           count(p.txn_id) FILTER (WHERE p.ip = u.ip)               AS prior_same_ip
    FROM unauthorized u
    LEFT JOIN transactions p
      ON p.user_id = u.user_id AND p.ts < u.txn_ts
     AND p.txn_type = 'charge' AND p.result = 'approved'
    GROUP BY u.dispute_id
),
prior_disputes AS (
    SELECT u.dispute_id, count(d2.dispute_id) AS earlier_disputes
    FROM unauthorized u
    LEFT JOIN transactions t2 ON t2.user_id = u.user_id
    LEFT JOIN disputes d2 ON d2.txn_id = t2.txn_id AND d2.filed_ts < u.filed_ts
    GROUP BY u.dispute_id
),
usage_after AS (
    SELECT u.dispute_id, coalesce(sum(e.minutes), 0) AS minutes_after, count(DISTINCT e.date) AS active_days_after
    FROM unauthorized u
    LEFT JOIN usage_events e
      ON e.user_id = u.user_id AND e.date > CAST(u.txn_ts AS DATE) AND e.date <= CAST(u.filed_ts AS DATE)
    GROUP BY u.dispute_id
),
logins_after AS (
    SELECT u.dispute_id, count(l.login_id) AS logins_same_device_after
    FROM unauthorized u
    LEFT JOIN logins l
      ON l.user_id = u.user_id AND l.device_id = u.device_id AND l.success
     AND l.ts > u.txn_ts AND l.ts <= u.filed_ts
    GROUP BY u.dispute_id
),
features AS (
    SELECT u.*, usr.signup_ts,
           date_diff('day', usr.signup_ts, u.txn_ts) AS tenure_days_at_purchase,
           p.prior_approved_charges, p.prior_same_device, p.prior_same_ip,
           pd.earlier_disputes, ua.minutes_after, ua.active_days_after, la.logins_same_device_after
    FROM unauthorized u
    JOIN users usr USING (user_id)
    JOIN prior p USING (dispute_id)
    JOIN prior_disputes pd USING (dispute_id)
    JOIN usage_after ua USING (dispute_id)
    JOIN logins_after la USING (dispute_id)
),
scored AS (
    SELECT *,
           CASE WHEN prior_same_device > 0 THEN 25 ELSE 0 END
         + CASE WHEN prior_same_ip > 0 THEN 15 ELSE 0 END
         + CASE WHEN tenure_days_at_purchase >= 180 THEN 10 WHEN tenure_days_at_purchase >= 60 THEN 5 ELSE 0 END
         + CASE WHEN prior_approved_charges >= 3 AND earlier_disputes = 0 THEN 10 ELSE 0 END
         + CASE WHEN minutes_after >= 300 THEN 25 WHEN minutes_after > 0 THEN 10 ELSE 0 END
         + CASE WHEN logins_same_device_after > 0 THEN 15 ELSE 0 END AS raw_score
    FROM features
)
SELECT
    'dispute' AS entity_type,
    dispute_id AS entity_id,
    CAST(least(raw_score, 100) AS INTEGER) AS risk_score,
    list_filter([
        CASE WHEN prior_same_device > 0 THEN 'SAME_DEVICE_AS_PRIOR_PURCHASES' END,
        CASE WHEN prior_same_ip > 0 THEN 'SAME_IP_AS_PRIOR_PURCHASES' END,
        CASE WHEN tenure_days_at_purchase >= 180 THEN 'LONG_TENURE' END,
        CASE WHEN prior_approved_charges >= 3 AND earlier_disputes = 0 THEN 'CLEAN_PAYMENT_HISTORY' END,
        CASE WHEN minutes_after >= 300 THEN 'HEAVY_USAGE_AFTER_PURCHASE'
             WHEN minutes_after > 0 THEN 'USAGE_AFTER_PURCHASE' END,
        CASE WHEN logins_same_device_after > 0 THEN 'KEPT_USING_SAME_DEVICE' END
    ], lambda x: x IS NOT NULL) AS reason_codes,
    CASE WHEN risk_score >= 60 THEN 'review' ELSE 'allow' END AS recommended_action,
    CASE WHEN risk_score >= 60 THEN 'Represent the dispute with the evidence pack; do not block the customer'
         ELSE 'Accept the chargeback: looks like genuine third-party fraud' END AS action_detail,
    txn_id, user_id, amount, txn_ts, filed_ts, status, outcome, tenure_days_at_purchase,
    prior_approved_charges, prior_same_device, prior_same_ip, minutes_after, active_days_after,
    logins_same_device_after
FROM scored;
