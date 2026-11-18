"""Screen 7: Dispute Lifecycle. Lag histogram, label maturity curve, dispute ratio trend, win rates."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from common import q, setup_page  # noqa: E402
from guide import page_intro, tip  # noqa: E402

setup_page("Dispute Lifecycle", "⏳")
st.title("Dispute Lifecycle")
page_intro("dispute_lifecycle")

lags = q("""SELECT d.dispute_id, d.reason_category, d.status, d.outcome, date_diff('day', t.ts, d.filed_ts) AS lag_days
            FROM disputes d JOIN transactions t USING (txn_id)""")
c1, c2, c3 = st.columns(3)
c1.metric("Disputes visible", f"{len(lags):,}")
c2.metric("Median lag", f"{lags.lag_days.median():.0f} days")
c3.metric("Still open", f"{(lags.status == 'open').sum():,}")

left, right = st.columns(2)
with left:
    st.subheader("Lag from purchase to dispute")
    fig = px.histogram(lags, x="lag_days", nbins=40, color="reason_category", height=330,
                       labels={"lag_days": "Days after purchase"})
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.25), bargap=0.05)
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.subheader("Label maturity curve")
    cohort = q("""
        WITH c AS (SELECT t.txn_id, t.ts FROM transactions t
                   WHERE t.txn_type = 'charge' AND t.result = 'approved'
                     AND t.ts < (SELECT min(ts) FROM transactions) + INTERVAL 30 DAY)
        SELECT date_diff('day', c.ts, d.filed_ts) AS lag_days FROM c JOIN disputes d USING (txn_id)""")
    horizon = int(cohort.lag_days.max()) if len(cohort) else 90
    days = list(range(0, horizon + 1))
    share = [(cohort.lag_days <= n).mean() for n in days] if len(cohort) else [0] * len(days)
    fig = go.Figure(go.Scatter(x=days, y=share, mode="lines", line_color="#1a73e8"))
    for n in (14, 30, 60):
        if n <= horizon:
            fig.add_annotation(x=n, y=share[n], text=f"day {n}: {share[n]:.0%}", showarrow=True, arrowhead=2)
    fig.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".0%",
                      xaxis_title="Days since purchase", yaxis_title="Share of eventual disputes known")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Oldest monthly cohort, observable for ~{horizon} days. Disputes beyond that are still unseen, "
               "so even this curve is slightly optimistic.")

tip("How to use the maturity curve: if only 60% of disputes are known 30 days after purchase, a 0.6% "
    "dispute ratio for last month really means about 1.0% once all labels arrive.")
st.subheader("Dispute ratio by purchase week")
weekly = q("""
    WITH c AS (SELECT txn_id, date_trunc('week', ts) AS week FROM transactions
               WHERE txn_type = 'charge' AND result = 'approved')
    SELECT week, count(d.dispute_id) / count(*) AS dispute_ratio FROM c LEFT JOIN disputes d USING (txn_id)
    GROUP BY 1 ORDER BY 1""")
fig = px.line(weekly, x="week", y="dispute_ratio", markers=True, height=280,
              labels={"dispute_ratio": "Disputes / approved charges", "week": ""})
fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), yaxis_tickformat=".2%")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Win rate by reason (closed disputes)")
st.dataframe(q("""SELECT reason_category, count(*) AS closed,
                         avg((outcome = 'won')::INT) AS win_rate
                  FROM disputes WHERE status = 'closed' GROUP BY 1 ORDER BY closed DESC"""),
             hide_index=True, use_container_width=True,
             column_config={"win_rate": st.column_config.NumberColumn(format="percent")})

st.subheader("One dispute, end to end")
dispute_id = st.selectbox("Dispute", lags.sort_values("lag_days", ascending=False).dispute_id.tolist())
d = q("""SELECT t.ts AS purchased, d.filed_ts AS filed, d.responded_ts AS responded,
                d.reason_category, d.status, d.outcome, t.amount
         FROM disputes d JOIN transactions t USING (txn_id) WHERE d.dispute_id = ?""", [dispute_id]).iloc[0]
steps = [("Purchase", d.purchased), ("Dispute filed", d.filed), ("We responded", d.responded)]
steps = [(name, ts) for name, ts in steps if ts is not None and str(ts) != "NaT"]
fig = go.Figure(go.Scatter(x=[ts for _, ts in steps], y=[1] * len(steps), mode="markers+text",
                           text=[name for name, _ in steps], textposition="top center", marker=dict(size=14)))
fig.update_layout(height=170, margin=dict(l=0, r=0, t=10, b=0), yaxis_visible=False)
st.plotly_chart(fig, use_container_width=True)
st.caption(f"${d.amount:,.2f} · {d.reason_category.replace('_', ' ')} · {d.status} · outcome: {d.outcome}")
