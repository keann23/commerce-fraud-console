"""Screen 9: Rule Simulator. Write a SQL WHERE clause over payment attempts and backtest it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import cursor, q, setup_page  # noqa: E402
from src.evaluate import rule_backtest  # noqa: E402

setup_page("Rule Simulator", "🧪")
st.title("Rule Simulator")
st.markdown("Write a WHERE clause over every payment attempt (`txn_features`) and see how many attack "
            "transactions it catches versus how many honest ones it would hit.")

EXAMPLES = {
    "Card testing velocity": "ip_declines_10m >= 5 AND amount < 3",
    "Micro auths on young accounts": "txn_type = 'auth' AND amount < 2 AND account_age_days < 1",
    "Virtual card, disposable email": "is_virtual_card AND disposable_email",
    "Big purchase on a card from another country": "amount >= 100 AND card_country_mismatch",
    "Too broad: any decline": "result = 'declined'",
}
example = st.selectbox("Start from an example", list(EXAMPLES))
clause = st.text_area("WHERE", EXAMPLES[example], height=90)
with st.expander("Available columns"):
    st.dataframe(q("DESCRIBE txn_features")[["column_name", "column_type"]], hide_index=True)

if st.button("Backtest", type="primary"):
    cur = cursor()
    try:
        result = rule_backtest(cur, clause)
    except Exception as exc:  # show SQL errors to the analyst instead of crashing the page
        st.error(f"Rule failed: {exc}")
        st.stop()
    finally:
        cur.close()
    hits = result["attack_hits"] + result["legit_hits"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Attempts matched", f"{hits:,}", help=f"of {result['total_attempts']:,} payment attempts")
    c2.metric("Attack attempts caught", f"{result['attack_hits']:,}")
    c3.metric("Legit attempts hit", f"{result['legit_hits']:,}")
    c4.metric("Precision", f"{result['attack_hits'] / hits:.1%}" if hits else "n/a")
    if result["by_attack_type"]:
        st.write("Attack hits by type:", result["by_attack_type"])
    st.dataframe(result["matches"].head(500), hide_index=True, use_container_width=True)
    st.caption("Labels come from ground truth via src/evaluate.py; detection SQL never sees them.")
