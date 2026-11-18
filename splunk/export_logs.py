"""Export the synthetic warehouse as JSON-lines event logs, one file per Splunk sourcetype.

Splunk works on events, not tables, so each file is a stream of timestamped events with the
fields an analyst would have in real logs (card details joined onto payments, account facts
onto signups). ground_truth is exported separately as a lookup, for scoring searches only.

  python splunk/export_logs.py            -> data/splunk/*.json
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

OUT = ROOT / "data" / "splunk"

EVENTS = {
    "fraud:payments": """
        SELECT t.ts, t.txn_id, t.user_id, t.pm_id, CAST(t.amount AS DOUBLE) AS amount, t.currency, t.txn_type,
               t.result, t.decline_reason, t.ip, t.device_id, p.card_fingerprint, p.bin, p.last4, p.card_country,
               p.is_virtual_or_prepaid
        FROM transactions t LEFT JOIN payment_methods p USING (pm_id)""",
    "fraud:logins": "SELECT ts, login_id, user_id, ip, country, lat, lon, device_id, success, mfa_used FROM logins",
    "fraud:account_events": "SELECT ts, event_id, user_id, event_type, device_id, ip FROM account_events",
    "fraud:signups": """
        SELECT u.signup_ts AS ts, u.user_id, u.email, u.country, u.signup_ip, u.signup_device_id,
               s.plan, s.is_trial, s.trial_start_ts, s.trial_end_ts, s.converted, s.status, s.canceled_ts
        FROM users u LEFT JOIN subscriptions s USING (user_id)""",
    "fraud:payment_methods": """
        SELECT added_ts AS ts, pm_id, user_id, card_fingerprint, bin, last4, card_country, is_virtual_or_prepaid
        FROM payment_methods""",
    "fraud:usage": "SELECT CAST(date AS TIMESTAMP) AS ts, user_id, app, sessions, minutes FROM usage_events",
    "fraud:disputes": """
        SELECT d.filed_ts AS ts, d.dispute_id, d.txn_id, d.reason_category, d.status, d.responded_ts, d.outcome,
               t.user_id, t.ts AS txn_ts
        FROM disputes d JOIN transactions t USING (txn_id)""",
}
LOOKUPS = {
    "ground_truth.csv": "SELECT entity_type, entity_id, campaign_id, attack_type, label FROM ground_truth",
    "disposable_domains.csv": "SELECT domain FROM disposable_domains",
}


def export(out_dir: Path = OUT, con=None) -> dict[str, int]:
    con = con or connect(read_only=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for sourcetype, sql in EVENTS.items():
        df = con.execute(f"SELECT * FROM ({sql}) ORDER BY ts").df()
        path = out_dir / f"{sourcetype.split(':')[1]}.json"
        with path.open("w") as f:
            for row in df.to_dict("records"):
                row = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()
                       if v is not None and v == v}  # drop NULL / NaN: absent fields, as in real logs
                f.write(json.dumps(row, default=str) + "\n")
        counts[sourcetype] = len(df)
    for name, sql in LOOKUPS.items():
        con.execute(sql).df().to_csv(out_dir / name, index=False)
    return counts


if __name__ == "__main__":
    for st, n in export().items():
        print(f"{st:<24}{n:>10,} events")
    print(f"written to {OUT.relative_to(ROOT)}/  (see splunk/README.md to load them)")
