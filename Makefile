PY := .venv/bin/python

.PHONY: week ingest backtest test content receipts sync sync-preview dry-send send

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

backtest:
	$(PY) -m engine.backtest

content:
	$(PY) -m run.content all

# Turn completed payments into the subscriber registry. Needs STRIPE_API_KEY.
sync:
	$(PY) -m run.sync

# What the next sync WOULD change, without writing or stamping anything.
sync-preview:
	$(PY) -m run.sync --dry-run --no-promote

# Build every subscriber's report and write the emails WITHOUT sending them.
# Read reports/outbox/*.eml to see exactly what would land in an inbox.
dry-send:
	EMAIL_PROVIDER=dry $(PY) -m run.batch

# The real thing. Needs EMAIL_PROVIDER + that provider's key in the environment.
send:
	$(PY) -m run.batch

receipts:
	$(PY) -m run.content receipts

test:
	$(PY) -m pytest tests/ -q
