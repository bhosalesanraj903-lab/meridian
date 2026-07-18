.PHONY: install test test-all lint gen ingest resolve screen build-lambdas

build-lambdas:
	rm -rf build/lambda_pkg build/ofac_ingest.zip && mkdir -p build
	.venv/bin/pip install --quiet --target build/lambda_pkg --no-deps .
	.venv/bin/pip install --quiet --target build/lambda_pkg requests
	cp lambdas/ofac_ingest/handler.py build/lambda_pkg/
	cd build/lambda_pkg && zip -qr ../ofac_ingest.zip . -x "*.pyc" -x "*__pycache__*"

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
