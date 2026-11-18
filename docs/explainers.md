# Interview explainers

Plain-English notes for every pattern and design choice. One section per feature, added as it is built.

---

## 1. The synthetic world and its legit noise

**What it is.** A simulated Adobe-style subscription business: 20,000 customers over 120 days (Jul 18 to Nov 15, 2026), on Single App, Photography, All Apps and Student plans with regional price tiers. It is generated from one fixed seed, so every run, test and demo sees the same customers.

**How it shows up in the data.** Ten tables (users, devices, logins, account_events, payment_methods, subscriptions, transactions, usage_events, disputes, ground_truth) in one DuckDB file. On top of normal behaviour, the generator plants the honest customers that look suspicious:

| Legit noise | Why it matters later | Approx. volume (seed 42) |
|---|---|---|
| Households sharing a device, home IP and sometimes a card | Looks like a trial-abuse or card-testing ring in the graph | 181 shared devices, 87 shared cards |
| Travelers logging in abroad on their own device, at plane speed | Looks like account takeover ("new country") | ~1,060 users |
| Plus-addressed emails (students, inbox filters) | Looks like trial-abuse email tricks | ~1,140 users |
| Legit virtual/prepaid cards (4%) | Virtual cards are a trial-abuse signal | ~720 cards |
| Password reset then email change from the owner's device | First half of the ATO sequence | ~100 users |
| Normal declines with retries (~6% of charges) | Card testing is defined by declines | ~3,400 declines |
| Forgotten-renewal disputes (canceled_subscription) | Disputes that are not fraud | ~180 |

**Why it is built this way.** A detector tested only against attacks always looks perfect. Measuring false positives needs honest customers who share the attacker's surface features. Each one differs from the attack in at least one deeper signal (a traveler keeps their device and moves at plane speed; a household has 2 to 4 accounts, not 30, and they convert to paid). Those differences are exactly what the detection SQL will lean on.

Other choices worth defending:
- **All money in USD** with a per-country multiplier, so SQL can sum fraud dollars without FX tables.
- **Email normalization and haversine distance are SQL macros** (`sql/macros.sql`), not Python, so detection logic stays in the warehouse and is unit-tested directly.
- **Dispute lag is lognormal** (median about 30 days, long tail to 120). Disputes that would be filed after the window ends are dropped, which reproduces the label-delay problem: recent weeks look cleaner than they are.
- **ground_truth exists but stays empty** in the baseline. Only attack injectors write it, and only evaluation reads it.

**One limitation.** Login locations are exact (home city plus a few km). Real IP geolocation is noisy: mobile carriers and VPNs can place a user hundreds of km away, which creates false "impossible travel". A real team would weight impossible travel by IP type (mobile, hosting, VPN) and geolocation confidence instead of trusting raw coordinates.

**Likely interview question.** *"Your data is synthetic, so how do you know your false positive rate means anything?"*
Short answer: the FPR is only as honest as the noise, so I modeled the specific legitimate behaviours that collide with each attack (shared family devices, travel, plus-addressing, virtual cards, legitimate declines and disputes) and documented their volumes. Phase 2 checks the same detection ideas against the real IEEE-CIS dataset.

---

## 2. Card testing

**What the attack is.** A fraudster buys a list of stolen card numbers and doesn't know which still work, so they run hundreds of tiny $0.50 to $2 authorizations through our checkout in a few minutes to find the live ones. The few that pass get used days later for real purchases, often from a different IP, and every declined test still costs us network fees and hurts our standing with card networks.

**How it shows up in the data.** For every IP and every device, the SQL (`sql/detect/card_testing.sql`) finds its worst rolling 10-minute window and measures:

| Signal | Attack | Honest lookalike |
|---|---|---|
| Attempts in 10 min | 10 to 100+ | Campus workshop: ~10; frustrated customer: 4 to 7 |
| Distinct cards | Nearly one per attempt | Campus: one per student; frustrated customer: 1 |
| Decline rate | 70 to 90% | Campus: ~3%; frustrated customer: ~90% |
| Median amount | $0.50 to $2 | Campus: $1 trial auth; frustrated customer: full plan price |
| Shared BIN / sequential last4 | Common (stolen lists come in ranges) | Random |

Score = velocity 20 + card diversity 20 + declines 40 + micro amounts 10 + card pattern 10. Declines get the most weight because they are the one thing the campus lookalike can't fake: those students' cards are real. And the decline score only counts once there are 5+ attempts, because one declined card proves nothing.

Results on seed 42 (12 campaigns, 42 attack IPs/devices, 402 lookalikes): recall 1.00, precision 1.00, false positive rate 0 on legit and on lookalikes. The margin matters more than the headline: the weakest attack entity scored 90, while the strongest legit entity (a customer retrying their own card 7 times) scored 53, against an alert line of 60. A test also injects the hardest campaign the PRD allows (100 attempts over 30 minutes split across 3 IPs and 3 devices, only 70% declined, for each card pattern) and requires every entity to be caught.

A second table, `card_testing_validated_cards`, lists the cards a flagged burst proved were live and whether they were later charged. On seed 42 that is 871 validated cards, 434 of them cashed out for $52.7k.

**Why this response.** 80+ → **block** the IP/device and rate-limit payment attempts. 60 to 79 → **step up** with CAPTCHA at checkout. Not manual review: a burst is over in minutes, so a human queue arrives too late. Friction is low because the block hits an IP/device that has no honest customers on it. The risk is a shared IP (campus, office NAT), which is why the campus workshop is a lookalike and why a mid score gets a CAPTCHA, not a block. The real follow-up is the validated-cards list: block those card fingerprints before the cash-out.

**One limitation.** The window is 10 minutes per IP or device. A patient tester who spreads attempts over hours, rotates residential proxies and spoofs a fresh device fingerprint per attempt will slip under it. A real team adds slower windows (1h, 24h), groups by BIN and merchant account as well as IP and device, and watches global decline rate and auth volume as a backstop that doesn't depend on any one entity.

**Likely interview question.** *"Why not just block any IP with lots of declines?"*
Short answer: declines alone also catch a real customer whose card keeps failing; our frustrated-customer lookalike hits a 90% decline rate. What separates testing is the combination: many different cards, micro amounts and speed, together with the declines. That's why the score is additive and the decline points only count once there are enough attempts to mean something.

---

## 3. Trial abuse

**What the attack is.** One person opens many "new" accounts to chain free 7-day trials and never pay, cancelling each one just before the first charge. It inflates trial and signup metrics, burns compute and support cost, and, in the student variant, steals a discount meant for verified students.

**How it shows up in the data.** On their own, the accounts look unrelated. The trick is to link them first (`sql/features/20_identity_links.sql`):

- **Email normalization** collapses `k.e.vin+7@gmail.com` and `kevin@gmail.com` into one inbox, and flags throwaway domains like mailinator.
- **An identity graph** connects accounts that share a device, a card fingerprint or a normalized inbox. Connected components (a recursive SQL query) turn chains like A-device-B-card-C into one cluster.
- **A cap on shared values:** anything shared by more than 50 accounts is treated as infrastructure, not identity, so a single public terminal can't merge thousands of strangers.

Each cluster with a trial is then scored (`sql/detect/trial_abuse.sql`):

| Signal | Points | Abuse ring | Honest lookalike |
|---|---|---|---|
| Trials per cluster | 25 | 10 to 50 | Family 2 to 4, library kiosk 6 to 10 |
| No conversions (once 3+ trials have ended) | 30 | 0% convert | Families and kiosks: about half convert |
| Email aliases / disposable inboxes | 20 | Dots, plus tags, mailinator | Returning student: 1 alias; work+personal: 1 alias |
| Virtual card, or one card on 5+ accounts | 15 | Shared virtual cards | Family card on 2 to 4 accounts |
| Cancel before billing | 10 | Always | Sometimes |

Results on seed 42 (10 rings, 268 abuse accounts, 155 lookalikes): recall 0.993, precision 1.00, false positive rate 0 on all legit and on lookalikes. The highest-scoring lookalike scored 43, against an alert line of 60. Collapsing identities turns **3,983 trial accounts into 3,588 real people: 9.9% trial inflation**, and the 266 flagged abuse accounts collapse into just 10 people. The 2 misses were accounts that used a fresh device, a fresh card and a throwaway inbox all at once: nothing links them, so a graph can't see them.

**Why this response.** 80+ → **block** new trials on the cluster's devices, cards and inboxes. 60 to 79 → **step up**: require a non-virtual card and phone verification to start a trial. Never ban the person from paying: a trial abuser is still a potential customer, and the cheapest fix is simply to make the next trial cost something. Friction is low for honest users because a real card and a phone number are things they already have.

**One limitation.** Linking only works through shared artifacts. An abuser who rotates devices (or spoofs fingerprints), cards and inboxes on every account is invisible to the graph, which is exactly the 2 misses above. A real team adds softer links (same IP /24 within a day, same name and billing ZIP, behavioural similarity such as the same first project file or the same app sequence) and weights edges instead of treating every link as equal.

**Likely interview question.** *"A family shares a laptop and a credit card. Why don't you flag them?"*
Short answer: sharing is normal; what separates abuse is never paying. A family cluster has 2 to 4 trials and usually someone converts, so the no-conversion points (the biggest component) stay low, and the card points only fire at 5+ accounts on one card or for virtual cards. The family is in the test data on purpose, and they score at most 43.

---

## 4. Account takeover (ATO)

**What the attack is.** A crew with passwords leaked from other sites tries them on our login page ("credential stuffing"), gets into real, long-standing accounts, locks the owner out and spends on the stored or a newly added card. The customer is the victim here, so the response has to protect them, not punish them.

**How it shows up in the data.** `sql/detect/ato.sql` first finds **anchor logins**: successful logins that are unusual for that account (a device with no earlier successful login, a country never logged in from, or one that follows an impossible-travel hop). It then looks at the 48 hours after the anchor, **from the same device**:

| Signal | Points | Why it matters |
|---|---|---|
| New device | 10 | Attacker isn't on the owner's hardware |
| New country | 15 | Crews operate from elsewhere |
| Impossible travel (> 900 km/h, > 500 km) | 20 | Owner at home in Paris, "owner" in Singapore an hour later |
| Password reset | 10 | Locks the owner out |
| Email change after the reset | 15 | Cuts off recovery and alerts: the clearest tell |
| New payment method | 10 | The crew's own or a stolen card |
| High-value purchase or plan upgrade | 10 | Monetization |
| Device used on 3+ accounts | 10 | Stuffing crews reuse machines |

Two design choices worth defending:
- **"New" means no earlier *successful* login.** Crews guess a few passwords from the same device first. If failed attempts counted as history, the successful login would look familiar.
- **14-day warm-up.** The dataset's login history starts at day 0, so for the first two weeks every device looks new. Detection ignores anchors in that period; a real system has years of history.

Results on seed 42 (8 campaigns, 94 victims, 72 lookalikes): recall 1.00, precision 1.00, false positive rate 0. Legit accounts never scored above 25 (new device + new country: a traveler with a new phone); the weakest victim scored 70. The dangerous case is a crew logging in from a country the victim has already visited: then the new-country and impossible-travel points never fire, and the account-change chain alone scores about 55, just under the line.

**Why this response.** 60 to 84 → **step up**: force MFA re-authentication and freeze email and payment changes for 72 hours. 85+ → **review**: kill sessions, verify the owner through the *original* email, roll back the email and card changes, refund the charge. Never **block**: banning the account punishes the victim (a test enforces this). Friction cost: a legit traveler with a new phone at most gets an MFA prompt, which they can pass.

**One limitation.** The anchor relies on device and country being new. A crew using residential proxies in the victim's own city, with a spoofed copy of the victim's device fingerprint, only shows up through the account changes, which caps the score around 55 (the dangerous case above). Real teams add behavioural biometrics (typing, navigation speed), check leaked-credential databases at login, and give a "reset then email change" chain weight on its own regardless of device.

**Likely interview question.** *"How is impossible travel computed, and how does it produce false positives?"*
Short answer: haversine distance between consecutive logins divided by the time between them; over 900 km/h (faster than a plane) is impossible. False positives come from IP geolocation error (mobile carriers, VPNs, corporate egress in another city), so I also require 500+ km, and in production I'd discount hops involving VPN or hosting IPs.

---

## 5. Friendly fraud and the chargeback lifecycle

**What the attack is.** A real, long-standing customer buys something (often a big annual plan), keeps using it, then tells their bank the charge was "unauthorized" to get their money back. The account and the card are genuine; the claim is not. It's the most common kind of chargeback for subscription businesses, and the hardest to see, because nothing about the account is fraudulent.

**How it shows up in the data.** `sql/detect/friendly_fraud.sql` scores every dispute filed as `unauthorized` by asking whether the purchase looked like the customer themselves:

| Signal | Points | Friendly fraud | Honest "unauthorized" dispute |
|---|---|---|---|
| Same device as earlier approved purchases | 25 | Yes, their own laptop | Stolen card: new device; ATO: crew's device |
| Same IP as earlier approved purchases | 15 | Home network | Elsewhere |
| Tenure at purchase (180+ days) | 10 | Years | Fresh fraud account |
| 3+ earlier approved charges, no earlier disputes | 10 | Yes | Sometimes (see below) |
| Usage after the purchase (300+ minutes) | 25 | Heavy | None, or the ATO owner's normal usage |
| Logins from the purchase device afterwards | 15 | Yes | No |

Results on seed 42 (61 friendly fraud disputes, 219 honest unauthorized disputes): recall 1.00, false positive rate 0. Friendly fraud scored at least 90, honest disputes at most 50. The 50s are instructive: card testing fraud accounts that made several cash-out charges on their own device look "consistent" with their own history. They fall short only because the account is days old and nobody uses the product. **Consistency means nothing without tenure and usage.**

**Chargeback lifecycle (`src/generate/disputes.py`).** Every dispute, legit or fraud, uses one lag model: lognormal, median about 30 days, mostly 2 to 8 weeks, tail to 120. Disputes that would be filed after the data ends are not visible yet, so the last month looks cleaner than it is (a test checks this). Practical consequence: never judge a rule change on last week's chargeback rate. Wait for labels to mature, or use a maturity curve to project the final rate.

**Why this response.** 60+ → **review**, which here means *represent* the dispute (fight it with evidence: device and IP match, usage after purchase, purchase history) and **never block the customer**. They're still a paying customer, and blocking them turns a $60 dispute into lost lifetime value. Below 60 → accept the chargeback; it looks like genuine third-party fraud, and fighting it would lose anyway while annoying the real cardholder's bank.

**One limitation.** Usage after purchase is account-level. In a real ATO, the owner keeps using their account too, so usage alone can't separate the two; the device and IP of the *purchase* do. A real team would tie usage sessions to devices, and pull in issuer-side data such as Visa Compelling Evidence 3.0 (two prior undisputed transactions with matching device or IP), which formalizes this exact rule.

**Likely interview question.** *"Why not just block customers who file friendly fraud disputes?"*
Short answer: because winning the dispute and keeping the customer are both worth more than banning them. The right move is to represent with evidence, and only escalate (require a non-disputable payment method, or end the relationship) for repeat offenders.

---

## 6. Response ladder and friction tradeoff

**What it is.** One policy layer (`sql/response_ladder.sql`) that every detection feeds. Each score maps to allow → step-up → review → block, and each step carries an assumed **friction rate** (the share of honest customers lost at that step) and a **fraud stop rate** (how often it actually stops an attack):

| Step | Legit customers lost | Attacks stopped | Example |
|---|---|---|---|
| Allow | 0% | 0% | — |
| Step-up | 5% | 90% | 3DS, MFA, CAPTCHA |
| Review | 10% | 100% | Analyst queue, owner verification, representment |
| Block | 100% | 100% | Deny the IP, device, cluster |

**How it shows up in the data.** `scored_entities` puts two dollar figures on every scored entity *without* looking at labels: `fraud_usd_if_true` (cash-out, fraudulent spend plus fees, a free trial month, the disputed amount) and `monthly_revenue_usd` (what that customer pays us). The Friction Tradeoff screen joins these to ground truth (through `src/evaluate.py` only) and sweeps the alert threshold for two policies:
- **Block-only:** anything at or above the threshold is blocked.
- **Ladder:** the 20 points above the threshold get step-up; higher scores get the pattern's strongest step.

On seed 42, at a threshold of 40, both policies stop about $103.3k of fraud. **Block-only causes 288 false declines (~$59.8k of monthly revenue); the ladder causes about 14 (~$3.0k): 95% fewer, at the same fraud capture.** At the default threshold of 60 there are no legit hits at all, so the ladder only matters once you push for more recall, which is exactly when you need it.

**Why this response.** Card testing and trial abuse top out at **block**: the entity has no honest owner to protect. ATO and friendly fraud top out at **review**: the account owner is either a victim or still a customer.

**One limitation.** The friction and stop rates are assumptions, not measurements. A real team would A/B test each challenge (3DS abandonment varies a lot by issuer and region), and price analyst time into the review step.

**Likely interview question.** *"How would you pick the threshold?"*
Short answer: minimize expected cost, which is missed fraud dollars plus friction cost on legit customers, using matured labels. The tradeoff curve shows it directly. Then re-check monthly, because attackers adapt and the label delay means the last few weeks always look better than they are.

---

## 7. Phase 2: dbt port

**What it is.** The whole detection pipeline as a dbt-duckdb project: 14 models (features → detections → response ladder) with dbt's lineage graph and 26 tests (no nulls in required columns, valid ladder steps, scores 0 to 100, one score per entity, ATO victims and friendly-fraud customers never blocked).

**How it's built.** The dbt models are *generated* from `sql/` by `dbt/sync_from_sql.py`: each `CREATE OR REPLACE TABLE x AS ...` becomes `models/<layer>/x.sql`, with table names swapped for `{{ ref() }}` and `{{ source() }}`. `sql/` stays the single source of truth; a test fails if someone edits `sql/` without regenerating. dbt builds into its own `dbt` schema, and `dbt/check_parity.py` compares all 14 tables with the plain-SQL output, row for row in both directions.

**What it found.** The parity check caught two real nondeterminism bugs in the original SQL: `any_value()` choosing which IP/device a card was "tested from" (DuckDB may return any matching row), and money sums whose last bits depended on parallel summation order. Both broke the project's "same seed, same results" rule silently; both are fixed.

**One limitation.** Generating dbt from plain SQL means dbt features that need Jinja in the model body (incremental models, macros per model) aren't used. If the team moved to dbt for real, dbt would become the source of truth and `sql/` would be retired.

**Likely interview question.** *"Why generate dbt instead of just porting it?"*
Short answer: two hand-maintained copies of detection logic will drift, and a drifted rule is a silent production bug. Generating one from the other, with a test that fails on drift and a parity check on the outputs, gives dbt's lineage and tests without a second copy to maintain.

---

## 8. Phase 2: Splunk SPL versions

**What it is.** The four detections rewritten in SPL, over the warehouse exported as JSON event logs (`fraud:payments`, `fraud:logins`, `fraud:account_events`, and so on).

**How it maps.** Rolling SQL windows become `streamstats time_window=10m`; `lag()` becomes `streamstats current=f last()`; "no earlier successful login from this device" becomes a running count per user and device; the ATO 48-hour chain carries the latest anchor forward per account with `streamstats last()`.

**What doesn't translate.** SPL has no recursion, so trial abuse's connected components become a one-hop grouping (accounts sharing one device, card or inbox). Rings chained only through different links can split. `splunk/README.md` has the full SQL → SPL table.

**One limitation.** The SPL hasn't been run in a live Splunk from this repo; the export is tested, the searches are reviewed against the SQL they mirror.

**Likely interview question.** *"When would you use SPL instead of SQL?"*
Short answer: SPL for near-real-time alerting on raw logs, where security and fraud operations already work; warehouse SQL for batch scoring, backtests and evaluation over months of history. Same logic, different strengths: SQL has recursion and set operations, SPL has streaming windows over events.

---

## 9. Phase 2: weekly intel brief

**What it is.** A weekly report: alerts by pattern, flagged exposure, approved revenue, decline rates, micro-auth volume, trial starts and disputes, each compared with last week and the 4-week average, plus the top alerts by exposure.

**How it works.** The numbers are computed in SQL (`src/intel_brief.py`). The write-up comes from a deterministic template by default, or from Claude when an API key is configured. Claude only receives aggregate numbers (never customer rows), is told to use only figures present in the facts, and server-side fallbacks are on; if it declines, the template is used.

**Why this design.** An LLM is good at turning a table of deltas into a readable narrative, but the numbers must be traceable. Keeping computation in SQL and showing "the exact numbers the brief was written from" next to the text makes every claim checkable.

**One limitation.** "Use only these numbers" is an instruction, not a guarantee. A production version would check every number in the generated text against the facts automatically before sending.

**Likely interview question.** *"How do you stop the LLM from making things up in a report?"*
Short answer: give it only computed facts, forbid figures outside them, show the facts beside the output, and in production add an automated check that every number in the text appears in, or is derivable from, the facts.

---

## 10. Phase 2: IEEE-CIS validation

**What it is.** A pipeline that tests whether this project's signal ideas carry information on real labelled fraud: the Kaggle IEEE-CIS dataset (e-commerce transactions with an `isFraud` label).

**How it maps.** There's no customer id, login or dispute data, so each idea gets its closest proxy: a reconstructed customer id (card1 + addr1 + the day the card was first seen), card velocity in the previous hour, micro amounts, anonymous email domains, a new device for a known customer, amount spikes, cards first seen today, and buyer/recipient email mismatch. For each signal: lift over the base fraud rate, and what share of fraud it covers. For a fixed-weight combined score: AUC, plus precision and recall at a 1/5/10% alert budget.

**Results (590,540 real transactions, 3.5% fraud; full report in `docs/ieee_validation.md`).**
- **Transferred:** a new device on a known customer (the ATO idea) has 2.18x lift; micro amounts 1.76x, though rare.
- **Didn't transfer at first:** card velocity (1.13x), "anonymous" email (0.76x) and buyer/recipient email mismatch (0.82x). Diagnostics showed these were *mapping* errors: `card1` is shared by up to ~15,000 transactions, so it isn't one card; `anonymous.com` behaves like a mainstream provider; and the risk is having a recipient email at all, not a mismatch.
- **Corrected proxies** (customer-level velocity 2.07x, real privacy providers 6.34x, recipient email present 2.76x) lift the fixed-weight score's AUC from 0.57 to 0.67 on the latest 40% of transactions. Those corrections were chosen after seeing the data, so this is reported as exploratory, not as a clean out-of-sample win.
- The first-pass results were fixed before looking at the data and are kept as the headline, misses included.

**One limitation.** `isFraud` in IEEE-CIS is chargeback-based, so it mixes true fraud and friendly fraud; and the anonymized columns only approximate customers and devices. Lift here supports an idea; it doesn't calibrate the simulator's thresholds.

**Likely interview question.** *"Your project is synthetic, so how do you know any of it works?"*
Short answer: the synthetic data proves the logic separates attacks from realistic lookalikes; on real IEEE-CIS data the account-takeover signal carried over at 2.2x lift, and two proxies failed, which taught me to check what a field actually means before trusting a rule built on it. I kept the failed first pass in the report rather than quietly swapping in the fixed version.
