"""Screen 1: Overview. Fraud prevented, false declines, dispute ratio, alerts by pattern."""
import plotly.express as px
import streamlit as st

from common import ACTION_COLORS, ACTION_LABELS, PATTERN_LABELS, cursor, money, q, setup_page
from guide import PURPOSE, learning_mode, page_intro, tip
from src.evaluate import evaluate_all, overview

setup_page("Overview")
st.title("Commerce Fraud Investigator Console")
st.caption("A fraud analyst console and learning simulator for an Adobe-style subscription business. "
           "All data is synthetic.")
with st.expander("🎯 What this simulator is for", expanded=learning_mode()):
    st.markdown(PURPOSE)
    st.markdown("**Suggested path:** Learning Guide → Overview → Attack Mode → Case Queue → Case File → "
                "Ring Explorer → Friction Tradeoff → Dispute Lifecycle → Evidence Pack → Rule Simulator → Intel Brief.")
page_intro("overview")

cur = cursor()
stats = overview(cur)
dispute_month = q("""
    WITH charges AS (SELECT txn_id, date_trunc('month', ts) AS month FROM transactions
                     WHERE txn_type = 'charge' AND result = 'approved')
    SELECT month, count(d.dispute_id) / count(*) AS dispute_ratio, count(*) AS charges
    FROM charges c LEFT JOIN disputes d USING (txn_id) GROUP BY 1 ORDER BY 1""")
alerts = q("SELECT pattern, recommended_action, count(*) AS n FROM alerts GROUP BY ALL")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Fraud $ prevented", money(stats["fraud_prevented_usd"]),
          help="Exposure of attacks we actioned, times how often that step stops the attack.")
c2.metric("Fraud $ missed", money(stats["fraud_missed_usd"]))
c3.metric("False declines", f"{stats['false_declines']:,}", help="Legit entities whose action is Block.")
c4.metric("Legit customers challenged", f"{stats['legit_challenged']:,}",
          help="Legit entities sent to step-up or review: friction, not a decline.")
matured = q("""SELECT count(d.dispute_id) / count(*) AS ratio
               FROM transactions t LEFT JOIN disputes d USING (txn_id)
               WHERE t.txn_type = 'charge' AND t.result = 'approved'
                 AND t.ts <= (SELECT max(ts) FROM transactions) - INTERVAL 60 DAY""").iloc[0, 0]
c5.metric("Dispute ratio (matured)", f"{matured:.2%}",
          help="Charges at least 60 days old only: newer charges haven't received their disputes yet (label delay).")

left, right = st.columns([3, 2])
with left:
    st.subheader("Open alerts by pattern")
    alerts["pattern"] = alerts.pattern.map(PATTERN_LABELS)
    alerts["action"] = alerts.recommended_action.map(ACTION_LABELS)
    fig = px.bar(alerts, x="pattern", y="n", color="recommended_action", color_discrete_map=ACTION_COLORS,
                 labels={"n": "Alerts", "pattern": "", "recommended_action": "Action"}, height=330)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, use_container_width=True)
    tip("Trial abuse has the most alerts because one ring is many accounts, but each card testing alert "
        "carries far more money: the cards it validated get cashed out later.")
with right:
    st.subheader("Dispute ratio by charge month")
    fig = px.line(dispute_month, x="month", y="dispute_ratio", markers=True, height=330,
                  labels={"dispute_ratio": "Disputes / approved charges", "month": ""})
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("The drop in recent months is label delay, not improvement: disputes arrive 2 to 8 weeks late.")

st.subheader("Detection quality vs ground truth")
report = evaluate_all(cur)
report["pattern"] = report.pattern.map(PATTERN_LABELS)
st.dataframe(
    report[["pattern", "attack_entities", "caught", "recall", "precision", "fpr_legit", "fpr_lookalike",
            "lookalikes", "campaign_recall"]],
    hide_index=True, use_container_width=True,
    column_config={c: st.column_config.NumberColumn(format="%.3f")
                   for c in ["recall", "precision", "fpr_legit", "fpr_lookalike", "campaign_recall"]})
st.caption("Lookalikes are legit customers built to resemble each attack (families sharing a laptop, travelers, "
           "campus networks, customers retrying a failing card). FPR on lookalikes is the honest test.")
cur.close()

st.divider()
st.markdown("**Screens:** Attack Mode (launch attacks live) · Case Queue · Ring Explorer · Case File · "
            "Friction Tradeoff · Dispute Lifecycle · Evidence Pack · Rule Simulator")
