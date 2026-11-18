-- IEEE-CIS VALIDATION: do this project's signal ideas carry over to real, labelled fraud data?
-- Source: Kaggle "IEEE-CIS Fraud Detection" (Vesta e-commerce transactions, isFraud label).
-- The dataset is anonymized and has no customer id, no logins and no disputes, so each simulator
-- signal is mapped to its closest real-data proxy:
--
--   simulator idea                     IEEE-CIS proxy
--   customer / account                 uid = card1 + addr1 + the day the card was first seen (TransactionDT/86400 - D1),
--                                      a widely used reconstruction from the competition
--   card testing velocity              transactions on the same card1 in the previous hour
--   micro amounts                      TransactionAmt < $5
--   disposable / anonymous inbox       P_emaildomain is an anonymous or privacy-focused provider
--   new device on a known account      uid has earlier transactions, never from this DeviceInfo (ATO idea)
--   amount spike vs history            amount > 3x the uid's average of earlier transactions
--   new account / short tenure         D1 = 0: card first seen today
--   buyer and recipient differ         R_emaildomain present and different from P_emaildomain
--
-- isFraud is only read by src/ieee/validate.py, never here.

CREATE OR REPLACE TABLE ieee_signals AS
WITH base AS (
    SELECT t.TransactionID, t.TransactionDT, t.TransactionAmt AS amount, t.ProductCD, t.card1,
           t.P_emaildomain, t.R_emaildomain, t.D1, i.DeviceInfo,
           CAST(t.card1 AS VARCHAR) || '_' || coalesce(CAST(t.addr1 AS VARCHAR), 'na') || '_'
               || coalesce(CAST(floor(t.TransactionDT / 86400.0 - t.D1) AS VARCHAR), 'na') AS uid
    FROM ieee_txn t
    LEFT JOIN ieee_identity i USING (TransactionID)
),
windows AS (
    SELECT *,
           count(*) OVER (PARTITION BY card1 ORDER BY TransactionDT
                          RANGE BETWEEN 3600 PRECEDING AND CURRENT ROW) - 1             AS card_txns_prev_1h,
           count(*) OVER (PARTITION BY uid ORDER BY TransactionDT, TransactionID
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)              AS uid_prior_txns,
           avg(amount) OVER (PARTITION BY uid ORDER BY TransactionDT, TransactionID
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)           AS uid_prior_avg_amount,
           count(*) OVER (PARTITION BY uid, DeviceInfo ORDER BY TransactionDT, TransactionID
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)              AS uid_prior_on_device
    FROM base
)
SELECT
    TransactionID,
    card_txns_prev_1h >= 3                                                               AS sig_card_velocity,
    amount < 5                                                                           AS sig_micro_amount,
    coalesce(P_emaildomain IN ('anonymous.com', 'protonmail.com', 'mail.com', 'yandex.ru',
                               'mail.ru', 'guerrillamail.com', 'yopmail.com'), false)    AS sig_anonymous_email,
    coalesce(uid_prior_txns > 0 AND DeviceInfo IS NOT NULL AND uid_prior_on_device = 0,
             false)                                                                      AS sig_new_device_known_uid,
    coalesce(uid_prior_txns > 0 AND amount > 3 * uid_prior_avg_amount, false)           AS sig_amount_spike,
    coalesce(D1 = 0, false)                                                              AS sig_new_card,
    coalesce(R_emaildomain IS NOT NULL AND R_emaildomain <> P_emaildomain, false)        AS sig_email_mismatch,
    card_txns_prev_1h, uid_prior_txns, amount
FROM windows;

-- One additive score, in the same spirit as the simulator's detectors (weights are judgment, not fitted).
CREATE OR REPLACE TABLE ieee_scores AS
SELECT TransactionID,
       15 * sig_card_velocity::INT + 10 * sig_micro_amount::INT + 20 * sig_anonymous_email::INT
     + 20 * sig_new_device_known_uid::INT + 15 * sig_amount_spike::INT + 10 * sig_new_card::INT
     + 10 * sig_email_mismatch::INT AS risk_score
FROM ieee_signals;
