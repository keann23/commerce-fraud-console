"""Shared helpers for every screen: one cached DuckDB connection, query helper, labels, colors."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import config as C  # noqa: E402
from src.db import connect, run_detection  # noqa: E402
from src.generate.run import build_database  # noqa: E402

PATTERN_LABELS = {
    "card_testing": "Card testing",
    "trial_abuse": "Trial abuse",
    "ato": "Account takeover",
    "friendly_fraud": "Friendly fraud",
}
ACTION_COLORS = {"allow": "#8a8f98", "step_up": "#d9a404", "review": "#e8710a", "block": "#d93025"}
ACTION_LABELS = {"allow": "Allow", "step_up": "Step-up", "review": "Review", "block": "Block"}


@st.cache_resource(show_spinner=False)
def _connection():
    if not C.DB_PATH.exists():
        with st.spinner("Generating the synthetic world and running detection (about a minute, first run only)..."):
            con = build_database()
            run_detection(con)
            return con
    con = connect()
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if "scored_entities" not in tables:
        with st.spinner("Running detection..."):
            run_detection(con)
    return con


def cursor():
    """A per-call cursor: Streamlit serves sessions on threads, and DuckDB cursors are per-thread safe."""
    return _connection().cursor()


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    cur = cursor()
    try:
        return cur.execute(sql, params or []).df()
    finally:
        cur.close()


def rebuild_world():
    """Drop every injected campaign and analyst decision: regenerate from the fixed seed."""
    _connection().close()
    st.cache_resource.clear()
    con = build_database()
    run_detection(con)
    con.close()


def setup_page(title: str, icon: str = "🛡️"):
    st.set_page_config(page_title=f"{title} · Fraud Console", page_icon=icon, layout="wide")
    _connection()
    # Widget values reset when you change page, so the setting lives in its own session key.
    st.session_state.setdefault("learning_mode", True)
    st.session_state["learning_mode"] = st.sidebar.toggle(
        "📘 Learning mode", value=st.session_state["learning_mode"],
        help="Opens each screen's guide and shows 💡 lessons next to charts. Turn off for a clean demo view.")
    st.sidebar.caption("All data is **synthetic** (Faker + fixed seed). No real people, cards or accounts. "
                       "New here? Start with the **Learning Guide** page.")


def money(x: float) -> str:
    return f"${x:,.0f}"


def reasons(codes) -> str:
    if codes is None or isinstance(codes, (float, str)) or not hasattr(codes, "__iter__"):
        return ""  # unscored entity (NULL / NaN)
    return ", ".join(c.replace("_", " ").lower() for c in codes)


def open_case(pattern: str, entity_type: str, entity_id: str):
    st.session_state["case"] = {"pattern": pattern, "entity_type": entity_type, "entity_id": entity_id}
    st.switch_page("pages/4_Case_File.py")
