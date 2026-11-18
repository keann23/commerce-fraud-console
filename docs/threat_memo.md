# Threat memo: commercial abuse in a creative-software subscription business

*Portfolio analysis by Kean Zhu. It describes how abuse typically targets a Creative Cloud-style business (monthly and annual plans, free trials, student pricing, cloud storage, metered generative-AI features) using general industry knowledge and the results of this project's simulator. It contains no Adobe data and makes no claims about Adobe's internal systems or numbers. All figures marked (sim) come from the synthetic simulator.*

---

## Bottom line

1. **Account takeover is the highest-impact threat.** Long-tenured accounts hold stored cards, years of cloud files and paid entitlements, and the customer is the victim. Response must protect the owner (MFA step-up, freeze changes, roll back), never ban.
2. **Card testing is the most frequent and the cheapest to stop.** It is loud (bursts of micro-auths, many cards, mostly declined), and the damage comes later, when validated cards are cashed out elsewhere. Block the burst **and** the cards it proved live.
3. **Trial and discount abuse quietly inflates growth metrics.** In the simulator, identity linking showed **9.9% of "unique" trial accounts were repeat identities** (sim). The fix is friction on the next trial, not bans.
4. **Friendly fraud is a margin problem, not a security problem.** Win it back with evidence (same device, same IP, usage after purchase) and keep the customer.
5. **Measure false declines as seriously as fraud loss.** At an aggressive threshold, a block-only policy turned away **288 honest customers vs ~14 with a graduated response ladder, for the same fraud stopped** (sim).

## Threats, ranked

| # | Threat | Likelihood | Impact | Why it targets this business |
|---|---|---|---|---|
| 1 | Account takeover (credential stuffing) | High | High | Huge consumer user base reusing passwords; stored cards; valuable files and entitlements; accounts resellable |
| 2 | Card testing at checkout | High | Medium | Low-friction checkout and $0/$1 trial auths are ideal for validating stolen cards |
| 3 | Trial, promo and student-discount abuse | High | Medium | Free trials and steep student pricing reward multi-accounting; email aliasing is trivial |
| 4 | Friendly fraud and renewal disputes | Medium | Medium | Auto-renewing subscriptions produce "I forgot to cancel" and "I didn't authorize this" disputes; dispute ratios carry card-network penalties |
| 5 | Metered-AI credit farming | Medium (rising) | Medium | Free generative-AI allowances per account have real compute cost; multi-accounting converts directly into cost |
| 6 | Reseller and license abuse | Medium | Medium | Gray-market "lifetime" keys, shared team seats, and region-price arbitrage |

*#5 and #6 are outside the simulator today; they are listed because they share the same building blocks (identity linking, velocity, entitlement anomalies).*

## Threat by threat

### 1. Account takeover
- **Signals:** login from a device and country never seen on the account (counting successful logins only), impossible travel (> 900 km/h), then from that same device within 48 hours: password reset → email change → new card → large purchase or upgrade. Crews reuse a few machines across many victims.
- **Simulator result:** recall 1.00, 0 false positives across 72 honest lookalikes (travelers with new phones, forgotten passwords) (sim). Weakest catch scored 70 vs a legit maximum of 25.
- **Gap:** a crew on residential proxies in the victim's city, spoofing the victim's device fingerprint, shows up only through the account-change chain (score ~55, below the line).
- **Recommend:** score "reset → email change" chains on their own regardless of device; check leaked-credential feeds at login; always notify the *original* email on email change; 72-hour hold on payment-method changes after a reset.

### 2. Card testing
- **Signals:** per IP and device in a rolling 10 minutes: attempt velocity, distinct cards, decline rate (only meaningful with 5+ attempts), micro amounts, shared BIN or sequential last-4.
- **Simulator result:** recall 1.00, 0 false positives, including campus networks starting $1 trial auths together (sim). Cards proven live by flagged bursts were later cashed out for **$52.7k** (sim).
- **Gap:** slow, distributed testing (hours, rotating proxies, fresh fingerprints) evades 10-minute windows.
- **Recommend:** add 1-hour and 24-hour windows and BIN-level velocity; watch global micro-auth decline rate as a backstop; **block validated card fingerprints**, not just the IP; CAPTCHA (not block) for mid scores, because shared IPs carry honest users.

### 3. Trial and discount abuse
- **Signals:** connected components over shared device, card fingerprint and normalized inbox (Gmail dots and plus tags removed; disposable domains flagged); trials per cluster; zero conversions; virtual cards; cancel right before billing; student plan on non-academic emails.
- **Simulator result:** recall 0.99, 0 false positives on families, library computers and returning students (sim). The two misses used a fresh device, card and inbox at once.
- **Recommend:** require a non-virtual card and phone verification for a second trial in a cluster; verify student status through an academic-verification step rather than email domain; report **trial inflation** as a standing growth metric.

### 4. Friendly fraud and renewal disputes
- **Signals:** "unauthorized" dispute on a purchase from the customer's usual device and IP, by a long-tenured account, with heavy product usage afterwards.
- **Simulator result:** recall 1.00; honest stolen-card disputes topped out at 50 vs a 60 line (sim).
- **Recommend:** auto-assemble evidence packs (device/IP match with prior undisputed purchases, post-purchase usage); send pre-renewal reminders and make cancellation easy, since that removes most "forgot to cancel" disputes at the source; track dispute ratio by **purchase** month with a maturity curve, because disputes arrive weeks late.

### 5. Metered-AI credit farming (emerging)
- **Likely signals:** many free accounts in one identity cluster each exhausting the free allowance; generation patterns automated (fixed intervals, identical prompts); API-like client fingerprints.
- **Recommend:** reuse the trial-abuse identity graph; meter allowances per *identity cluster* rather than per account; step up (phone verification) before a second free allowance in a cluster.

### 6. Reseller and license abuse
- **Likely signals:** one payment instrument funding many unrelated accounts; seat assignments churning across countries; region-priced purchases used from other regions.
- **Recommend:** price-region consistency checks; seat-assignment velocity limits; takedown workflow for marketplaces selling "lifetime" access.

## Response principles

| Principle | Why |
|---|---|
| Graduated ladder: allow → step-up → review → block | Challenges cost honest users ~5%; blocks cost them 100% |
| Never block victims or paying customers | ATO victims need protection; friendly-fraud customers need evidence, not a ban |
| Block the asset, not just the source | IPs rotate; validated cards and linked identities persist |
| Every alert carries reason codes | Analysts must explain decisions to customers, auditors and card networks |

## Metrics to watch weekly

- Dispute ratio by purchase month, with a maturity projection (keep well under card-network thresholds)
- False-decline rate and step-up abandonment rate
- Micro-auth (≤ $2) volume and decline rate: the leading indicator for card testing
- ATO rate per 10,000 logins; share of accounts with MFA
- Trial inflation and trial-to-paid conversion per identity cluster

## 30 / 60 / 90 days

- **30:** turn on reason codes and the response ladder for card testing and ATO; start weekly intel briefs; baseline false declines.
- **60:** identity-cluster trial limits and student verification; evidence-pack automation for disputes; slower card-testing windows.
- **90:** extend the identity graph to AI-credit allowances; leaked-credential checks at login; validate signals on real labelled data (IEEE-CIS replication in this repo is the first step).

## Limits of this memo

The simulator's data is synthetic, so the recall and false-positive figures show that the *logic* separates attacks from realistic lookalikes. They are not a forecast of production performance. The friction and stop rates in the ladder are stated assumptions. Real deployment needs A/B-measured challenge abandonment, matured chargeback labels, and attackers who adapt.
