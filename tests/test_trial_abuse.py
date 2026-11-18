"""Trial abuse: identity linking, detection quality, injector contract."""
from src.db import run_detection
from src.evaluate import evaluate_pattern
from src.generate.attacks.trial_abuse import inject_trial_abuse

MIN_RECALL = 0.85
MAX_FPR = 0.02


def test_trial_abuse_recall(small_db):
    result = evaluate_pattern(small_db, "trial_abuse")
    assert result["attack_entities"] > 0
    assert result["recall"] >= MIN_RECALL, result


def test_trial_abuse_false_positive_rates(small_db):
    result = evaluate_pattern(small_db, "trial_abuse")
    assert result["lookalikes"] > 0, "injector must create legit lookalikes"
    assert result["fpr_legit"] < MAX_FPR, result
    assert result["fpr_lookalike"] < MAX_FPR, result


def test_required_detection_columns(small_db):
    cols = {r[0] for r in small_db.execute("DESCRIBE detect_trial_abuse").fetchall()}
    assert {"entity_id", "risk_score", "reason_codes", "recommended_action"} <= cols


def test_email_tricks_collapse_into_one_cluster(injection_db):
    """Dot and plus variants of one inbox must land in the same identity cluster even with no
    shared device or card."""
    con = injection_db
    campaign = inject_trial_abuse(con, seed=77, n_accounts=15, n_devices=3, n_virtual_cards=3,
                                  fresh_card_rate=1.0, start_day=30, with_lookalikes=False)
    run_detection(con)
    rows = con.execute("""
        SELECT d.cluster_id, u.email FROM ground_truth g
        JOIN users u ON u.user_id = g.entity_id
        JOIN detect_trial_abuse d ON d.entity_id = g.entity_id
        WHERE g.campaign_id = ? AND u.email LIKE '%@gmail.com'
          AND (u.email LIKE '%.%@%' OR u.email LIKE '%+%')""", [campaign]).fetchall()
    alias_clusters = {cluster for cluster, email in rows if not email.split("@")[0].isalnum()}
    assert rows and len(alias_clusters) == 1, rows


def test_injector_contract(injection_db):
    con = injection_db
    campaign = inject_trial_abuse(con, seed=78, n_accounts=12, start_day=10)
    assert campaign.startswith("TA-")
    labels = dict(con.execute("""SELECT label, count(*) FROM ground_truth WHERE campaign_id = ?
                                 GROUP BY 1""", [campaign]).fetchall())
    assert labels["attack"] == 12 and labels.get("lookalike", 0) > 0
    converted = con.execute("""SELECT count(*) FROM subscriptions s JOIN ground_truth g ON g.entity_id = s.user_id
                               WHERE g.campaign_id = ? AND g.label = 'attack' AND s.converted""",
                            [campaign]).fetchall()[0][0]
    assert converted == 0
