"""Card testing: injector contract, detection quality, and the hardest campaign the PRD allows."""
import pytest

from src.config import SQL_DIR
from src.db import run_detection
from src.evaluate import evaluate_pattern
from src.generate.attacks.card_testing import inject_card_testing

MIN_RECALL = 0.85
MAX_FPR = 0.02


def test_detection_sql_never_reads_ground_truth():
    for path in [*SQL_DIR.glob("features/*.sql"), *SQL_DIR.glob("detect/*.sql"),
                 *SQL_DIR.glob("response_ladder.sql")]:
        assert "ground_truth" not in path.read_text().lower(), f"{path.name} reads ground_truth"


def test_every_detection_has_the_required_columns(small_db):
    cols = {r[0] for r in small_db.execute("DESCRIBE detect_card_testing").fetchall()}
    assert {"entity_id", "risk_score", "reason_codes", "recommended_action"} <= cols
    lo, hi = small_db.execute("SELECT min(risk_score), max(risk_score) FROM detect_card_testing").fetchone()
    assert 0 <= lo and hi <= 100


def test_card_testing_recall(small_db):
    result = evaluate_pattern(small_db, "card_testing")
    assert result["attack_entities"] > 0
    assert result["recall"] >= MIN_RECALL, result


def test_card_testing_false_positive_rates(small_db):
    result = evaluate_pattern(small_db, "card_testing")
    assert result["lookalikes"] > 0, "injector must create legit lookalikes"
    assert result["fpr_legit"] < MAX_FPR, result
    assert result["fpr_lookalike"] < MAX_FPR, result


def test_injector_returns_campaign_and_writes_ground_truth(injection_db):
    con = injection_db
    campaign = inject_card_testing(con, seed=99, attempts=120, duration_minutes=10, start_day=20)
    assert campaign.startswith("CT-")
    labels = dict(con.execute("""SELECT label, count(*) FROM ground_truth WHERE campaign_id = ?
                                 GROUP BY 1""", [campaign]).fetchall())
    assert labels.get("attack", 0) > 0 and labels.get("lookalike", 0) > 0
    n_auths = con.execute("""SELECT count(*) FROM transactions t
                             JOIN ground_truth g ON g.entity_type = 'ip' AND g.entity_id = t.ip
                             WHERE g.campaign_id = ? AND g.label = 'attack' AND t.txn_type = 'auth'""",
                          [campaign]).fetchone()[0]
    assert n_auths == 120


@pytest.mark.parametrize("pattern", ["random", "same_bin", "sequential_last4"])
def test_hardest_campaign_is_still_caught(injection_db, pattern):
    """PRD's weakest corner: 100 attempts spread over 30 min, 3 IPs, 3 devices, only 70% declines."""
    con = injection_db
    campaign = inject_card_testing(con, seed=500 + len(pattern), attempts=100, duration_minutes=30, n_ips=3,
                                   n_devices=3, decline_rate=0.7, card_pattern=pattern, start_day=40)
    run_detection(con)
    missed = con.execute("""
        SELECT g.entity_type, g.entity_id, d.risk_score FROM ground_truth g
        LEFT JOIN detect_card_testing d USING (entity_type, entity_id)
        WHERE g.campaign_id = ? AND g.label = 'attack' AND g.entity_type IN ('ip', 'device')
          AND coalesce(d.recommended_action, 'allow') = 'allow'""", [campaign]).fetchall()
    assert not missed, missed
