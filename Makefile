PY := .venv/bin/python

.PHONY: week ingest backtest test

week:
	$(PY) -m run.week

ingest:
	$(PY) -m ingest.pull

backtest:
	$(PY) -m engine.backtest

test:
	$(PY) -m pytest tests/ -q
