PY := .venv/bin/python
SEASON ?= 2026
# The public sample league the retired Sleeper-era study was measured on.
RETIRED_LEAGUE ?= 289646328504385536

.PHONY: week ingest backtest backtest-early backtest-retired test content receipts sync sync-preview dry-send send demo index \
        intake intake-preview tuesday tuesday-preview monday monday-preview sample

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

# Regenerate the LIVE product's grading AND republish it. The published page
# claims to be generated, so the two must never be run apart.
backtest:
	$(PY) -m engine.nflverse_backtest
	$(PY) -m render.backtest_site
	$(PY) -m render.backtest_site --source $(PWD)/reports/backtest.md

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
