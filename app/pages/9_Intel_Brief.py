"""Screen 10: Weekly Intel Brief. Weekly trends from the warehouse, written up as a short brief."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402

from common import PATTERN_LABELS, cursor, setup_page  # noqa: E402
from guide import page_intro, tip  # noqa: E402
from src.intel_brief import (build_facts, claude_brief, complete_weeks, has_api_key, template_brief,  # noqa: E402
                             weekly_metrics)

setup_page("Intel Brief", "📰")
st.title("Weekly Intel Brief")
page_intro("intel_brief")

# On Streamlit Cloud the key lives in the app's Secrets; locally, in the environment.
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:  # no secrets file configured: that's fine, the template writer works without one
    pass

cur = cursor()
weekly = weekly_metrics(cur)
weeks = complete_weeks(weekly)
week = st.selectbox("Week starting (Monday)", weeks[::-1], format_func=lambda d: d.strftime("%b %d, %Y"))

alert_cols = {f"alerts_{p}": label for p, label in PATTERN_LABELS.items()}
trend = weekly[weekly.week.isin(weeks)].melt(id_vars="week", value_vars=list(alert_cols), var_name="pattern",
                                             value_name="alerts")
trend["pattern"] = trend.pattern.map(alert_cols)
fig = px.bar(trend, x="week", y="alerts", color="pattern", height=300, labels={"week": "", "alerts": "Alerts"})
fig.add_vline(x=week, line_dash="dot", line_color="#5f6368")
fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.25))
st.plotly_chart(fig, use_container_width=True)
tip("Spikes line up with attack campaigns injected that week. Launch one in Attack Mode, and the brief for "
    "that week changes the next time you open this page.")

facts = build_facts(cur, week)
cur.close()

st.subheader("The brief")
writer = "template"
if has_api_key():
    writer = st.radio("Writer", ["template", "claude"], horizontal=True,
                      format_func={"template": "Template (instant, deterministic)",
                                   "claude": "Claude (narrative, a few cents per brief)"}.get)
else:
    st.caption("Written by the built-in template. Add an `ANTHROPIC_API_KEY` (environment variable, or the app's "
               "Secrets on Streamlit Cloud) to have Claude write it from the same numbers.")

if writer == "claude":
    key = f"brief_{week}"
    if key not in st.session_state or st.button("Rewrite"):
        with st.spinner("Claude is writing the brief from this week's numbers..."):
            try:
                st.session_state[key] = claude_brief(facts)
            except Exception as exc:  # API or network problem: show the template rather than nothing
                st.warning(f"Claude couldn't write the brief ({type(exc).__name__}); showing the template instead.")
                st.session_state[key] = template_brief(facts)
    brief = st.session_state[key]
else:
    brief = template_brief(facts)

with st.container(border=True):
    st.markdown(brief)
st.download_button("⬇️ Download brief (Markdown)", brief, file_name=f"intel_brief_{week}.md", mime="text/markdown")

with st.expander("The exact numbers the brief was written from"):
    st.json(facts, expanded=False)
