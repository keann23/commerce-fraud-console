"""Screen 3: Case Queue. Alerts sorted by risk, with reason codes and the recommended action."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import ACTION_LABELS, PATTERN_LABELS, open_case, q, reasons, setup_page  # noqa: E402

setup_page("Case Queue", "📥")
st.title("Case Queue")

alerts = q("""
    WITH latest AS (
        SELECT entity_type, entity_id, pattern, arg_max(decision, decided_ts) AS decision
        FROM case_decisions GROUP BY ALL)
    SELECT a.pattern, a.entity_type, a.entity_id, a.risk_score, a.reason_codes, a.recommended_action,
           a.action_detail, round(a.fraud_usd_if_true, 2) AS exposure_usd, a.event_ts, l.decision
    FROM alerts a LEFT JOIN latest l USING (pattern, entity_type, entity_id)
    ORDER BY a.risk_score DESC, a.fraud_usd_if_true DESC""")

f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
patterns = f1.multiselect("Pattern", list(PATTERN_LABELS), default=list(PATTERN_LABELS), format_func=PATTERN_LABELS.get)
actions = f2.multiselect("Recommended action", ["block", "review", "step_up"], default=["block", "review", "step_up"],
                         format_func=ACTION_LABELS.get)
min_score = f3.number_input("Min score", 0, 100, 60)
undecided = f4.checkbox("Undecided only")

view = alerts[alerts.pattern.isin(patterns) & alerts.recommended_action.isin(actions) & (alerts.risk_score >= min_score)]
if undecided:
    view = view[view.decision.isna()]
view = view.assign(pattern_label=view.pattern.map(PATTERN_LABELS), reasons=view.reason_codes.apply(reasons),
                   action=view.recommended_action.map(ACTION_LABELS)).reset_index(drop=True)

st.caption(f"{len(view):,} alerts · total exposure ${view.exposure_usd.sum():,.0f}. "
           "Select a row to open its case file.")
selection = st.dataframe(
    view[["risk_score", "pattern_label", "entity_type", "entity_id", "action", "reasons", "exposure_usd",
          "event_ts", "decision"]],
    hide_index=True, use_container_width=True, height=560, on_select="rerun", selection_mode="single-row",
    column_config={
        "risk_score": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d"),
        "pattern_label": "Pattern", "entity_type": "Type", "entity_id": "Entity", "action": "Action",
        "reasons": st.column_config.TextColumn("Reason codes", width="large"),
        "exposure_usd": st.column_config.NumberColumn("Exposure", format="$%.0f"),
        "event_ts": st.column_config.DatetimeColumn("When", format="MMM D, HH:mm"),
        "decision": "Analyst decision",
    })
rows = selection.selection.rows
if rows:
    row = view.iloc[rows[0]]
    st.info(f"**{row.entity_id}** · {row.pattern_label} · {row.action_detail}")
    if st.button("Open case file →", type="primary"):
        open_case(row.pattern, row.entity_type, row.entity_id)
