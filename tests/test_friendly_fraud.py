"""Friendly fraud and the chargeback lifecycle."""
from src.evaluate import evaluate_pattern
from src.generate.disputes import LAG_MAX_DAYS, LAG_MIN_DAYS


def test_friendly_fraud_recall_and_fpr(small_db):
    result = evaluate_pattern(small_db, "friendly_fraud")
    assert result["attack_entities"] > 0 and result["lookalikes"] > 0
    assert result["recall"] >= 0.85, result
    assert result["fpr_lookalike"] < 0.02, result


def test_friendly_fraud_never_blocks_the_customer(small_db):
    actions = {r[0] for r in small_db.execute("SELECT DISTINCT recommended_action FROM detect_friendly_fraud").fetchall()}
    assert actions <= {"allow", "review"}


def test_dispute_lag_within_model_bounds(small_db):
    lo, hi = small_db.execute("""SELECT min(date_diff('day', t.ts, d.filed_ts)), max(date_diff('day', t.ts, d.filed_ts))
                                 FROM disputes d JOIN transactions t USING (txn_id)""").fetchall()[0]
    assert lo >= LAG_MIN_DAYS - 1 and hi <= LAG_MAX_DAYS


def test_label_delay_recent_weeks_look_clean(small_db):
    """Disputes per approved charge are lower for the most recent month: labels haven't arrived yet."""
    early, recent = small_db.execute("""
        WITH c AS (SELECT t.txn_id, t.ts, d.dispute_id FROM transactions t LEFT JOIN disputes d USING (txn_id)
                   WHERE t.txn_type = 'charge' AND t.result = 'approved')
        SELECT avg((dispute_id IS NOT NULL)::INT) FILTER (WHERE ts < (SELECT max(ts) FROM c) - INTERVAL 60 DAY),
               avg((dispute_id IS NOT NULL)::INT) FILTER (WHERE ts >= (SELECT max(ts) FROM c) - INTERVAL 30 DAY)
        FROM c""").fetchall()[0]
    assert recent < early
