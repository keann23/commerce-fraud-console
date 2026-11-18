"""Score each detection against ground_truth. Only this module and tests may read ground_truth.

Definitions (per pattern, at the entity level the detection works on):
  flagged          recommended_action is anything other than 'allow'
  recall           injected attack entities flagged / injected attack entities
  precision        flagged entities that are attacks / all flagged entities
  fpr_legit        flagged legit entities / all legit entities the detection scored
  fpr_lookalike    flagged lookalikes / lookalikes (the honest test: legit entities built to look bad)
  campaign_recall  campaigns with at least one flagged entity / campaigns
"""
import re

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


# ---------- helpers for the app (the only place screens may get ground-truth labels) ----------
STRONGEST_STEP = {"card_testing": "block", "trial_abuse": "block", "ato": "review", "friendly_fraud": "review"}
STEP_FRICTION = {"allow": 0.0, "step_up": 0.05, "review": 0.10, "block": 1.0}
STEP_STOP_RATE = {"allow": 0.0, "step_up": 0.90, "review": 1.0, "block": 1.0}
FORBIDDEN_SQL = ("drop", "delete", "insert", "update", "attach", "copy", "create", "alter", "pragma",
                 "install", "load", "call", "export", "import", "detach", "truncate")


def labeled_scores(con) -> pd.DataFrame:
    """Every scored entity with its truth label: attack, lookalike or legit."""
    return con.execute("""
        WITH truth AS (
            SELECT attack_type AS pattern, entity_type, entity_id,
                   max(CASE WHEN label = 'attack' THEN 1 ELSE 0 END) AS is_attack,
                   max(CASE WHEN label = 'lookalike' THEN 1 ELSE 0 END) AS is_lookalike,
                   any_value(campaign_id) AS campaign_id
            FROM ground_truth GROUP BY ALL
        )
        SELECT s.*, coalesce(t.is_attack, 0) = 1 AS is_attack, coalesce(t.is_lookalike, 0) = 1 AS is_lookalike,
               t.campaign_id
        FROM scored_entities s
        LEFT JOIN truth t USING (pattern, entity_type, entity_id)""").df()


def tradeoff(con, pattern: str | None = None, thresholds=range(0, 101, 5)) -> pd.DataFrame:
    """For each alert threshold, compare a block-only policy with the response ladder.

    Ladder: scores within 20 points above the threshold get a step-up; higher scores get the
    pattern's strongest step (block for card testing / trial abuse, review for ATO / friendly fraud).
    """
    df = labeled_scores(con)
    if pattern:
        df = df[df.pattern == pattern]
    legit = ~df.is_attack
    strongest = df.pattern.map(STRONGEST_STEP)
    strong_friction, strong_stop = strongest.map(STEP_FRICTION), strongest.map(STEP_STOP_RATE)
    rows = []
    for t in thresholds:
        hit = df.risk_score >= t
        mid = df.risk_score < t + 20
        ladder = (strong_friction.where(~mid, STEP_FRICTION["step_up"]),
                  strong_stop.where(~mid, STEP_STOP_RATE["step_up"]))
        block_only = (pd.Series(STEP_FRICTION["block"], index=df.index),
                      pd.Series(STEP_STOP_RATE["block"], index=df.index))
        for policy, (friction_all, stop_all) in (("block_only", block_only), ("ladder", ladder)):
            friction = friction_all.where(hit, 0.0)
            stop = stop_all.where(hit, 0.0)
            rows.append({
                "threshold": t,
                "policy": policy,
                "fraud_stopped_usd": float((df.fraud_usd_if_true * stop)[df.is_attack].sum()),
                "fraud_missed_usd": float((df.fraud_usd_if_true * (1 - stop))[df.is_attack].sum()),
                "legit_actioned": int((hit & legit).sum()),
                "expected_false_declines": float(friction[legit].sum()),
                "monthly_revenue_lost_usd": float((df.monthly_revenue_usd * friction)[legit].sum()),
                "recall": float((hit & df.is_attack).sum() / max(df.is_attack.sum(), 1)),
            })
    return pd.DataFrame(rows)


def overview(con) -> dict:
    """Headline numbers under the current recommended actions."""
    df = labeled_scores(con)
    attacks, legit = df[df.is_attack], df[~df.is_attack]
    return {
        "fraud_prevented_usd": float((attacks.fraud_usd_if_true * attacks.fraud_stop_rate).sum()),
        "fraud_missed_usd": float((attacks.fraud_usd_if_true * (1 - attacks.fraud_stop_rate)).sum()),
        "false_declines": int((legit.recommended_action == "block").sum()),
        "legit_challenged": int((legit.recommended_action != "allow").sum()),
        "expected_legit_lost": float(legit.friction_rate.sum()),
    }


def campaign_report(con, campaign_id: str) -> pd.DataFrame:
    """For Attack Mode: each entity of one campaign that its pattern is evaluated on (e.g. IPs and devices
    for card testing, not the tester's throwaway accounts), its score, action, and whether it was caught."""
    evaluated = [(pattern, t) for pattern, spec in PATTERNS.items() for t in spec["entity_types"]]
    return con.execute("""
        WITH evaluated(attack_type, entity_type) AS (SELECT unnest($pairs, recursive := true))
        SELECT g.label, g.attack_type, g.entity_type, g.entity_id, s.pattern AS scored_by, s.risk_score,
               s.recommended_action, s.reason_codes,
               coalesce(s.recommended_action <> 'allow', false) AS flagged
        FROM ground_truth g
        LEFT JOIN scored_entities s
          ON s.entity_type = g.entity_type AND s.entity_id = g.entity_id AND s.pattern = g.attack_type
        SEMI JOIN evaluated e ON e.attack_type = g.attack_type AND e.entity_type = g.entity_type
        WHERE g.campaign_id = $campaign
        ORDER BY g.label, g.entity_type, s.risk_score DESC NULLS LAST""",
        {"campaign": campaign_id, "pairs": [{"attack_type": a, "entity_type": t} for a, t in evaluated]}).df()


def rule_backtest(con, where_clause: str) -> dict:
    """Run an analyst's WHERE clause over txn_features and count attack vs legit hits."""
    words = set(re.findall(r"[a-z_]+", where_clause.lower()))
    if ";" in where_clause or words & set(FORBIDDEN_SQL):
        raise ValueError("Only a boolean WHERE expression is allowed (no ';' or DDL/DML keywords).")
    hits = con.execute(f"""
        WITH attack_txn AS (
            SELECT DISTINCT f.txn_id, g.attack_type
            FROM txn_features f
            JOIN ground_truth g ON g.label = 'attack' AND (
                   (g.entity_type = 'txn' AND g.entity_id = f.txn_id)
                OR (g.entity_type = 'user' AND g.entity_id = f.user_id AND g.attack_type <> 'friendly_fraud')
                OR (g.entity_type = 'ip' AND g.entity_id = f.ip)
                OR (g.entity_type = 'device' AND g.entity_id = f.device_id))
        )
        SELECT f.*, a.attack_type, a.txn_id IS NOT NULL AS is_attack
        FROM txn_features f LEFT JOIN attack_txn a USING (txn_id)
        WHERE ({where_clause})""").df()
    totals = con.execute("""SELECT count(*) FROM txn_features""").fetchall()[0][0]
    return {
        "matches": hits,
        "total_attempts": totals,
        "attack_hits": int(hits.is_attack.sum()),
        "legit_hits": int((~hits.is_attack).sum()),
        "by_attack_type": hits[hits.is_attack].attack_type.value_counts().to_dict(),
    }
