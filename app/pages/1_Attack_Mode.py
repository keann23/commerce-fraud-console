"""Screen 2: Attack Mode. Launch an attack, rerun detection, see what fired, how fast, what was missed."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from common import PATTERN_LABELS, cursor, q, reasons, rebuild_world, setup_page  # noqa: E402
from guide import page_intro, tip  # noqa: E402
from src.db import run_detection  # noqa: E402
from src.evaluate import campaign_report  # noqa: E402
from src.generate.attacks.ato import inject_ato  # noqa: E402
from src.generate.attacks.card_testing import CARD_PATTERNS, inject_card_testing  # noqa: E402
from src.generate.attacks.friendly_fraud import inject_friendly_fraud  # noqa: E402
from src.generate.attacks.trial_abuse import inject_trial_abuse  # noqa: E402

setup_page("Attack Mode", "🎯")
st.title("Attack Mode")
page_intro("attack_mode")

attack = st.radio("Attack", list(PATTERN_LABELS), format_func=PATTERN_LABELS.get, horizontal=True)
col1, col2, col3 = st.columns(3)
params = {}
if attack == "card_testing":
    params["attempts"] = col1.slider("Auth attempts", 100, 500, 250, 25, help="How many stolen cards the tester tries. More attempts = louder burst.")
    params["duration_minutes"] = col1.slider("Burst duration (minutes)", 5, 30, 15, help="Spreading the same attempts over longer time lowers velocity in any 10-minute window, which makes it harder to catch.")
    params["n_ips"] = col2.slider("IPs in the pool", 1, 3, 1, help="Rotating IPs splits the burst, so each IP looks smaller. Detection also scores per device.")
    params["n_devices"] = col2.slider("Devices", 1, 3, 2, help="How many machines (device fingerprints) the tester uses.")
    params["decline_rate"] = col3.slider("Decline rate", 0.70, 0.90, 0.80, 0.05, help="Share of stolen cards that are already dead. Declines are the strongest card testing signal.")
    params["card_pattern"] = col3.selectbox("Stolen card list", CARD_PATTERNS, help="same_bin: most cards from one bank range. sequential_last4: generated card numbers in sequence. random: no pattern (hardest).")
    inject = inject_card_testing
elif attack == "trial_abuse":
    params["n_accounts"] = col1.slider("Trial accounts", 10, 50, 20, help="How many fake identities one person creates.")
    params["duration_days"] = col1.slider("Spread over (days)", 10, 45, 30, help="Signups spread over time look less like a burst.")
    params["n_devices"] = col2.slider("Shared devices", 1, 3, 2, help="How many laptops/phones the abuser reuses. Shared devices link accounts in the identity graph.")
    params["n_virtual_cards"] = col2.slider("Shared virtual cards", 1, 3, 2, help="Disposable cards reused across accounts to start trials.")
    params["fresh_card_rate"] = col3.slider("Share of accounts with a fresh card", 0.0, 0.5, 0.15, 0.05, help="Evasion: accounts that use a brand-new card share no card link with the ring.")
    params["student_variant"] = col3.checkbox("Student discount variant", help="Abuse the discounted Student plan with non-.edu or plus-tagged .edu emails.")
    inject = inject_trial_abuse
elif attack == "ato":
    params["n_victims"] = col1.slider("Victim accounts", 1, 20, 8, help="Real, long-standing customers whose passwords the crew has.")
    params["impossible_travel_rate"] = col2.slider("Share with impossible travel", 0.0, 1.0, 0.5, 0.1, help="Share of victims who logged in at home minutes before the crew logged in from abroad.")
    params["monetize_rate"] = col2.slider("Share monetized", 0.0, 1.0, 0.8, 0.1, help="Share of takeovers that end in a big purchase or plan upgrade.")
    params["n_devices"] = col3.slider("Crew devices", 1, 3, 2, help="Fewer devices = the same machine shows up on many victim accounts, a credential-stuffing tell.")
    inject = inject_ato
else:
    params["n_customers"] = col1.slider("Customers filing false disputes", 5, 30, 12, help="Long-standing customers who will claim a purchase was unauthorized.")
    params["big_purchase_rate"] = col2.slider("Share disputing a big annual purchase", 0.0, 1.0, 0.5, 0.1, help="The rest dispute an ordinary monthly renewal.")
    inject = inject_friendly_fraud

if st.button(f"🚀 Launch {PATTERN_LABELS[attack].lower()}", type="primary"):
    cur = cursor()
    seed = 100_000 + int(q("SELECT count(DISTINCT campaign_id) FROM ground_truth").iloc[0, 0])
    t0 = time.perf_counter()
    campaign = inject(cur, seed=seed, **params)
    t1 = time.perf_counter()
    run_detection(cur)
    t2 = time.perf_counter()
    cur.close()
    st.session_state["last_campaign"] = {"id": campaign, "inject_s": t1 - t0, "detect_s": t2 - t1}

last = st.session_state.get("last_campaign")
campaigns = q("SELECT DISTINCT campaign_id FROM ground_truth ORDER BY campaign_id DESC")["campaign_id"].tolist()
if campaigns:
    st.divider()
    default = campaigns.index(last["id"]) if last and last["id"] in campaigns else 0
    chosen = st.selectbox("Campaign report", campaigns, index=default)
    if last and chosen == last["id"]:
        st.success(f"Injected **{chosen}** in {last['inject_s']:.1f}s · detection reran in {last['detect_s']:.1f}s")

    cur = cursor()
    report = campaign_report(cur, chosen)
    cur.close()
    attacks = report[report.label == "attack"]
    looks = report[report.label == "lookalike"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Attack entities", len(attacks))
    m2.metric("Caught", int(attacks.flagged.sum()),
              delta=f"{attacks.flagged.mean():.0%} recall" if len(attacks) else None)
    m3.metric("Lookalikes injected", len(looks))
    m4.metric("Lookalikes wrongly flagged", int(looks.flagged.sum()), delta_color="inverse",
              delta=f"{looks.flagged.mean():.0%}" if len(looks) else None)

    report = report.assign(result=report.apply(
        lambda r: ("✅ caught" if r.flagged else "❌ missed") if r.label == "attack"
        else ("⚠️ false positive" if r.flagged else "✅ correctly allowed"), axis=1),
        reasons=report.reason_codes.apply(reasons))
    tab_a, tab_l = st.tabs(["Attack entities", "Legit lookalikes"])
    for tab, frame in ((tab_a, report[report.label == "attack"]), (tab_l, report[report.label == "lookalike"])):
        tab.dataframe(frame[["result", "entity_type", "entity_id", "scored_by", "risk_score", "recommended_action",
                             "reasons"]], hide_index=True, use_container_width=True)
    tip("Recall = caught ÷ attack entities. 'Lookalikes wrongly flagged' is the cost side: honest customers "
        "this detector would have hurt. A good detector keeps the first high and the second at zero.")
    missed = attacks[~attacks.flagged]
    if len(missed):
        st.info(f"{len(missed)} attack entities slipped through. Open them in the Case File to see which signals "
                "were missing: usually that's the limitation described in docs/explainers.md for this pattern.")

with st.sidebar:
    st.divider()
    if st.button("♻️ Reset world", help="Regenerate from the fixed seed: removes all launched campaigns."):
        with st.spinner("Rebuilding (about a minute)..."):
            rebuild_world()
        st.session_state.pop("last_campaign", None)
        st.rerun()
