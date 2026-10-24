PY := .venv/bin/python
SEASON ?= 2026
# The public sample league the retired Sleeper-era study was measured on.
RETIRED_LEAGUE ?= 289646328504385536

.PHONY: week ingest backtest backtest-early backtest-retired test content receipts sync sync-preview dry-send send demo index \
        intake intake-preview tuesday tuesday-preview saturday saturday-preview proving stats ask launch-check launch-check-fast drops sitemap monday monday-preview sample \
        og brand billing billing-preview roster-update seat-release waitlist-preview waitlist-send live-sample

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

# Regenerate the LIVE product's grading AND republish it. The published page
# claims to be generated, so the two must never be run apart.
backtest:
	$(PY) -m engine.nflverse_backtest
	$(PY) -m render.backtest_site

# The early-season arm (weeks 2-3, prior-season seeded). Separate target: it
# is a preregistered arm with its own frozen method, not part of the headline
# run, and its report is read by site/confidence.html.
backtest-early:
	$(PY) -m engine.early_season_backtest

# The RETIRED Sleeper-era study. Kept generated and unedited because a past
# measurement is part of the record; it publishes to no page. Needs the sample
# league it was measured on, which is why it takes an explicit --league.
backtest-retired:
	$(PY) -m engine.backtest --league $(RETIRED_LEAGUE)

# The public drafts, from the graded record (run/posts.py). `make content`
# used to run run/content.py, which drafts from a Sleeper league and so
# produces nothing for the product that ships — pointing the target at the
# live path is what stops somebody generating league-flavoured drafts for a
# product that has no league.
content:
	$(PY) -m run.posts all

# Turn completed payments into the subscriber registry. Needs STRIPE_API_KEY.
sync:
	$(PY) -m run.sync

# What the next sync WOULD change, without writing or stamping anything.
sync-preview:
	$(PY) -m run.sync --dry-run --no-promote

# --- the roster product (PLAN §0): no league is ever read ------------------
#
# The Tuesday pair. `intake` turns completed payments into data/registry/
# rosters.json; `tuesday` builds and mails one report per roster in it. Both
# have a preview that writes nothing, because the first time either is run
# against real customers should not also be the first time anyone sees its
# output.
intake:
	$(PY) -m run.intake

intake-preview:
	$(PY) -m run.intake --dry-run

tuesday:
	$(PY) -m run.tuesday

tuesday-preview:
	EMAIL_PROVIDER=dry $(PY) -m run.tuesday --allow-dry

# The Saturday final check: Friday's injury report against the lineups sent
# on Tuesday. Mails only the subscribers whose lineup has to change.
saturday:
	$(PY) -m run.saturday

saturday-preview:
	EMAIL_PROVIDER=dry $(PY) -m run.saturday --allow-dry

# Weeks 4-8 of 2025 through every runner, with twelve made-up subscribers and
# a fake mail provider. Writes only to a temp folder.
proving:
	$(PY) -m run.proving

# The owner's demand summary: form Worker rows + the committed send log (+ the
# registry if a copy is here). Counts only, never an address. Read-only.
stats:
	$(PY) -m run.stats

# A roster change a subscriber sent by email ("reply with your new roster"),
# applied through the same validated path as a confirmed self-serve update: it
# posts an authenticated update row to the form Worker and the next hourly
# intake checks it and keeps their scoring and lineup. ROSTER is a file of the
# names they sent, or - for stdin. Needs UPDATE_SECRET and FORM_ENDPOINT (the
# GitHub secrets' values) in this shell. Prints no address. ARGS=--dry-run
# resolves the names and posts nothing.
#   make roster-update EMAIL=fan@example.com ROSTER=names.txt
roster-update:
	$(PY) -m run.updates --email "$(EMAIL)" --roster "$(ROSTER)" $(ARGS)

# Free a League Pass seat whose holder has left the league (D10): the address
# goes on the stop list, and the next hourly intake releases that seat, so the
# pass has room for the manager who replaced them. Commit and push
# data/processed/suppressed.txt — the crons read the committed copy. Prints no
# address. To give the seat back: python -m run.suppress --remove EMAIL.
#   make seat-release EMAIL=left@example.com
seat-release:
	$(PY) -m run.suppress "$(EMAIL)"

# The launch announcement, the one email the waitlist was promised. Preview
# first. The send needs EMAIL_PROVIDER + its key (RESEND_API_KEY or
# POSTMARK_TOKEN), EMAIL_FROM, SITE_URL, SENDER_POSTAL_ADDRESS, and FORM_ENDPOINT
# + FORM_API_KEY for the Worker's list — or LIST=file.csv (an `email` column)
# for the sign-ups that arrived by email before the Worker existed; run it once
# per list, the send log keeps anyone on both to one message. Afterwards commit
# and push data/processed/sent.jsonl: the crons read the committed copy, and it
# is what stops a second send.
waitlist-preview:
	$(PY) -m run.waitlist $(if $(LIST),--list "$(LIST)")

waitlist-send:
	$(PY) -m run.waitlist --send $(if $(LIST),--list "$(LIST)")

# This week's live sample (site/this-week.html + site/week.json). Its FIRST
# build before the week's first kickoff RECORDS its odds on the public ledger,
# like a subscriber's report; every later build of the week is refused unless
# ARGS=--force, which records nothing and prints only the odds on the record
# (after kickoff, only those on games not yet started, and the page says it
# was rebuilt after the week began). ARGS=--no-record previews before kickoff.
live-sample:
	$(PY) -m render.live_sample $(ARGS)

# The product's own answer to "A or B this week?", for replying in public:
# facts for both, and the report's % only with ARGS=--publish, which records
# it on the public record first (graded Monday). Also --scoring, --size.
ask:
	$(PY) -m run.ask "$(A)" "$(B)" $(ARGS)

# Launch readiness: the site, the funnel, this week's product, compliance text,
# email DNS, owner setup and the economics, as PASS/FAIL/WARN/OWNER gates.
# Read-only. `make launch-check-fast` skips the browser, proving run and tests.
launch-check:
	$(PY) -m run.launch_check

launch-check-fast:
	$(PY) -m run.launch_check --fast

# This week's public posts, drafted from the live sample report (content/this-week.md).
drops:
	$(PY) -m run.drops

# site/sitemap.xml, derived from which pages say noindex (tests fail if it is stale).
sitemap:
	$(PY) -m render.sitemap

# site/_headers — Cloudflare Pages' security headers, with each page's inline
# scripts hashed into its Content-Security-Policy. Run after editing any
# page's <script>; tests fail if it is stale (GitHub Pages ignores the file).
.PHONY: headers lock notice-approval
headers:
	$(PY) -m render.headers

# requirements.lock / requirements-dev.lock, hash-locked from requirements.txt
# (needs PyPI). Run after changing a pin and commit all three.
lock:
	$(PY) -m infra.lock_requirements

# The owner's code for a real change-notice send (needs LOG_SECRET):
#   make notice-approval PAGE=terms EFFECTIVE=2026-11-15
# then paste the summary when asked, exactly as it goes in the workflow's box.
# SUMMARY='...' in SINGLE quotes works too. Either way the words reach the code
# as typed: the recipe passes each variable's RAW text ($(value ...)), single-
# quoted for the shell. "$(SUMMARY)" let make expand "$69" to "9" (and a
# double-quoted shell word drops quotes), so the code was signed over words
# nobody pasted and the workflow refused it.
shell_quote = '$(subst ','\'',$(value $(1)))'
notice-approval:
	$(PY) -m run.approval notice $(call shell_quote,PAGE) $(call shell_quote,EFFECTIVE) $(if $(value SUMMARY),$(call shell_quote,SUMMARY),-)

# Settle last week's published calls against the real box scores and republish
# the public record. No secrets, no league — grading reads public data only.
monday:
	$(PY) -m run.monday

monday-preview:
	$(PY) -m run.monday --dry-run

# --- the Sleeper-era pair, being retired -----------------------------------
#
# Build every subscriber's report and write the emails WITHOUT sending them.
# Read reports/outbox/*.eml to see exactly what would land in an inbox.
dry-send:
	EMAIL_PROVIDER=dry $(PY) -m run.batch --allow-dry

# The real thing. Needs EMAIL_PROVIDER + that provider's key in the environment.
send:
	$(PY) -m run.batch

# The demo on the marketing site plus the local pair, rebuilt through the real
# renderers. This existed only as ad-hoc commands, and the page it produces is
# the launch proof — a hand-edit would drift the sales page away from the
# product. --public runs anonymize_for_public(); nothing under reports/ is
# tracked because those renders name real league members.
# NOTE: `demo` no longer writes into site/ — the published sample belongs to
# `make sample` (the solo product). This pair is the LOCAL legacy league demo
# only; the day this target wrote site/sample-report.html again it silently
# replaced the solo sample with a league report full of features the paid
# product does not have.
demo:
	$(PY) -m engine.week_report --league 289646328504385536 --week 10 --roster 1
	$(PY) -m render.report --public --output reports/league-demo-public.html
	$(PY) -m render.report
	$(PY) -c "import json,pathlib,run.week as w; \
	  r=json.loads(pathlib.Path('data/processed/week_report.json').read_text()); \
	  m=r['meta']; p=pathlib.Path('reports')/f\"rival-report-{m['season']}-w{int(m['week']):02d}-r{m['my_roster_id']}.txt\"; \
	  p.write_text(w.text_summary(r), encoding='utf-8'); print(f'summary rewritten to {p}')"

# The published sample report — the funnel's proof asset. `make sample` is the
# only way to rebuild it: it runs the REAL pipeline (run/solo.py -> the same
# template a subscriber's report uses), so no number can appear on the page
# unless the product computed it. The roster and week are pinned in
# render/sample.py.
# Both published samples: the mid-season file a buyer decides on, and the
# WEEK ONE file they actually receive first. They link to each other, so
# rebuilding one without the other is how the pair drifts.
sample:
	$(PY) -m render.sample
	$(PY) -m render.sample --week 1

# The social preview card. Needs headless Chrome, so it is a deliberate local
# act like `make sample` — the PNG is committed and CI never renders one.
# Run it after any change to the landing page's hero file card: the card's
# figures are READ from that page, so a stale og.png advertises stale numbers.
og:
	$(PY) -m render.og

# The two PNGs Stripe's branding settings take. Same mark as every page, so
# there is no second drawing of the logo to drift from the first. Committed;
# CI never renders one.
brand:
	$(PY) -m render.brand

# End monthly subscriptions in their final paid period (the one the season's
# last weekly report falls in), so none renews into a month with no report.
# Preview first: this is the only money-mutating call in the repo.
billing-preview:
	$(PY) -m run.billing

billing:
	$(PY) -m run.billing --send

# One person's data (run/privacy.py). Make the keyed code HERE, never in CI:
#   make privacy-code EMAIL=their@address      (needs LOG_SECRET in the shell)
# then run the privacy-request workflow with that code, or locally:
#   make privacy ACTION=show|export|delete CODE=<12 hex>   (mails hello@)
.PHONY: privacy-code privacy notice-preview notice
privacy-code:
	$(PY) -m run.privacy code "$(EMAIL)"

privacy:
	$(PY) -m run.privacy $(ACTION) $(CODE) --send

# The terms/privacy change notice, before the change takes effect:
#   make notice-preview PAGE=terms EFFECTIVE=2026-11-01 SUMMARY="..."
notice-preview:
	$(PY) -m run.notice --page $(PAGE) --effective $(EFFECTIVE) --summary "$(SUMMARY)"

notice:
	$(PY) -m run.notice --page $(PAGE) --effective $(EFFECTIVE) --summary "$(SUMMARY)" --send

# One pre-season file, for eyeballing it before a send. Takes a roster of
# player ids; the real ones come from a subscriber's own ref at intake.
# make preseason ROSTER="00-0034796,00-0032764,..."
preseason:
	$(PY) -m render.preseason --roster "$(ROSTER)" --print

# The player directory the intake page downloads. Regenerate whenever the
# nflverse cache moves — a stale directory cannot resolve a rookie, and the
# subscriber who rostered him simply cannot finish signup. `--check` fails if
# the committed asset has drifted, which is what CI runs.
index:
	$(PY) -m render.player_index --season $(SEASON)

# Grade first, then draft: a Receipts post written before settlement is a
# post about games that have not finished.
receipts:
	$(PY) -m run.monday
	$(PY) -m run.posts receipts

test:
	$(PY) -m pytest tests/ -q
