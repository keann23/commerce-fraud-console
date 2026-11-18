"""Response ladder, tradeoff math, rule simulator guard, evidence pack."""
import pytest

from src.evaluate import overview, rule_backtest, tradeoff
from src.evidence_pack import build_evidence_pdf


def test_every_alert_maps_to_a_ladder_step(small_db):
    unmapped = small_db.execute("""SELECT count(*) FROM scored_entities
                                   WHERE recommended_action NOT IN (SELECT step FROM ladder_steps)""").fetchall()[0][0]
    assert unmapped == 0


def test_ladder_cuts_false_declines_at_equal_threshold(small_db):
    df = tradeoff(small_db, thresholds=[30, 40]).set_index(["threshold", "policy"])
    for t in (30, 40):
        ladder, block = df.loc[(t, "ladder")], df.loc[(t, "block_only")]
        assert ladder.recall == block.recall                       # same alerts fire
        assert ladder.expected_false_declines <= block.expected_false_declines
        assert ladder.fraud_stopped_usd >= 0.95 * block.fraud_stopped_usd


def test_overview_has_no_false_declines_at_default_actions(small_db):
    stats = overview(small_db)
    assert stats["fraud_prevented_usd"] > 0
    assert stats["false_declines"] == 0


@pytest.mark.parametrize("bad", ["1=1; DROP TABLE users", "amount > 1 OR (DELETE FROM users)"])
def test_rule_simulator_rejects_statements(small_db, bad):
    with pytest.raises(ValueError):
        rule_backtest(small_db, bad)


def test_rule_simulator_backtest(small_db):
    result = rule_backtest(small_db, "ip_declines_10m >= 5 AND amount < 3")
    assert result["attack_hits"] > 0 and result["legit_hits"] == 0


def test_evidence_pack_pdf(small_db):
    row = small_db.execute("""SELECT d.*, t.device_id, t.ip FROM detect_friendly_fraud d JOIN transactions t USING (txn_id)
                              WHERE d.recommended_action = 'review' LIMIT 1""").df().iloc[0].to_dict()
    row["dispute_id"] = row["entity_id"]
    pdf = build_evidence_pdf(row, [], [], [])
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000
