-- TRIAL ABUSE
-- Attack: one person opens many "new" accounts to chain free trials, cancelling each before it bills.
-- They hide behind email tricks (Gmail dots, plus tags, disposable inboxes) and reuse a laptop or
-- a virtual card, so the accounts look unrelated unless you link them.
--
-- Signals, per identity cluster (accounts connected by shared device, card or normalized inbox):
--   trials per cluster       one human rarely needs more than one or two trials
--   zero conversions         abusers never pay; families and shared computers usually do (only
--                            counted once 3+ trials have reached their end date)
--   email aliases            several accounts, one real inbox, or throwaway domains
--   virtual / shared card    virtual cards are disposable; one card on 5+ accounts is not a family
--   cancel before billing    abusers cancel right before the first charge
--
-- Score (0 to 100): trial volume 25 + no conversions 30 + email tricks 20 + card 15 + early cancel 10.
-- Action: 80+ deny new trials to the whole cluster; 60 to 79 require a non-virtual card and phone
-- verification to start a trial. Nobody is banned from paying.

CREATE OR REPLACE TABLE trial_identity_clusters AS
WITH members AS (
    SELECT c.cluster_id, u.user_id, u.email, u.email_normalized,
           is_disposable_email(u.email) AS disposable,
           s.plan, coalesce(s.is_trial, false) AS is_trial, s.converted,
           coalesce(s.canceled_ts < s.trial_end_ts, false) AS canceled_in_trial
    FROM identity_clusters c
    JOIN users u USING (user_id)
    LEFT JOIN subscriptions s USING (user_id)
),
cluster_stats AS (
    SELECT cluster_id,
           count(DISTINCT user_id)                                                  AS n_accounts,
           count(DISTINCT user_id) FILTER (WHERE is_trial)                          AS n_trials,
           count(DISTINCT user_id) FILTER (WHERE is_trial AND converted IS NOT NULL) AS n_decided,
           count(DISTINCT user_id) FILTER (WHERE is_trial AND converted)            AS n_converted,
           count(DISTINCT user_id) FILTER (WHERE is_trial AND canceled_in_trial)    AS n_canceled_in_trial,
           count(DISTINCT email_normalized)                                         AS n_inboxes,
           avg(disposable::INT)                                                     AS disposable_share,
           count(*) FILTER (WHERE plan = 'student' AND email NOT LIKE '%.edu')      AS n_student_non_edu
    FROM members
    GROUP BY cluster_id
),
card_users AS (
    SELECT card_fingerprint, count(DISTINCT user_id) AS n_users FROM payment_methods GROUP BY 1
),
card_stats AS (
    SELECT c.cluster_id,
           avg(p.is_virtual_or_prepaid::INT) AS virtual_share,
           max(cu.n_users)                   AS max_accounts_per_card
    FROM payment_methods p
    JOIN identity_clusters c USING (user_id)
    JOIN card_users cu USING (card_fingerprint)
    GROUP BY 1
),
device_users AS (
    SELECT link_value, count(DISTINCT user_id) AS n_users FROM identity_links WHERE link_type = 'device' GROUP BY 1
),
device_stats AS (
    SELECT c.cluster_id, max(du.n_users) AS max_accounts_per_device
    FROM identity_links l
    JOIN identity_clusters c USING (user_id)
    JOIN device_users du USING (link_value)
    WHERE l.link_type = 'device'
    GROUP BY 1
),
features AS (
    SELECT s.*,
           coalesce(cs.virtual_share, 0)            AS virtual_share,
           coalesce(cs.max_accounts_per_card, 0)    AS max_accounts_per_card,
           coalesce(ds.max_accounts_per_device, 0)  AS max_accounts_per_device,
           1 - s.n_inboxes / s.n_accounts            AS email_alias_share,
           CASE WHEN s.n_decided > 0 THEN 1 - s.n_converted / s.n_decided ELSE 0 END AS non_conversion_rate
    FROM cluster_stats s
    LEFT JOIN card_stats cs USING (cluster_id)
    LEFT JOIN device_stats ds USING (cluster_id)
    WHERE s.n_trials >= 1
),
scored AS (
    SELECT *,
           25 * least(greatest(n_trials - 1, 0) / 8.0, 1)                            AS volume_pts,
           30 * non_conversion_rate * least(n_decided / 3.0, 1)                      AS no_conversion_pts,
           20 * least((email_alias_share + disposable_share) / 0.5, 1)               AS email_pts,
           CASE WHEN virtual_share >= 0.5 OR max_accounts_per_card >= 5 THEN 15 ELSE 0 END AS card_pts,
           10 * n_canceled_in_trial / n_trials                                       AS cancel_pts
    FROM features
)
SELECT
    cluster_id, n_accounts, n_trials, n_decided, n_converted, n_canceled_in_trial, n_inboxes,
    round(disposable_share, 3) AS disposable_share, round(virtual_share, 3) AS virtual_share,
    max_accounts_per_card, max_accounts_per_device, n_student_non_edu,
    CAST(round(least(volume_pts + no_conversion_pts + email_pts + card_pts + cancel_pts, 100)) AS INTEGER)
        AS risk_score,
    list_filter([
        CASE WHEN n_trials >= 3 THEN 'MANY_TRIALS_ONE_IDENTITY' END,
        CASE WHEN n_decided >= 3 AND n_converted = 0 THEN 'NO_CONVERSIONS' END,
        CASE WHEN n_inboxes < n_accounts THEN 'EMAIL_ALIASES' END,
        CASE WHEN disposable_share > 0 THEN 'DISPOSABLE_EMAIL' END,
        CASE WHEN virtual_share >= 0.5 THEN 'VIRTUAL_CARD' END,
        CASE WHEN max_accounts_per_card >= 3 THEN 'SHARED_CARD' END,
        CASE WHEN max_accounts_per_device >= 3 THEN 'SHARED_DEVICE' END,
        CASE WHEN n_trials >= 2 AND n_canceled_in_trial >= 0.8 * n_trials THEN 'CANCEL_BEFORE_BILLING' END,
        CASE WHEN n_student_non_edu > 0 AND n_trials >= 2 THEN 'STUDENT_NON_EDU' END
    ], lambda x: x IS NOT NULL) AS reason_codes,
    CASE WHEN risk_score >= 80 THEN 'block'
         WHEN risk_score >= 60 THEN 'step_up'
         ELSE 'allow' END AS recommended_action,
    CASE WHEN risk_score >= 80 THEN 'Deny new trials on this cluster''s devices, cards and inboxes'
         WHEN risk_score >= 60 THEN 'Require a non-virtual card and phone verification to start a trial'
         ELSE 'No action' END AS action_detail
FROM scored;

-- One row per account in a scored cluster: the entity the case queue and evaluation work on.
CREATE OR REPLACE TABLE detect_trial_abuse AS
SELECT 'user' AS entity_type, c.user_id AS entity_id, t.cluster_id, t.risk_score, t.reason_codes,
       t.recommended_action, t.action_detail, t.n_accounts, t.n_trials, t.n_converted, t.n_inboxes
FROM identity_clusters c
JOIN trial_identity_clusters t USING (cluster_id);
