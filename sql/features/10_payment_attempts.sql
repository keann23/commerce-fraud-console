-- Every auth or charge attempt with the card details an analyst needs (fingerprint, BIN, last4).
-- Refunds are excluded: they are money going back, not an attempt to use a card.
CREATE OR REPLACE VIEW payment_attempts AS
SELECT
    t.txn_id, t.user_id, t.pm_id, t.ts, t.amount, t.txn_type, t.result, t.decline_reason,
    t.ip, t.device_id,
    p.card_fingerprint, p.bin, p.last4
FROM transactions t
LEFT JOIN payment_methods p USING (pm_id)
WHERE t.txn_type IN ('auth', 'charge');
