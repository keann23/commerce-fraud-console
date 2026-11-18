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

Results on seed 42 (12 campaigns, 42 attack IPs/devices, 430 lookalikes): recall 1.00, precision 1.00, false positive rate 0 on legit and on lookalikes. The margin matters more than the headline: the weakest attack entity scored 90, while the strongest legit entity (a customer retrying their own card 7 times) scored 51, against an alert line of 60. A test also injects the hardest campaign the PRD allows (100 attempts over 30 minutes split across 3 IPs and 3 devices, only 70% declined, for each card pattern) and requires every entity to be caught.

A second table, `card_testing_validated_cards`, lists the cards a flagged burst proved were live and whether they were later charged. On seed 42 that is 871 validated cards, 440 of them cashed out for $53.6k.

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

Results on seed 42 (10 rings, 268 abuse accounts, 155 lookalikes): recall 0.993, precision 1.00, false positive rate 0 on all legit and on lookalikes. The lowest-scoring lookalike scored 43, against an alert line of 60. Collapsing identities turns **4,011 trial accounts into 3,616 real people: 9.9% trial inflation.** The 2 misses were accounts that used a fresh device, a fresh card and a throwaway inbox all at once: nothing links them, so a graph can't see them.

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

Results on seed 42 (8 campaigns, 94 victims, 72 lookalikes): recall 0.99, precision 1.00, false positive rate 0. Legit accounts never scored above 25 (new device + new country: a traveler with a new phone). Attacks averaged 88. The one miss scored 55: the crew logged in from a country that victim had already visited, so the new-country and impossible-travel points never fired.

**Why this response.** 60 to 84 → **step up**: force MFA re-authentication and freeze email and payment changes for 72 hours. 85+ → **review**: kill sessions, verify the owner through the *original* email, roll back the email and card changes, refund the charge. Never **block**: banning the account punishes the victim (a test enforces this). Friction cost: a legit traveler with a new phone at most gets an MFA prompt, which they can pass.

**One limitation.** The anchor relies on device and country being new. A crew using residential proxies in the victim's own city, with a spoofed copy of the victim's device fingerprint, only shows up through the account changes, which caps the score around 55 (exactly the miss above). Real teams add behavioural biometrics (typing, navigation speed), check leaked-credential databases at login, and give a "reset then email change" chain weight on its own regardless of device.

**Likely interview question.** *"How is impossible travel computed, and how does it produce false positives?"*
Short answer: haversine distance between consecutive logins divided by the time between them; over 900 km/h (faster than a plane) is impossible. False positives come from IP geolocation error (mobile carriers, VPNs, corporate egress in another city), so I also require 500+ km, and in production I'd discount hops involving VPN or hosting IPs.
