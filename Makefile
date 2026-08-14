PY := .venv/bin/python

.PHONY: week ingest backtest test content receipts

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

backtest:
	$(PY) -m engine.backtest

content:
	$(PY) -m run.content all

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
