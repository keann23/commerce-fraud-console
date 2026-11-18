"""Learning Guide: the simulator's purpose, the four attacks at a glance, a guided path, and a glossary."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from common import setup_page  # noqa: E402
from guide import GLOSSARY, PURPOSE  # noqa: E402

setup_page("Learning Guide", "📘")
st.title("Learning Guide")
st.markdown("Start here if you are new to fraud, or new to this console. It takes about 30 minutes to work "
            "through the path below.")

st.markdown(PURPOSE)

st.header("The four attacks at a glance")
st.dataframe(pd.DataFrame([
    {"Attack": "Card testing",
     "What the fraudster wants": "Find out which stolen cards still work",
     "How it shows up in data": "One IP/device, dozens of tiny auths in minutes, many different cards, most declined",
     "Honest lookalike": "A campus network starting $1 trial auths together; a customer retrying a failing card",
     "Right response": "Block the IP/device, rate limit, block the cards proven to work"},
    {"Attack": "Trial abuse",
     "What the fraudster wants": "Use the product free forever",
     "How it shows up in data": "Many accounts sharing a device, virtual card or inbox (after normalization); none ever pay",
     "Honest lookalike": "A family on one laptop and card; a library computer; a returning student",
     "Right response": "Collapse the identities; require a real card and phone to start a trial"},
    {"Attack": "Account takeover",
     "What the fraudster wants": "Spend from someone else's account",
     "How it shows up in data": "Login from a new device and country (maybe impossible travel), then reset, email change, new card, big purchase",
     "Honest lookalike": "A traveler with a new phone; someone who forgot their password and changed email",
     "Right response": "Force MFA, freeze changes, roll back and refund. Never ban: the owner is the victim"},
    {"Attack": "Friendly fraud",
     "What the fraudster wants": "Keep the product and get the money back",
     "How it shows up in data": "Purchase from the customer's usual device and IP, heavy usage after, then an 'unauthorized' dispute",
     "Honest lookalike": "A real stolen-card purchase that the true cardholder disputes",
     "Right response": "Fight the dispute with evidence; keep the customer"},
]), hide_index=True, use_container_width=True)

st.header("How the console works")
st.markdown("""
| Step | What happens | Where to see it |
|---|---|---|
| 1. Generate | 20,000 synthetic customers with 120 days of history, including honest customers who look suspicious | every screen |
| 2. Inject | Attack injectors add a campaign *and* matching honest lookalikes, and record the truth in a hidden table | Attack Mode |
| 3. Detect | One SQL file per attack scores entities 0 to 100 and gives reason codes. **Detection never sees the truth table.** | Case Queue, Case File |
| 4. Respond | The response ladder maps each score to allow / step-up / review / block, with a friction cost | Case Queue, Friction Tradeoff |
| 5. Measure | Only the evaluation code compares detections with the truth: recall, precision, false positives | Overview, Attack Mode |
""")
st.caption("Why hide the truth from detection? In real life you never know the answers in advance. If the rules "
           "could peek, every score here would be meaningless.")

st.header("Guided path")
st.markdown("Tick each step as you go (ticks are kept for this browser session only).")
PATH = [
    ("Overview", "Read the five headline numbers and hover each ⓘ. Why is 'false declines' as important as 'fraud prevented'?"),
    ("Attack Mode", "Launch a default card testing attack. How many attack entities were caught? Were any lookalikes flagged?"),
    ("Attack Mode", "Launch card testing at its hardest settings (100 attempts, 30 min, 3 IPs, 3 devices, 0.70 declines). Which reason codes still fire?"),
    ("Case Queue", "Find the top alert. What is its exposure, and why is that the action the ladder chose?"),
    ("Case File", "Open an account takeover case. Write down the order of events in the 48 hours after the suspicious login."),
    ("Ring Explorer", "Open the riskiest identity ring. How many accounts, how many real inboxes, how many cards?"),
    ("Ring Explorer", "Find a low-risk cluster with green (paying) accounts. What makes it different from a ring?"),
    ("Friction Tradeoff", "Drag the threshold from 60 down to 30. How many more honest customers does block-only lose than the ladder?"),
    ("Dispute Lifecycle", "Read the maturity curve at day 30. Why should you never judge last week's fraud rate at face value?"),
    ("Evidence Pack", "Download a PDF. Which piece of evidence would convince a bank most?"),
    ("Rule Simulator", "Run the 'Too broad' example, then tighten it until precision is above 90%."),
]
done = 0
for i, (screen, task) in enumerate(PATH):
    if st.checkbox(f"**{screen}:** {task}", key=f"path_{i}"):
        done += 1
st.progress(done / len(PATH), text=f"{done} of {len(PATH)} steps done")

st.header("Glossary")
search = st.text_input("Search terms", placeholder="e.g. chargeback, BIN, step-up")
terms = {k: v for k, v in GLOSSARY.items()
         if not search or search.lower() in k.lower() or search.lower() in v.lower()}
for term, meaning in terms.items():
    st.markdown(f"**{term}:** {meaning}")
if not terms:
    st.caption("No matching terms.")

st.divider()
st.caption("All data is synthetic, generated with Faker and a fixed seed. 'Adobe-style' describes the business model "
           "being simulated, not Adobe data. The design reasoning for every detector is in docs/explainers.md.")
