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

receipts:
	$(PY) -m run.content receipts

test:
	$(PY) -m pytest tests/ -q
