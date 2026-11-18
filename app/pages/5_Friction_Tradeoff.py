"""Screen 6: Friction Tradeoff. Threshold slider: fraud caught ($) vs false declines and revenue lost."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from common import PATTERN_LABELS, cursor, money, q, setup_page  # noqa: E402
from src.evaluate import tradeoff  # noqa: E402

setup_page("Friction Tradeoff", "⚖️")
st.title("Friction Tradeoff")
st.markdown("Lowering the alert threshold catches more fraud but touches more honest customers. Compare a "
            "**block-only** policy with the **response ladder**, which challenges mid-risk scores (3DS / MFA / "
            "CAPTCHA) and saves blocks for the clearest cases.")

c1, c2 = st.columns([1, 2])
choice = c1.selectbox("Pattern", ["all", *PATTERN_LABELS], format_func=lambda p: "All patterns" if p == "all"
                      else PATTERN_LABELS[p])
threshold = c2.slider("Alert threshold (risk score)", 0, 100, 40, 5)


@st.cache_data(show_spinner="Simulating thresholds...")
def curve(pattern: str, version: int):
    cur = cursor()
    try:
        return tradeoff(cur, None if pattern == "all" else pattern, thresholds=range(0, 101, 5))
    finally:
        cur.close()


version = int(q("SELECT count(*) FROM ground_truth").iloc[0, 0])  # recompute after Attack Mode launches
df = curve(choice, version)
at = df[df.threshold == threshold].set_index("policy")
blk, lad = at.loc["block_only"], at.loc["ladder"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Recall at this threshold", f"{lad.recall:.1%}")
m2.metric("Fraud stopped (ladder)", money(lad.fraud_stopped_usd),
          delta=f"{lad.fraud_stopped_usd - blk.fraud_stopped_usd:+,.0f} vs block-only", delta_color="off")
m3.metric("Expected false declines", f"{lad.expected_false_declines:,.1f}",
          delta=f"{blk.expected_false_declines:,.0f} with block-only", delta_color="off")
saved = 1 - lad.expected_false_declines / blk.expected_false_declines if blk.expected_false_declines else 0
m4.metric("False declines avoided by the ladder", f"{saved:.0%}")

fig = make_subplots(rows=1, cols=2, subplot_titles=("Fraud stopped ($)", "Legit monthly revenue lost ($)"))
colors = {"block_only": "#d93025", "ladder": "#1a73e8"}
for policy, frame in df.groupby("policy"):
    name = "Block-only" if policy == "block_only" else "Response ladder"
    fig.add_trace(go.Scatter(x=frame.threshold, y=frame.fraud_stopped_usd, name=name, line_color=colors[policy],
                             legendgroup=policy), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame.threshold, y=frame.monthly_revenue_lost_usd, name=name,
                             line_color=colors[policy], legendgroup=policy, showlegend=False), row=1, col=2)
for col in (1, 2):
    fig.add_vline(x=threshold, line_dash="dot", line_color="#5f6368", row=1, col=col)
fig.update_layout(height=380, margin=dict(l=0, r=0, t=40, b=0), legend=dict(orientation="h", y=-0.2))
fig.update_xaxes(title_text="Alert threshold")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Assumptions")
st.dataframe(q("SELECT step, friction_rate, fraud_stop_rate, description FROM ladder_steps ORDER BY severity"),
             hide_index=True, use_container_width=True,
             column_config={"friction_rate": st.column_config.NumberColumn("Legit users lost", format="percent"),
                            "fraud_stop_rate": st.column_config.NumberColumn("Attacks stopped", format="%.2f")})
st.caption("Ladder policy at threshold T: scores from T to T+19 get step-up; T+20 and above get the pattern's "
           "strongest step (block for card testing and trial abuse, review for ATO and friendly fraud, because "
           "those customers are victims or still customers). Friction rates are assumptions defined in "
           "sql/response_ladder.sql.")
