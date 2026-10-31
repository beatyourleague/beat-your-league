# Launch readiness

Oct 15 2026, NFL Week 6. An audit before taking the first payment: four research briefs
(who pays for fantasy tools, the 2026 competitors, conversion benchmarks, costs and
compliance) and eight audits (the product built for six real rosters this week, two panels
of four buyer personas walking the site on their own devices, the website, operations,
economics, legal, go-to-market). An adversarial verifier re-checked every serious finding;
93 were confirmed, 1 refuted. Estimates are labelled. Not legal or tax advice.

**The repeatable version of this check is `make launch-check`.** It turns everything a machine
can verify into PASS / FAIL / WARN / OWNER gates and says READY only when nothing is left.

## Verdict

**A viable product for a narrow, real buyer — not ready to take money until the owner steps
below are done.** It leads the field on honesty and on the shape of the service: decided for
you, in your inbox, any league app, no login, a Saturday check only when Friday's injury
report changes something, and a refund that beats the category. It was behind the free app
optimizers on what they already show (opponent, kickoff, current injury status); the report
work below closes most of that from facts alone. The owner's own rules exclude the
category's usual trust signals (named experts, accuracy awards, user counts), so the free
report on the visitor's own roster is the strongest conversion lever left — switch it on
with sending.

Treat the rest of 2026 as a proof season. The profit case is August 2027.

## Who to sell to first

**The busy money-league regular**: about 28–49, a white-collar job, 1–3 leagues with at
least one $50–$100 buy-in on ESPN, Yahoo or CBS (average entry fees: CBS $122, Yahoo $91,
ESPN $70, Sleeper $45). Already in the top quarter of fantasy spenders, about 4.5 hours a
week on it, and wants the decision made rather than another tool to run. **Sell him the $14.99
Monthly plan** (2026 sells monthly plans that stop on their own; the $39 season pass is 2027's).

**Second: his league's commissioner**, buying the $34.99-a-month League Pass out of the pot
(about $2.92 a manager in a 12-team league). Each sale puts the brand in front
of 10–12 managers, and word of mouth is how players find tools — which matters most for an
anonymous brand.

Not yet: multi-league grinders (FantasyPros covers 50 leagues), Sleeper-native under-30s
(lowest buy-ins, free AI, and a two-FLEX default lineup the product can't set up yet), free
office leagues.

**The persona panel.** Eight simulated buyers; none would buy with checkout closed, and every
one scored trust lowest (3–6 of 10). The closest — the busy ESPN/Yahoo regular and the
commissioners — flip on the same two things: a free report on their own roster, and a sample
that shows a real close call.

## Scorecard (as audited) and status now

| Area | Audit | Status now |
|---|---|---|
| Product value | 6, at risk | **Fixed:** opponent and kickoff on every row, a Thursday-night line, an "if he's cleared" plan for players ruled out last week, dated injury wording, no pointless Sunday checks, an email that fits a 390px phone |
| Decision quality | 5, **no-go** | **Fixed:** injured reserve, PUP, suspended and released players are out in the weekly report (they were started with odds) |
| Website appeal | 7, at risk | **Fixed:** apps named in the hero; FAQs for "more than one league" and "why not a chatbot"; honest scoring coverage; the false "nobody answers who do I start" line gone |
| Conversion funnel | 3, **no-go** | Code side **fixed** (Sleeper kicker line, ranked search, problems first, the live sample shows odds again); checkout, waitlist and free report wait on owner steps |
| Trust | 5, at risk | Live sample rebuilt on a rule-chosen 2026 roster; "file" wording fixed at the source |
| Pricing & economics | 7, go | Fee figures corrected (about 7%, not 3.7%); League Pass's false "cheaper than one buy-in" replaced with the dues split |
| Operations | 5, at risk | **Fixed in code:** the form Worker starts the crons on time (GitHub's schedule as backup), a watchdog alarms when a Tuesday or Saturday run never happened, pre-launch runs stop filing false issues, the Tuesday run refuses a week already underway, free reports can't crowd out paid ones. Owner: deploy the Worker with its token, DMARC |
| Legal & compliance | 4, **no-go** | **Fixed:** Pay-button text matches the terms; required terms box names the renewal and 18+; consent recorded on the customer; privacy names every processor; renewal notice complete; launch email has a sender and opt-out. Owner: mailbox address |
| Go-to-market | 3, at risk | **Added:** posts that lead with the manager's question and one fact; `make ask` for the product's own answer to "A or B?" (the % only when it's recorded publicly); `?via=` channel tags counted by `make stats`; a League Pass group-chat line and a pass-buyer thank-you page. Owner: one pseudonymous handle, Reddit answers only |
| Brand | 7, go | — |

## The final review (after the fixes)

A second adversarial pass over the fixed product: four reviewers (the report on 240+ real
rosters this week, operations, the site in a browser with checkout switched on, every page
and email for wording and law), each finding re-attacked by a second agent before it counted.
**37 confirmed, 7 refuted, all 37 fixed**, each pinned by a test. The ones that mattered:

- **Players who can't play were still started** when they had no stats yet this season
  (released kickers, injured-reserve tight ends, a backup whose team was on bye) — 29 of 240
  random rosters. They're now benched or flagged, and no new odds appear because of it.
- **Plans that couldn't be followed:** an if/then that moved in a Thursday-night player to
  cover a Sunday starter's Friday news (the flagship sample had one). Every plan now uses a
  player who is still unlocked, or says plainly that nobody can step in.
- **The public record could hold a pick nobody received** after a Tuesday retry. Calls are
  now recorded only when their email is delivered.
- **The missed-run alarm could stay quiet** when one person bought that week, and false-alarm
  in launch week; **old free-report requests could be re-mailed** the next season;
  **a new buyer could be welcomed twice**. All fixed.
- **The League Pass could be bought before seats could be claimed**, and **seat holders had
  no way to stop their emails**. The pass now waits for its seats, and seats get a stop route
  backed by a stop list.
- **The terms and privacy policy promised things nothing does** (one-click cancelling,
  automatic deletions). They now say only what happens.

`make launch-check` after the fixes: **57 pass · 0 fail · 1 warn (unpushed commits) ·
6 owner.** Full suite: 1,359 passing.

## Must be true before the first payment (owner)

All in `LAUNCH.md`, in this order:

1. **Steps 1–3:** payment links checked, Stripe public details (business name, support email
   hello@, no phone or address — receipts show them), the customer portal set to cancel at
   the end of the paid period, the Pay-button script (it now also makes
   the terms box required), Resend verified, **DMARC**, Gmail "Send mail as" hello@, all GitHub
   secrets, and the **fork pull-request approval setting** (the public repo's cache holds the
   subscriber list).
2. **Step 5, the form Worker** — no longer a follow-up. Without it, roster changes have no
   path (every report promises one), seats can't be claimed, and the waitlist is a mailto that
   nothing collects.
3. **A sender address:** a rented mailbox, never a home (about US$10/month), in
   `SENDER_POSTAL_ADDRESS`. The launch announcement refuses to send without it.
4. **Step 4:** one real purchase watched from payment to inbox, then open — ideally for the
   Week 7 Tuesday (Oct 20). Each closed week costs about an eighth of what's left of 2026.
   *(Oct 23: Week 7 passed with checkout closed. The target is now a weekend proving purchase
   and an opening before the Week 8 Tuesday, Oct 27 — LAUNCH.md "Where things stand".)*
5. **Then** Resend Pro and the free own-roster report (`TRIAL_OPEN`).

## The money

From `run/economics.py` (assumptions at its top) and the audit's model. **Re-based Oct 31
2026 on what 2026 actually sells** — $14.99 and $34.99 monthly plans, Stripe's C$15 dispute fee
counted, and the weeks left counted from a Nov 9 opening. An earlier version priced one-time
passes ($29, $19, $69) from an Oct 26 opening and came to about $727.

| Number | Value |
|---|---|
| Stripe on a $14.99 charge (Canadian account, US card, CAD payout) | about 7.9% — $1.18, kept by Stripe on a refund |
| With a USD payout account | about $0.88 |
| Net per buyer after Stripe, 8% refunds and disputes | Monthly about $15.98 · League Pass about $37.76, at 1.3 charges a buyer |
| Break-even on this season's fixed costs | three Monthly buyers (mailbox, domain) |
| Base case for 2026, opening Mon Nov 9 (first report Week 10) | about 30 Monthly buyers + 2 League Passes (30% leave before a second charge, Weeks 13–17 assumed to sell at half a regular week, to the half of a league still alive): about $513 after fixed costs |
| Owner time for that base case | about 49 hours — PLAN §5's own budget of ~35 min a day for 9 weeks (37 h), the weekly QA-and-refunds hour (9 h) and setup (3 h) — so about $11 an hour. `run/economics.py` holds this line to the model |
| 100 subscribers by Week 10 | would need 5,000–20,000 visitors in 2–3 weeks: not organic |
| Paid ads | cost $50–$300 per buyer against about $26 of value (a Monthly buyer plus a 30% chance of a 2027 re-buy at $39): none this season |
| Biggest lever | the refund rate: 15% costs about $48, 25% about $117 per 50 Monthly buyers |
| Free email capacity | Resend's free tier lasts to about 85 recipients a send day |
| GST/HST | not until C$30,000 of sales in four quarters |

**Pricing:** a 2026 plan bills monthly and stops on its own; a 2026 buyer coming back in
2027 is a new purchase, so the model calls it a re-buy rate, never a renewal rate. The working
plan for 2027 is $14.99 and $39 for everyone, with no price promised on any page, and never
prorate; the pass earns more than monthly in every join week. Don't advertise a pass's 12-month coverage until rosters roll to a new
season (IDEAS.md), or 2027 reports would be built from 2026 rosters.

## What was deliberately not done

- No track-record or grade claims on selling pages, no testimonials, no customer counts — the
  owner's rules; the free report is the trust lever instead.
- The flagship sample (a 70% close call) was not re-pinned: that moves every pinned landing
  figure and needs a rule chosen before looking at outcomes (IDEAS.md).
- Two-FLEX lineups, a season roll, a multi-team price, registry encryption: logged in
  IDEAS.md with their reasons.

## Refuted

- "Selling to your own leagues breaks anonymity" — the rule covers public surfaces; your own
  leagues remain the best warm channel.
