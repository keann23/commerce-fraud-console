"""Screen 4: Ring Explorer. Accounts linked by device, card and normalized email light up as rings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from pyvis.network import Network  # noqa: E402

from common import ACTION_COLORS, ACTION_LABELS, open_case, q, reasons, setup_page  # noqa: E402
from guide import page_intro, tip  # noqa: E402

setup_page("Ring Explorer", "🕸️")
st.title("Ring Explorer")
page_intro("ring_explorer")

LINK_STYLE = {"device": ("square", "#4285f4"), "card": ("diamond", "#9334e6"), "email": ("triangle", "#12a4af")}


def render(net: Network, height: int = 620):
    net.set_options('{"physics": {"barnesHut": {"gravitationalConstant": -4000, "springLength": 90}}, '
                    '"interaction": {"hover": true}}')
    components.html(net.generate_html(), height=height + 20, scrolling=False)


tab_rings, tab_bursts = st.tabs(["Identity rings (trial abuse)", "Card testing bursts"])

with tab_rings:
    summary = q("""SELECT sum(n_trials) AS trial_accounts, count(*) AS identities,
                          count(*) FILTER (WHERE recommended_action <> 'allow') AS rings
                   FROM trial_identity_clusters""").iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Trial accounts", f"{int(summary.trial_accounts):,}")
    c2.metric("Real identities after linking", f"{int(summary.identities):,}",
              delta=f"-{1 - summary.identities / summary.trial_accounts:.1%} trial inflation", delta_color="off")
    c3.metric("Rings flagged", int(summary.rings))

    tip("Trial inflation = 1 − real identities ÷ trial accounts. It is how much your 'new trial' metric "
        "overstates real people, before even deciding who is abusive.")
    clusters = q("""SELECT cluster_id, n_accounts, n_trials, n_converted, risk_score, recommended_action, reason_codes
                    FROM trial_identity_clusters WHERE n_accounts >= 2
                    ORDER BY risk_score DESC, n_accounts DESC LIMIT 200""")
    labels = {r.cluster_id: f"{r.cluster_id} · {r.n_accounts} accounts · {r.n_converted}/{r.n_trials} converted · "
                            f"score {r.risk_score} ({ACTION_LABELS[r.recommended_action]})"
              for r in clusters.itertuples()}
    cluster_id = st.selectbox("Cluster", list(labels), format_func=labels.get)
    show_unshared = st.checkbox("Also show links used by only one account", value=False)
    row = clusters.set_index("cluster_id").loc[cluster_id]
    st.caption(f"Reason codes: {reasons(row.reason_codes) or 'none'}")

    members = q("""SELECT c.user_id, u.email, s.plan, s.is_trial, s.converted, s.status
                   FROM identity_clusters c JOIN users u USING (user_id) LEFT JOIN subscriptions s USING (user_id)
                   WHERE c.cluster_id = ?""", [cluster_id])
    links = q("""SELECT l.user_id, l.link_type, l.link_value,
                        count(*) OVER (PARTITION BY l.link_type, l.link_value) AS shared_by
                 FROM identity_links l JOIN identity_clusters c USING (user_id) WHERE c.cluster_id = ?""", [cluster_id])
    if not show_unshared:
        links = links[links.shared_by >= 2]

    net = Network(height="620px", width="100%", cdn_resources="remote", bgcolor="#ffffff", font_color="#202124")
    for m in members.itertuples():
        color = "#188038" if m.converted else ("#d93025" if m.is_trial else "#8a8f98")
        net.add_node(m.user_id, label=m.email, title=f"{m.user_id}\n{m.plan} · {m.status}", color=color, size=14)
    for value, group in links.groupby(["link_type", "link_value"]):
        shape, color = LINK_STYLE[value[0]]
        node_id = f"{value[0]}:{value[1]}"
        net.add_node(node_id, label=value[0], title=f"{value[0]} {value[1]}\nshared by {len(group)} accounts",
                     shape=shape, color=color, size=10)
        for user_id in group.user_id:
            net.add_edge(user_id, node_id, color="#c0c4c9")
    render(net)
    st.caption("Accounts: red = trial cancelled, green = converted to paid, grey = no trial.  "
               "Links: blue square = device, purple diamond = card, teal triangle = normalized email.")
    pick = st.selectbox("Open an account in the Case File", members.user_id.tolist())
    if st.button("Open case file →", key="ring_case"):
        open_case("trial_abuse", "user", pick)

with tab_bursts:
    bursts = q("""SELECT entity_type, entity_id, risk_score, recommended_action, attempts_10m, distinct_cards_10m,
                         decline_rate_10m, window_end FROM detect_card_testing
                  WHERE recommended_action <> 'allow' ORDER BY risk_score DESC, attempts_10m DESC""")
    if bursts.empty:
        st.info("No card testing alerts. Launch one in Attack Mode.")
    else:
        labels = {f"{r.entity_type}:{r.entity_id}": f"{r.entity_type} {r.entity_id} · {r.attempts_10m} attempts / "
                  f"{r.distinct_cards_10m} cards in 10 min · {r.decline_rate_10m:.0%} declined · score {r.risk_score}"
                  for r in bursts.itertuples()}
        key = st.selectbox("Flagged IP / device", list(labels), format_func=labels.get)
        etype, eid = key.split(":", 1)
        burst = bursts[(bursts.entity_type == etype) & (bursts.entity_id == eid)].iloc[0]
        column = "ip" if etype == "ip" else "device_id"
        cards = q(f"""
            SELECT a.card_fingerprint, a.bin, a.last4, bool_or(a.result = 'approved') AS approved,
                   any_value(v.later_charges) AS later_charges, any_value(v.later_charge_amount) AS later_usd
            FROM payment_attempts a
            LEFT JOIN card_testing_validated_cards v USING (card_fingerprint)
            WHERE a.{column} = ? AND a.ts BETWEEN ? - INTERVAL 1 HOUR AND ? + INTERVAL 1 HOUR AND a.amount <= 5
            GROUP BY ALL LIMIT 400""", [eid, burst.window_end, burst.window_end])
        cashouts = q("""
            SELECT DISTINCT p.card_fingerprint, t.user_id, t.ip, t.amount
            FROM transactions t JOIN payment_methods p USING (pm_id)
            WHERE p.card_fingerprint IN (SELECT unnest(?)) AND t.txn_type = 'charge' AND t.result = 'approved'
              AND t.amount > 5""", [cards[cards.approved].card_fingerprint.tolist()])
        c1, c2, c3 = st.columns(3)
        c1.metric("Cards tried", len(cards))
        c2.metric("Cards proven live", int(cards.approved.sum()))
        c3.metric("Cashed out later", f"${cashouts.amount.sum():,.0f}" if len(cashouts) else "$0")

        net = Network(height="620px", width="100%", cdn_resources="remote", bgcolor="#ffffff", font_color="#202124")
        net.add_node(key, label=f"{etype} {eid}", color=ACTION_COLORS[burst.recommended_action], size=30, shape="star")
        for c in cards.itertuples():
            net.add_node(c.card_fingerprint, label=f"{c.bin}…{c.last4}" if c.approved else " ",
                         title=f"BIN {c.bin} · last4 {c.last4}", size=9 if c.approved else 5,
                         color="#188038" if c.approved else "#dadce0")
            net.add_edge(key, c.card_fingerprint, color="#e8eaed")
        for o in cashouts.itertuples():
            node = f"cashout:{o.user_id}:{o.ip}"
            net.add_node(node, label=f"cash-out from {o.ip}", color="#d93025", shape="dot", size=12)
            net.add_edge(o.card_fingerprint, node, color="#d93025")
        render(net)
        st.caption("⭐ tester IP/device · 🟩 card that passed (now known live) · ⬜ declined card · "
                   "🟥 later cash-out from a different IP. Block the green cards, not just the IP.")
