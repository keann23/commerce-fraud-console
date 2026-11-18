"""Learning content for every screen, kept in one place so it is easy to review and edit.

Each guide has:
  summary   one or two sentences shown at the top of the screen, always
  why       why this matters in a real fraud team
  how       step-by-step instructions
  look_for  what to notice: the lessons the screen teaches
  try       small exercises
"""
import streamlit as st

PURPOSE = """
**Why this simulator exists**

Fraud analysts rarely get to see the whole picture at once. In a real company the attack happens in
one system, detection runs in another, the chargeback arrives six weeks later in a third, and nobody
ever tells you which customers you wrongly blocked. That makes fraud hard to learn.

This simulator puts the whole loop in one place, on safe synthetic data where **the answers are known**:

1. **Simulate**: a realistic subscription business (20,000 customers, 120 days of logins, payments,
   trials, product usage and disputes), including honest customers who *look* suspicious.
2. **Attack**: inject card testing, trial abuse, account takeover or friendly fraud, at any size, whenever you like.
3. **Detect**: plain SQL rules score every IP, device, account and dispute from 0 to 100, with reason codes.
4. **Decide**: each score maps to a response ladder (allow, step-up, review, block) that weighs fraud
   loss against the cost of annoying or losing honest customers.
5. **Measure**: because every attack and every lookalike is labelled, you can see exactly what was
   caught, what was missed, and which honest customers were hurt.

Use it to learn how each fraud pattern shows up in data, why the obvious rule usually hurts good
customers, and how analysts trade off loss against friction.
"""

GUIDES = {
    "overview": {
        "summary": "The dashboard a fraud lead opens first: how much fraud was stopped, how many honest customers "
                   "were hurt, how disputes are trending, and how well each detector performs against the truth.",
        "why": "Fraud teams are judged on two numbers that pull in opposite directions: fraud losses and "
               "false declines (honest customers turned away). A good dashboard always shows both.",
        "how": [
            "Read the five numbers across the top first. Hover the ⓘ icon on each for its exact definition.",
            "**Open alerts by pattern** shows how many entities each detector flagged and which action it recommends.",
            "**Dispute ratio by charge month** shows chargebacks per approved charge, by the month of the purchase.",
            "**Detection quality** compares every detector with the hidden ground truth.",
        ],
        "look_for": [
            "**Fraud $ prevented vs missed**: the share of attack money the current actions stop.",
            "**False declines = 0 at the default settings.** That is not luck: the alert line (score 60) sits "
            "above every honest lookalike. Lower the threshold on the Friction Tradeoff screen to see it change.",
            "**The dispute ratio falls in the latest months.** That is label delay, not success: disputes "
            "arrive 2 to 8 weeks after the purchase. Never judge the latest month's fraud rate at face value.",
            "In the quality table, **FPR on lookalikes** is the honest test: those are good customers deliberately built "
            "to resemble each attack.",
        ],
        "try": [
            "Note the alert counts, launch an attack in **Attack Mode**, then come back and see what changed.",
        ],
    },
    "attack_mode": {
        "summary": "Inject a fraud attack into the live data, re-run every detector, and see in seconds what fired, "
                   "what was missed, and which honest lookalikes were caught by mistake.",
        "why": "Detection rules are only trustworthy if you have seen them catch attacks of different sizes and "
               "styles, and seen them leave similar-looking good customers alone. Red teams do this for real; "
               "here it takes one click.",
        "how": [
            "Pick an attack type. The sliders change with it; hover the ⓘ on each slider for what it means.",
            "Press **Launch**. The injector writes the attack (and its honest lookalikes) into the warehouse, then all "
            "detection SQL re-runs.",
            "Read the four numbers: attack entities, how many were caught, lookalikes injected, lookalikes wrongly flagged.",
            "Open the two tabs to see every entity, its score, the recommended action and the reason codes.",
            "Missed something? Copy its id into the **Case File** to see which signals were absent.",
            "**Reset world** (sidebar) removes everything you launched and rebuilds the original data.",
        ],
        "look_for": [
            "What each attack is scored on: card testing on **IPs and devices**, trial abuse and ATO on **accounts**, "
            "friendly fraud on **disputes**. The entity choice is a design decision: it is what you would act on.",
            "Each launch also creates **lookalikes**: a campus network starting trials together, a customer retrying "
            "a failing card, a family sharing a laptop, a traveler with a new phone, a real stolen-card dispute. "
            "A detector that flags these is costing the business good customers.",
            "**Reason codes** tell you *why* something scored high. An analyst should be able to explain every alert.",
        ],
        "try": [
            "Card testing at its hardest: 100 attempts, 30 minutes, 3 IPs, 3 devices, 70% declines. Is it still caught? "
            "Which reason codes carry it?",
            "Trial abuse with **fresh card share** at 0.5: does recall drop? Which accounts slip through, and what do "
            "they have in common?",
            "Account takeover with **impossible travel at 0**: the crew no longer gives itself away by location. "
            "Does the reset → email change → new card chain still catch it?",
            "Friendly fraud: open one of the flagged disputes in **Evidence Pack**.",
        ],
    },
    "case_queue": {
        "summary": "The analyst's to-do list: every entity a detector flagged, ranked by risk, with its reason codes, "
                   "money at stake and recommended action.",
        "why": "Real teams get far more alerts than they can review. Triage (deciding what to look at first) is "
               "a core skill: highest risk and highest exposure first, and never action an alert you can't explain.",
        "how": [
            "Use the filters to narrow by pattern, recommended action and minimum score. Tick **Undecided only** "
            "to hide cases you've already decided.",
            "Click a row to select it, then **Open case file** to investigate it.",
            "Decisions you log in the Case File show up in the **Analyst decision** column.",
        ],
        "look_for": [
            "**Risk** is the detector's 0 to 100 score. **Exposure** is the money at stake if it really is fraud: "
            "cash-out spend, fraudulent charges plus a $15 chargeback fee, a free trial month, or the disputed amount.",
            "**Action** comes from the response ladder: *Step-up* (3DS, MFA or CAPTCHA), *Review* (an analyst or the "
            "owner verifies), *Block*.",
            "ATO and friendly fraud never say *Block*: the account owner is either a victim or still a paying customer.",
        ],
        "try": [
            "Sort mentally by risk × exposure: which three cases would you work first, and why?",
            "Filter to **Step-up** only. These are the borderline cases where friction, not a block, is the right call.",
        ],
    },
    "ring_explorer": {
        "summary": "A network view of how accounts connect through shared devices, cards and email inboxes. Trial abuse "
                   "rings and card testing bursts light up here.",
        "why": "Fraudsters create many accounts that look unrelated one by one. They give themselves away by "
               "reusing the same laptop, card or inbox. Linking accounts into clusters (identity resolution) turns "
               "30 'new customers' back into the one person they really are.",
        "how": [
            "**Identity rings tab**: pick a cluster from the list (sorted by risk). Drag nodes, scroll to zoom, hover for details.",
            "Round nodes are accounts. Square = device, diamond = card, triangle = email inbox after normalization.",
            "Account colours: red = cancelled its trial, green = converted to paid, grey = never trialled.",
            "**Card testing bursts tab**: pick a flagged IP or device to see every card it tried and where the "
            "working cards were used later.",
        ],
        "look_for": [
            "**Email normalization** is why one triangle can connect many accounts: Gmail ignores dots and everything "
            "after a +, so `k.e.vin+7@gmail.com` and `kevin@gmail.com` are one inbox.",
            "**Trial inflation** (top numbers): how many 'unique' trial accounts are really the same people.",
            "Compare an abuse ring (all red, many accounts, virtual cards) with a family or a library computer "
            "(a few accounts, usually some green). Sharing is normal; never paying is the tell.",
            "In bursts, green cards were proven to work. The tester's IP is gone tomorrow, but those cards come back "
            "for a cash-out from a different IP: block the cards, not just the IP.",
        ],
        "try": [
            "Scroll the cluster list to find a low-scoring cluster with green nodes. Why is it low risk?",
            "Tick **Also show links used by only one account** to see how much noise the default view hides.",
        ],
    },
    "case_file": {
        "summary": "Everything about one account, IP, device or dispute on a single page: its scores, a timeline of logins, "
                   "account changes, payments and disputes, its product usage, its links to other accounts, and "
                   "decision buttons.",
        "why": "Scores tell you *where* to look; the timeline tells you *what happened*. Analysts confirm or reject "
               "an alert by reading the sequence of events, and they record a decision so the team (and future "
               "models) can learn from it.",
        "how": [
            "Pick a case from the list, arrive from the Case Queue or Ring Explorer, or type any id: `U…` for an account, "
            "`D…` for a device, `DP…` for a dispute, or an IP address.",
            "For an IP or device, first pick which of its accounts to inspect.",
            "Hover the timeline dots for device, IP, country and amount. Below it, the bars show daily product usage.",
            "Choose a decision (Approve, Step-up, Review, Block) and add a note. Decisions are saved and appear in the queue.",
        ],
        "look_for": [
            "**Account takeover**: a successful login from a new device or country, then within hours from that same "
            "device a password reset, an email change, a new card and a big purchase. Sometimes a login at home "
            "minutes earlier proves 'impossible travel'.",
            "**Friendly fraud**: a purchase from the usual device and home IP, heavy product usage afterwards, then an "
            "'unauthorized' dispute weeks later.",
            "**Card testing**: one IP with many short-lived accounts and dozens of tiny declined auths in minutes.",
            "**Trial abuse**: the Linked entities table shows the same device, card or inbox on many other accounts.",
            "The highlighted decision button is the ladder's recommendation; you can disagree, and that is the point.",
        ],
        "try": [
            "Open an ATO case and write down the order of events in the 48 hours after the suspicious login.",
            "Open a friendly fraud dispute and compare usage before and after the purchase.",
        ],
    },
    "friction_tradeoff": {
        "summary": "Move the alert threshold and see the trade-off in money: fraud stopped against honest customers "
                   "lost, for a block-everything policy versus the response ladder.",
        "why": "Every fraud rule makes two kinds of mistakes: missed fraud and false declines. Blocking more fraud "
               "always costs some good customers. The response ladder softens the cost by challenging borderline "
               "cases (3DS, MFA, CAPTCHA) instead of blocking them.",
        "how": [
            "Pick a pattern (or all), then drag the **Alert threshold** slider. Anything scoring at or above it is actioned.",
            "**Block-only** blocks everything at or above the threshold.",
            "**Response ladder** gives scores just above the threshold (within 20 points) a step-up, and higher "
            "scores the pattern's strongest step.",
            "The left chart is fraud stopped ($); the right is monthly revenue lost from honest customers.",
        ],
        "look_for": [
            "At the default threshold of 60 no honest customer is touched, so both policies look the same.",
            "Lower the threshold toward 40 or 30: block-only starts turning away hundreds of good customers, while the ladder "
            "loses only the few who give up on a challenge. Fraud stopped barely changes.",
            "**Expected false declines** = honest customers actioned × the share lost at that step. A blocked "
            "customer is lost for sure; a challenged one is lost ~5% of the time.",
            "The **Assumptions** table drives everything. Those rates are estimates; changing them changes the answer.",
        ],
        "try": [
            "Find the lowest threshold where block-only still has zero false declines. What is recall there?",
            "Switch to Account takeover only. Why does the ladder top out at Review rather than Block?",
        ],
    },
    "dispute_lifecycle": {
        "summary": "How chargebacks unfold over time: how long after a purchase disputes arrive, how many are known "
                   "after N days, how the dispute ratio moves week by week, and how often each kind is won.",
        "why": "A chargeback is the bank reversing a payment after a customer disputes it. They arrive weeks late, "
               "so fraud labels are always incomplete for recent data. Card networks also fine merchants whose "
               "dispute ratio gets too high (often around 1%), so teams watch it closely.",
        "how": [
            "**Lag histogram**: days from purchase to dispute, coloured by dispute reason.",
            "**Label maturity curve**: of all the disputes a group of purchases will eventually get, what share is known N days later.",
            "**Dispute ratio by purchase week**: disputes divided by approved charges.",
            "**Win rate by reason**: how often the merchant wins after responding (representment).",
            "Pick any dispute at the bottom to see its own timeline.",
        ],
        "look_for": [
            "Most disputes land 2 to 8 weeks after purchase, with a long tail. The median is about a month.",
            "Read the maturity curve at day 14 and day 30. If only part of the disputes are known after 30 days, "
            "last week's 'clean' numbers are mostly missing labels.",
            "That is why the weekly dispute ratio drops toward zero at the end: **label delay**, not improvement.",
            "Reasons differ: *canceled subscription* (customer forgot to cancel) is usually honest; *unauthorized* "
            "may be real fraud or friendly fraud.",
        ],
        "try": [
            "If you changed a rule last week, when could you fairly judge its effect on chargebacks? Use the curve.",
        ],
    },
    "evidence_pack": {
        "summary": "Builds a one-click PDF that argues a friendly fraud dispute should be reversed: the purchase came "
                   "from the customer's own device and home IP, and they kept using the product afterwards.",
        "why": "When a customer disputes a charge, the merchant can respond with evidence (\"representment\"). "
               "Card networks give extra weight to proof that the same device or IP made earlier undisputed "
               "purchases. Visa's Compelling Evidence 3.0 rules formalize this. A strong pack wins money back "
               "without blocking a customer who is still paying.",
        "how": [
            "Pick a dispute that the friendly fraud detector flagged for review (highest score first).",
            "Check the four evidence numbers and the three tabs: earlier purchases, usage after purchase, logins after purchase.",
            "Click **Download evidence pack** for the PDF.",
        ],
        "look_for": [
            "The strongest evidence is a **device and IP match with earlier undisputed purchases**. That is "
            "what separates friendly fraud from a real stolen card.",
            "Usage after the purchase shows the customer received and used what they paid for.",
            "Honest 'unauthorized' disputes (real stolen cards, account takeovers) score low and are *not* fought: "
            "fighting them would lose and annoy the real cardholder's bank.",
        ],
        "try": [
            "Read the PDF summary as if you were the issuing bank. Which point convinces you most?",
        ],
    },
    "rule_simulator": {
        "summary": "Write your own fraud rule as a SQL WHERE clause over every payment attempt and backtest it: how many "
                   "attack transactions it catches and how many honest ones it would hit.",
        "why": "Analysts propose rules all the time. Before a rule goes live it must be backtested on history, "
               "because a rule that catches fraud but also hits thousands of good payments does more harm than good.",
        "how": [
            "Start from an example, or write your own condition. It is the part after WHERE in SQL.",
            "Expand **Available columns** to see every field you can use.",
            "Press **Backtest**. You get matches, attack hits, legit hits and precision (the share of hits that were attacks).",
            "Only a condition is allowed: no semicolons and no commands that change data.",
        ],
        "look_for": [
            "**Precision** answers 'if this rule fires, how often is it right?'. Under about 50% means more good "
            "customers than fraudsters get hit.",
            "Broad rules (`result = 'declined'`) catch a lot but hurt many honest customers. Combining signals "
            "(velocity + tiny amounts) is what makes rules sharp.",
            "Column meanings: `ip_attempts_10m`, `ip_cards_10m`, `ip_declines_10m` are payment attempts, distinct "
            "cards and declines from the same IP in the previous 10 minutes. `account_age_days` is the account's "
            "age at the time of payment. `not_signup_device` means paid from a device other than the one used to sign up.",
        ],
        "try": [
            "Run the *Too broad* example, then tighten it until precision is above 90%.",
            "Write a rule for ATO purchases using `amount`, `not_signup_device` and `card_country_mismatch`. "
            "How does it compare with the ATO detector?",
        ],
    },
}

GLOSSARY = {
    "3DS (3-D Secure)": "An extra check during card payment where the bank asks the cardholder to confirm (app approval, code). Shifts fraud liability to the bank; costs some abandonment.",
    "Account takeover (ATO)": "A criminal logs into a real customer's account, usually with a password leaked from another site.",
    "BIN": "Bank Identification Number: the first 6 digits of a card, identifying the issuing bank. Stolen card lists often share a BIN.",
    "Card fingerprint": "A stable token for one physical card, so the same card can be recognised across accounts without storing its number.",
    "Card testing": "Using small, rapid charges to find out which stolen card numbers still work.",
    "Cash-out": "Spending with cards or accounts after testing or taking them over: the step where fraud turns into money.",
    "Chargeback / dispute": "The cardholder asks their bank to reverse a charge. The merchant loses the money plus a fee unless it wins.",
    "Connected components": "Groups of accounts linked directly or indirectly by shared devices, cards or inboxes; used to collapse fake identities.",
    "Credential stuffing": "Trying leaked username/password pairs from other breaches on our login page at scale.",
    "Dispute ratio": "Disputes divided by approved charges. Card networks penalise merchants whose ratio is too high.",
    "Email normalization": "Reducing an address to its real inbox: lower-case, Gmail dots removed, plus-tags removed.",
    "False decline / false positive": "An honest customer blocked or challenged by a fraud rule.",
    "Friction": "Anything that slows an honest customer down (CAPTCHA, 3DS, MFA, review). Some customers give up.",
    "Friendly fraud": "A genuine customer disputes a charge they really made, to get their money back.",
    "Ground truth": "The hidden labels saying what really was an attack. Real teams rarely have it complete; here it is exact.",
    "Impossible travel": "Two logins too far apart for the time between them (here: over 900 km/h and more than 500 km).",
    "Label delay / label maturity": "Fraud labels (chargebacks) arrive weeks late, so recent data looks cleaner than it is.",
    "Lookalike": "An honest customer who shares surface features with an attack, used here to measure false positives.",
    "MFA": "Multi-factor authentication: a second proof of identity (code, app) at login.",
    "Precision / recall": "Precision: of what we flagged, how much was fraud. Recall: of all fraud, how much we flagged.",
    "Reason code": "A short label explaining why a detector scored something high, so analysts can explain decisions.",
    "Representment": "The merchant's response to a chargeback, with evidence, asking the bank to reverse it.",
    "Response ladder": "Graduated actions (allow, step-up, review, block) chosen by risk, instead of block-or-allow.",
    "Risk score": "A 0 to 100 number from a detector; higher means more evidence of that attack.",
    "Step-up": "Asking for extra proof (3DS, MFA, CAPTCHA) instead of blocking outright.",
    "Trial abuse": "One person opening many accounts to chain free trials without ever paying.",
    "Velocity": "How many events (payment attempts, signups) happen from one source in a short window.",
    "Virtual / prepaid card": "Disposable or anonymous cards; legitimate for privacy, but convenient for abusers.",
}


def learning_mode() -> bool:
    return st.session_state.get("learning_mode", True)


def page_intro(key: str):
    """Short 'what this is' line always; the full guide in an expander, open while learning mode is on."""
    g = GUIDES[key]
    st.markdown(f"<div style='font-size:1.05rem'>{g['summary']}</div>", unsafe_allow_html=True)
    with st.expander("📘 How to use this screen, and what it teaches", expanded=learning_mode()):
        st.markdown(f"**Why it matters.** {g['why']}")
        st.markdown("**How to use it**")
        st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(g["how"], 1)))
        st.markdown("**What to look for**")
        st.markdown("\n".join(f"- {point}" for point in g["look_for"]))
        if g.get("try"):
            st.markdown("**Try this**")
            st.markdown("\n".join(f"- {t}" for t in g["try"]))


def tip(text: str):
    """A short lesson next to a chart or table, shown only in learning mode."""
    if learning_mode():
        st.info(text, icon="💡")
