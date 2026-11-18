"""Weekly fraud intel brief: weekly metrics from the warehouse, written up as a short brief.

The numbers always come from SQL. The write-up comes from one of two writers:
  template_brief()  deterministic, no API key needed (the default)
  claude_brief()    Claude writes the narrative from the same numbers, when ANTHROPIC_API_KEY is set

Claude only ever sees the computed metrics (never raw customer rows) and is told not to invent figures.
"""
import json
import os
from datetime import date

import pandas as pd

MODEL = "claude-opus-5-5"
PATTERNS = ["card_testing", "trial_abuse", "ato", "friendly_fraud"]
PATTERN_NAMES = {"card_testing": "card testing", "trial_abuse": "trial abuse", "ato": "account takeover",
                 "friendly_fraud": "friendly fraud"}

WEEKLY_SQL = """
WITH weeks AS (
    SELECT DISTINCT date_trunc('week', ts) AS week FROM transactions
),
payments AS (
    SELECT date_trunc('week', ts) AS week,
           sum(amount) FILTER (WHERE txn_type = 'charge' AND result = 'approved')       AS approved_usd,
           count(*) FILTER (WHERE txn_type = 'charge')                                 AS charge_attempts,
           avg((result = 'declined')::INT) FILTER (WHERE txn_type = 'charge')          AS charge_decline_rate,
           count(*) FILTER (WHERE txn_type = 'auth' AND amount <= 2)                   AS micro_auths,
           avg((result = 'declined')::INT) FILTER (WHERE txn_type = 'auth' AND amount <= 2) AS micro_auth_decline_rate
    FROM transactions GROUP BY 1
),
alerts_wk AS (
    SELECT date_trunc('week', event_ts) AS week, pattern, count(*) AS alerts, sum(fraud_usd_if_true) AS exposure_usd
    FROM scored_entities WHERE recommended_action <> 'allow' GROUP BY ALL
),
alerts_pivot AS (
    SELECT week,
           sum(alerts) FILTER (WHERE pattern = 'card_testing')   AS alerts_card_testing,
           sum(alerts) FILTER (WHERE pattern = 'trial_abuse')    AS alerts_trial_abuse,
           sum(alerts) FILTER (WHERE pattern = 'ato')            AS alerts_ato,
           sum(alerts) FILTER (WHERE pattern = 'friendly_fraud') AS alerts_friendly_fraud,
           sum(exposure_usd)                                     AS flagged_exposure_usd
    FROM alerts_wk GROUP BY 1
),
trials AS (
    SELECT date_trunc('week', trial_start_ts) AS week, count(*) AS trial_starts,
           avg(converted::INT) FILTER (WHERE converted IS NOT NULL) AS trial_conversion_rate
    FROM subscriptions WHERE is_trial GROUP BY 1
),
disputes_wk AS (
    SELECT date_trunc('week', filed_ts) AS week, count(*) AS disputes_filed,
           count(*) FILTER (WHERE reason_category = 'unauthorized') AS unauthorized_disputes
    FROM disputes GROUP BY 1
),
signups AS (
    SELECT date_trunc('week', signup_ts) AS week, count(*) AS new_accounts FROM users GROUP BY 1
)
SELECT w.week, s.new_accounts, t.trial_starts, t.trial_conversion_rate,
       p.approved_usd, p.charge_attempts, p.charge_decline_rate, p.micro_auths, p.micro_auth_decline_rate,
       a.alerts_card_testing, a.alerts_trial_abuse, a.alerts_ato, a.alerts_friendly_fraud, a.flagged_exposure_usd,
       d.disputes_filed, d.unauthorized_disputes
FROM weeks w
LEFT JOIN payments p USING (week) LEFT JOIN alerts_pivot a USING (week) LEFT JOIN trials t USING (week)
LEFT JOIN disputes_wk d USING (week) LEFT JOIN signups s USING (week)
ORDER BY w.week
"""


def weekly_metrics(con) -> pd.DataFrame:
    df = con.execute(WEEKLY_SQL).df()
    df["week"] = pd.to_datetime(df["week"]).dt.date
    counts = [c for c in df.columns if c.startswith(("alerts_", "new_", "trial_starts", "disputes", "unauthorized",
                                                     "micro_auths", "charge_attempts"))]
    df[counts] = df[counts].fillna(0).astype(int)
    return df


def complete_weeks(df: pd.DataFrame) -> list[date]:
    """Weeks with a full 7 days of data (drops a partial first and last week)."""
    return df["week"].tolist()[1:-1] if len(df) > 2 else df["week"].tolist()


def top_alerts(con, week: date, n: int = 5) -> list[dict]:
    rows = con.execute("""
        SELECT pattern, entity_type, entity_id, risk_score, recommended_action,
               CAST(reason_codes AS VARCHAR) AS reason_codes, round(fraud_usd_if_true, 2) AS exposure_usd
        FROM scored_entities
        WHERE recommended_action <> 'allow' AND date_trunc('week', event_ts) = ?
        ORDER BY fraud_usd_if_true DESC, risk_score DESC LIMIT ?""", [week, n]).df()
    return rows.to_dict("records")


def build_facts(con, week: date) -> dict:
    """Everything the brief may say, as plain numbers: this week, last week, the 4-week baseline."""
    df = weekly_metrics(con).set_index("week")
    weeks = df.index.tolist()
    i = weeks.index(week)
    this, prev = df.iloc[i], df.iloc[i - 1] if i > 0 else None
    base = df.iloc[max(0, i - 4):i]
    def clean(v):
        if pd.isna(v):
            return None
        v = float(v)
        return int(v) if v.is_integer() else round(v, 4)
    metrics = {}
    for col in df.columns:
        metrics[col] = {
            "this_week": clean(this[col]),
            "last_week": clean(prev[col]) if prev is not None else None,
            "four_week_avg": clean(base[col].mean()) if len(base) else None,
        }
    last_week_in_data = weeks[-1]
    return {
        "week_starting": week.isoformat(),
        "weeks_until_end_of_data": len([w for w in weeks if w > week]),
        "is_recent": (last_week_in_data - week).days <= 35,
        "metrics": metrics,
        "top_alerts": top_alerts(con, week),
        "notes": [
            "All data is synthetic (simulated subscription business).",
            "Disputes arrive a median ~30 days after purchase, so dispute counts for recent weeks are incomplete.",
            "Alerts use each detector's default thresholds (60+ = actioned).",
        ],
    }


# ---------- writers ----------
def _pct(x):
    return "n/a" if x is None else f"{x:.1%}"


def _delta(m: dict) -> str:
    now, base = m["this_week"], m["four_week_avg"]
    if now is None or not base:
        return ""
    change = (now - base) / base
    return f" ({change:+.0%} vs 4-week avg)"


def template_brief(facts: dict) -> str:
    """Deterministic brief: same facts in, same text out. Used when no API key is configured."""
    m = facts["metrics"]
    total_alerts = sum(m[f"alerts_{p}"]["this_week"] or 0 for p in PATTERNS)
    lines = [f"# Weekly fraud intel brief: week of {facts['week_starting']}", ""]
    lines.append("## Headline")
    busiest = max(PATTERNS, key=lambda p: m[f"alerts_{p}"]["this_week"] or 0)
    lines.append(f"{total_alerts} alerts this week; most came from **{PATTERN_NAMES[busiest]}** "
                 f"({m[f'alerts_{busiest}']['this_week']}). Flagged exposure: "
                 f"${(m['flagged_exposure_usd']['this_week'] or 0):,.0f}.")
    lines += ["", "## By pattern"]
    for p in PATTERNS:
        lines.append(f"- **{PATTERN_NAMES[p].capitalize()}:** {m[f'alerts_{p}']['this_week']} alerts"
                     f"{_delta(m[f'alerts_{p}'])}")
    lines += ["", "## Business signals",
              f"- Approved charges: ${(m['approved_usd']['this_week'] or 0):,.0f}{_delta(m['approved_usd'])}",
              f"- Charge decline rate: {_pct(m['charge_decline_rate']['this_week'])} "
              f"(4-week avg {_pct(m['charge_decline_rate']['four_week_avg'])})",
              f"- Micro auths (<= $2): {m['micro_auths']['this_week']}{_delta(m['micro_auths'])}, "
              f"{_pct(m['micro_auth_decline_rate']['this_week'])} declined",
              f"- Trial starts: {m['trial_starts']['this_week']}{_delta(m['trial_starts'])}",
              f"- Disputes filed: {m['disputes_filed']['this_week']} "
              f"({m['unauthorized_disputes']['this_week']} 'unauthorized')"]
    if facts["top_alerts"]:
        lines += ["", "## Top alerts by exposure"]
        for a in facts["top_alerts"]:
            lines.append(f"- {PATTERN_NAMES[a['pattern']]} · {a['entity_type']} `{a['entity_id']}` · score "
                         f"{a['risk_score']} · ${a['exposure_usd']:,.0f} · {a['recommended_action']}")
    lines += ["", "## Caveats"]
    if facts["is_recent"]:
        lines.append("- This is a recent week: disputes and chargebacks for it are still arriving, so dispute "
                     "numbers will rise. Don't read a low count as improvement yet.")
    lines += [f"- {n}" for n in facts["notes"] if "synthetic" in n]
    return "\n".join(lines)


SYSTEM_PROMPT = """You write the weekly fraud intelligence brief for the payments and commercial abuse team of a
subscription software business. Your readers are fraud analysts and their manager.

Write from the JSON facts you are given and nothing else:
- Use only numbers that appear in the facts (you may compute simple differences or percentages from them).
  If something isn't in the facts, don't mention it.
- Compare this week with last week and with the 4-week average, and call out what changed and why it matters.
- Patterns: card testing, trial abuse, account takeover, friendly fraud.
- If the week is recent, remind readers that disputes arrive weeks late, so low dispute counts are not improvement.
- Suggest at most three concrete next actions an analyst could take.
- Mention once that the data is synthetic.

Format: Markdown, a title line, then sections Headline, What changed, By pattern, Recommended actions,
Caveats. Under 350 words. Plain, direct sentences."""


def claude_brief(facts: dict, client=None) -> str:
    """Claude writes the narrative from the facts. Falls back to the template if it declines."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (or another configured credential)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        # If the model declines, the API retries the same request on a suitable fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": "Facts for this week's brief:\n\n" + json.dumps(facts, indent=2, default=str)}],
    )
    if response.stop_reason == "refusal":
        return template_brief(facts)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or template_brief(facts)


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.db import connect
    con = connect(read_only=True)
    week = complete_weeks(weekly_metrics(con))[-1]
    facts = build_facts(con, week)
    print(claude_brief(facts) if has_api_key() else template_brief(facts))
