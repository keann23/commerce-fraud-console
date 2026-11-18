"""Account takeover: detection quality and injector contract."""
from src.db import run_detection
from src.evaluate import evaluate_pattern
from src.generate.attacks.ato import inject_ato

MIN_RECALL = 0.85
MAX_FPR = 0.02


def test_ato_recall(small_db):
    result = evaluate_pattern(small_db, "ato")
    assert result["attack_entities"] > 0
    assert result["recall"] >= MIN_RECALL, result


def test_ato_false_positive_rates(small_db):
    result = evaluate_pattern(small_db, "ato")
    assert result["lookalikes"] > 0, "injector must create legit lookalikes"
    assert result["fpr_legit"] < MAX_FPR, result
    assert result["fpr_lookalike"] < MAX_FPR, result


def test_victims_are_not_banned(small_db):
    """The owner is the victim: ATO may step up or send to review, never 'block'."""
    blocked = small_db.execute("SELECT count(*) FROM detect_ato WHERE recommended_action = 'block'").fetchall()[0][0]
    assert blocked == 0


def test_injector_contract_and_sequence(injection_db):
    con = injection_db
    campaign = inject_ato(con, seed=31, n_victims=4, impossible_travel_rate=1.0, monetize_rate=1.0, start_day=40)
    assert campaign.startswith("ATO-")
    victims = [r[0] for r in con.execute("""SELECT entity_id FROM ground_truth WHERE campaign_id = ?
                                            AND label = 'attack' AND entity_type = 'user'""", [campaign]).fetchall()]
    assert len(victims) == 4
    run_detection(con)
    for user_id in victims:
        codes, action = con.execute("SELECT reason_codes, recommended_action FROM detect_ato WHERE entity_id = ?",
                                    [user_id]).fetchall()[0]
        assert {"IMPOSSIBLE_TRAVEL", "EMAIL_CHANGE_AFTER_RESET", "HIGH_VALUE_PURCHASE"} <= set(codes)
        assert action != "allow"
