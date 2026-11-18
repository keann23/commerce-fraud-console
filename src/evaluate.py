"""Score each detection against ground_truth. Only this module and tests may read ground_truth.

Definitions (per pattern, at the entity level the detection works on):
  flagged          recommended_action is anything other than 'allow'
  recall           injected attack entities flagged / injected attack entities
  precision        flagged entities that are attacks / all flagged entities
  fpr_legit        flagged legit entities / all legit entities the detection scored
  fpr_lookalike    flagged lookalikes / lookalikes (the honest test: legit entities built to look bad)
  campaign_recall  campaigns with at least one flagged entity / campaigns
"""
import pandas as pd

from src.db import connect

PATTERNS = {
    "card_testing": {"table": "detect_card_testing", "entity_types": ["ip", "device"]},
    "trial_abuse": {"table": "detect_trial_abuse", "entity_types": ["user"]},
    "ato": {"table": "detect_ato", "entity_types": ["user"]},
    "friendly_fraud": {"table": "detect_friendly_fraud", "entity_types": ["dispute"]},
}


def evaluate_pattern(con, pattern: str) -> dict:
    spec = PATTERNS[pattern]
    row = con.execute(f"""
        WITH det AS (
            SELECT entity_type, entity_id, recommended_action <> 'allow' AS flagged FROM {spec['table']}
        ),
        attacks AS (
            SELECT DISTINCT entity_type, entity_id, campaign_id FROM ground_truth
            WHERE attack_type = $pattern AND label = 'attack' AND list_contains($types, entity_type)
        ),
        any_attack AS (  -- entities that belong to ANY attack are not legit for FPR purposes
            SELECT DISTINCT entity_type, entity_id FROM ground_truth WHERE label = 'attack'
        ),
        lookalikes AS (
            SELECT DISTINCT entity_type, entity_id FROM ground_truth
            WHERE attack_type = $pattern AND label = 'lookalike' AND list_contains($types, entity_type)
        ),
        legit AS (
            SELECT d.* FROM det d ANTI JOIN any_attack USING (entity_type, entity_id)
        ),
        attack_hits AS (
            SELECT a.*, coalesce(d.flagged, false) AS flagged
            FROM attacks a LEFT JOIN det d USING (entity_type, entity_id)
        )
        SELECT
            (SELECT count(DISTINCT (entity_type, entity_id)) FROM attacks)                         AS n_attack,
            (SELECT count(DISTINCT (entity_type, entity_id)) FROM attack_hits WHERE flagged)       AS tp,
            (SELECT count(*) FROM legit WHERE flagged)                                             AS fp,
            (SELECT count(*) FROM legit)                                                           AS n_legit,
            (SELECT count(*) FROM lookalikes)                                                      AS n_lookalike,
            (SELECT count(*) FROM lookalikes JOIN det USING (entity_type, entity_id) WHERE flagged) AS fp_lookalike,
            (SELECT count(DISTINCT campaign_id) FROM attacks)                                      AS n_campaigns,
            (SELECT count(DISTINCT campaign_id) FROM attack_hits WHERE flagged)                    AS campaigns_hit
    """, {"pattern": pattern, "types": spec["entity_types"]}).fetchone()
    n_attack, tp, fp, n_legit, n_lookalike, fp_lookalike, n_campaigns, campaigns_hit = row

    def ratio(a, b):
        return a / b if b else float("nan")

    return {
        "pattern": pattern,
        "attack_entities": n_attack,
        "caught": tp,
        "recall": ratio(tp, n_attack),
        "precision": ratio(tp, tp + fp),
        "fpr_legit": ratio(fp, n_legit),
        "fpr_lookalike": ratio(fp_lookalike, n_lookalike),
        "false_positives": fp,
        "lookalikes": n_lookalike,
        "campaign_recall": ratio(campaigns_hit, n_campaigns),
    }


def evaluate_all(con) -> pd.DataFrame:
    return pd.DataFrame([evaluate_pattern(con, p) for p in PATTERNS])


if __name__ == "__main__":
    with connect(read_only=True) as con:
        report = evaluate_all(con)
    with pd.option_context("display.float_format", "{:.3f}".format, "display.width", 140):
        print(report.to_string(index=False))
