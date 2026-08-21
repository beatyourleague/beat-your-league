PY := .venv/bin/python
SEASON ?= 2026

.PHONY: week ingest backtest test content receipts sync sync-preview dry-send send demo index \
        intake intake-preview tuesday tuesday-preview

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

# Regenerate the record AND republish it. The published page claims to be
# generated, so the two must never be run apart.
backtest:
	$(PY) -m engine.backtest
	$(PY) -m render.backtest_site

content:
	$(PY) -m run.content all

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
demo:
	$(PY) -m engine.week_report --league 289646328504385536 --week 10 --roster 1
	$(PY) -m render.report --public --output site/sample-report.html
	$(PY) -m render.report
	$(PY) -c "import json,pathlib,run.week as w; \
	  r=json.loads(pathlib.Path('data/processed/week_report.json').read_text()); \
	  m=r['meta']; p=pathlib.Path('reports')/f\"rival-report-{m['season']}-w{int(m['week']):02d}-r{m['my_roster_id']}.txt\"; \
	  p.write_text(w.text_summary(r), encoding='utf-8'); print(f'summary rewritten to {p}')"

# The player directory the intake page downloads. Regenerate whenever the
# nflverse cache moves — a stale directory cannot resolve a rookie, and the
# subscriber who rostered him simply cannot finish signup. `--check` fails if
# the committed asset has drifted, which is what CI runs.
index:
	$(PY) -m render.player_index --season $(SEASON)

receipts:
	$(PY) -m run.content receipts

test:
	$(PY) -m pytest tests/ -q
