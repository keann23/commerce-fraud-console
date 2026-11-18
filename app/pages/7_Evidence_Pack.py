"""Screen 8: Evidence Pack. One-click PDF to represent a friendly fraud dispute."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import q, reasons, setup_page  # noqa: E402
from src.evidence_pack import build_evidence_pdf  # noqa: E402

setup_page("Evidence Pack", "📄")
st.title("Evidence Pack")
st.markdown("For disputes scored as likely **friendly fraud**, assemble what the issuer needs to reverse the "
            "chargeback: the purchase came from the customer's own device and IP, and they kept using the product.")

cases = q("""SELECT d.*, t.device_id, t.ip FROM detect_friendly_fraud d JOIN transactions t USING (txn_id)
             WHERE d.recommended_action = 'review' ORDER BY d.risk_score DESC, d.amount DESC""")
if cases.empty:
    st.info("No disputes flagged for representment. Launch friendly fraud in Attack Mode.")
    st.stop()

labels = {r.entity_id: f"{r.entity_id} · ${r.amount:,.2f} · score {r.risk_score} · {r.status}" for r in cases.itertuples()}
dispute_id = st.selectbox("Dispute to represent", list(labels), format_func=labels.get)
case = cases.set_index("entity_id").loc[dispute_id].to_dict() | {"dispute_id": dispute_id}

c1, c2, c3, c4 = st.columns(4)
c1.metric("Prior purchases, same device", int(case["prior_same_device"]))
c2.metric("Prior purchases, same IP", int(case["prior_same_ip"]))
c3.metric("Minutes used after purchase", f"{int(case['minutes_after']):,}")
c4.metric("Tenure at purchase", f"{int(case['tenure_days_at_purchase'])} days")
st.caption(f"Reason codes: {reasons(case['reason_codes'])}")

prior = q("""SELECT p.ts, p.amount, p.device_id, p.ip, d.dispute_id IS NOT NULL AS disputed
             FROM transactions p LEFT JOIN disputes d USING (txn_id)
             WHERE p.user_id = ? AND p.ts < ? AND p.txn_type = 'charge' AND p.result = 'approved'
             ORDER BY p.ts DESC LIMIT 12""", [case["user_id"], case["txn_ts"]])
usage = q("""SELECT date, app, sessions, minutes FROM usage_events
             WHERE user_id = ? AND date > CAST(? AS DATE) AND date <= CAST(? AS DATE) ORDER BY date LIMIT 30""",
          [case["user_id"], case["txn_ts"], case["filed_ts"]])
logins = q("""SELECT ts, device_id, ip, country FROM logins
              WHERE user_id = ? AND success AND ts > ? AND ts <= ? ORDER BY ts LIMIT 20""",
           [case["user_id"], case["txn_ts"], case["filed_ts"]])

tab1, tab2, tab3 = st.tabs(["Earlier purchases", "Usage after purchase", "Logins after purchase"])
tab1.dataframe(prior, hide_index=True, use_container_width=True)
tab2.dataframe(usage, hide_index=True, use_container_width=True)
tab3.dataframe(logins, hide_index=True, use_container_width=True)

pdf = build_evidence_pdf(case, prior.to_dict("records"), usage.to_dict("records"), logins.to_dict("records"))
st.download_button("⬇️ Download evidence pack (PDF)", data=pdf, file_name=f"evidence_{dispute_id}.pdf",
                   mime="application/pdf", type="primary")
