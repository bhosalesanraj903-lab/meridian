.PHONY: install test test-all lint gen ingest resolve screen

PY := .venv/bin/python

install:
	python3 -m venv .venv && .venv/bin/pip install -e ".[dev,aws]"

test:
	$(PY) -m pytest -q -m "not slow" tests/

test-all:
	$(PY) -m pytest -q tests/

lint:
	.venv/bin/ruff check .

gen:
	$(PY) -m meridian.generator.customers --count 5000 --seed 42

ingest:
	$(PY) -m meridian.ingestion.ofac

resolve:
	$(PY) -m meridian.matching.resolver

screen:
	$(PY) -m meridian.screening.screen
