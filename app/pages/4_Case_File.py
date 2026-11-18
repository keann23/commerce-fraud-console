"""Screen 5: Case File. One account's timeline, linked entities, and decision buttons that are logged."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from common import ACTION_LABELS, PATTERN_LABELS, cursor, q, reasons, setup_page  # noqa: E402
from guide import page_intro, tip  # noqa: E402

setup_page("Case File", "🗂️")
st.title("Case File")
page_intro("case_file")

case = st.session_state.get("case")
alerts = q("SELECT pattern, entity_type, entity_id, risk_score FROM alerts ORDER BY risk_score DESC")
options = [f"{r.pattern}|{r.entity_type}|{r.entity_id}" for r in alerts.itertuples()]
current = f"{case['pattern']}|{case['entity_type']}|{case['entity_id']}" if case else (options[0] if options else None)
if current and current not in options:
    options.insert(0, current)
c1, c2 = st.columns([3, 2])
picked = c1.selectbox("Case", options, index=options.index(current) if current else 0,
                      format_func=lambda s: "  ·  ".join([PATTERN_LABELS[s.split('|')[0]], *s.split('|')[1:]]))
typed = c2.text_input("…or look up any user / IP / device / dispute id", placeholder="U000123")
pattern, entity_type, entity_id = picked.split("|")
if typed:
    entity_id = typed.strip()
    entity_type = ("user" if entity_id.startswith("U") else "dispute" if entity_id.startswith("DP")
                   else "device" if entity_id.startswith("D") else "ip")
    pattern = None

scores = q("SELECT * FROM scored_entities WHERE entity_type = ? AND entity_id = ? ORDER BY risk_score DESC",
           [entity_type, entity_id])
if not scores.empty:
    top = scores.iloc[0] if pattern is None else scores[scores.pattern == pattern].iloc[0]
    pattern = top.pattern
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pattern", PATTERN_LABELS[top.pattern])
    m2.metric("Risk score", int(top.risk_score))
    m3.metric("Recommended", ACTION_LABELS[top.recommended_action])
    m4.metric("Exposure", f"${top.fraud_usd_if_true:,.0f}")
    st.markdown(f"**Reason codes:** {reasons(top.reason_codes) or 'none'}  \n**Action:** {top.action_detail}")
else:
    st.info("This entity has no detection score.")

# Resolve the entity to the account(s) to show.
if entity_type == "user":
    users = [entity_id]
elif entity_type == "dispute":
    users = q("SELECT t.user_id FROM disputes d JOIN transactions t USING (txn_id) WHERE d.dispute_id = ?",
              [entity_id]).user_id.tolist()
else:
    column = "ip" if entity_type == "ip" else "device_id"
    involved = q(f"""SELECT user_id, count(*) AS attempts, sum((result = 'declined')::INT) AS declined,
                            min(ts) AS first_ts, max(ts) AS last_ts
                     FROM payment_attempts WHERE {column} = ? GROUP BY 1 ORDER BY attempts DESC""", [entity_id])
    st.subheader(f"Accounts that transacted from this {entity_type}")
    st.dataframe(involved, hide_index=True, use_container_width=True)
    users = involved.user_id.head(25).tolist()

if users:
    user_id = st.selectbox("Account", users) if len(users) > 1 else users[0]
    profile = q("""SELECT u.user_id, u.email, u.email_normalized, u.country, u.signup_ts, u.account_age_days,
                          s.plan, s.status, s.is_trial, s.converted, c.cluster_id
                   FROM users u LEFT JOIN subscriptions s USING (user_id) LEFT JOIN identity_clusters c USING (user_id)
                   WHERE u.user_id = ?""", [user_id])
    st.subheader(f"Account {user_id}")
    st.dataframe(profile, hide_index=True, use_container_width=True)

    cur = cursor()
    timeline = cur.execute("""
        SELECT ts, CASE WHEN success THEN 'login ok' ELSE 'login failed' END AS kind,
               coalesce(country, '') || ' · ' || coalesce(device_id, '') || ' · ' || coalesce(ip, '') AS detail,
               NULL::DOUBLE AS amount
        FROM logins WHERE user_id = $u
        UNION ALL
        SELECT ts, event_type, coalesce(device_id, '') || ' · ' || coalesce(ip, ''), NULL
        FROM account_events WHERE user_id = $u
        UNION ALL
        SELECT ts, txn_type || ' ' || result,
               coalesce(decline_reason || ' · ', '') || coalesce(device_id, '') || ' · ' || coalesce(ip, ''),
               CAST(amount AS DOUBLE)
        FROM transactions WHERE user_id = $u
        UNION ALL
        SELECT d.filed_ts, 'dispute: ' || d.reason_category, d.status || ' / ' || d.outcome, CAST(t.amount AS DOUBLE)
        FROM disputes d JOIN transactions t USING (txn_id) WHERE t.user_id = $u
        ORDER BY ts""", {"u": user_id}).df()
    usage = cur.execute("SELECT date, sum(minutes) AS minutes FROM usage_events WHERE user_id = ? GROUP BY 1 ORDER BY 1",
                        [user_id]).df()
    cur.close()

    st.subheader("Timeline")
    tip("Read left to right. For ATO look for: new-device login → password_reset → email_change → "
        "payment_method_add → charge, all from the same device. For friendly fraud: a charge, steady usage "
        "(bars below), then a dispute weeks later.")
    if not timeline.empty:
        fig = px.scatter(timeline, x="ts", y="kind", color="kind", hover_data=["detail", "amount"], height=360)
        fig.update_traces(marker=dict(size=10))
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="", xaxis_title="")
        st.plotly_chart(fig, use_container_width=True)
    if not usage.empty:
        fig = px.bar(usage, x="date", y="minutes", height=180, labels={"minutes": "Product minutes", "date": ""})
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    with st.expander(f"All {len(timeline)} events"):
        st.dataframe(timeline, hide_index=True, use_container_width=True)

    st.subheader("Linked entities")
    links = q("""SELECT l.link_type, l.link_value, string_agg(o.user_id, ', ' ORDER BY o.user_id) AS other_accounts,
                        count(o.user_id) AS n_other
                 FROM identity_links l
                 LEFT JOIN identity_links o ON o.link_type = l.link_type AND o.link_value = l.link_value
                                           AND o.user_id <> l.user_id
                 WHERE l.user_id = ? GROUP BY ALL ORDER BY n_other DESC""", [user_id])
    st.dataframe(links, hide_index=True, use_container_width=True)

if not scores.empty:
    st.subheader("Decision")
    note = st.text_input("Note (optional)")
    cols = st.columns(4)
    for col, decision in zip(cols, ["allow", "step_up", "review", "block"]):
        label = "Approve" if decision == "allow" else ACTION_LABELS[decision]
        if col.button(label, use_container_width=True, type="primary" if decision == top.recommended_action else "secondary"):
            cur = cursor()
            cur.execute("""INSERT INTO case_decisions (pattern, entity_type, entity_id, decision, note)
                           VALUES (?, ?, ?, ?, ?)""", [pattern, entity_type, entity_id, decision, note])
            cur.close()
            st.toast(f"Logged: {label} on {entity_id}")
    history = q("""SELECT decided_ts, decision, note FROM case_decisions WHERE entity_type = ? AND entity_id = ?
                   ORDER BY decided_ts DESC""", [entity_type, entity_id])
    if not history.empty:
        st.dataframe(history, hide_index=True, use_container_width=True)
