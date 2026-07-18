.PHONY: install test test-all lint gen ingest resolve screen build-lambdas

# One bundle zip serves every Lambda (handlers are renamed <name>_handler.py);
# heavy deps (splink/pandas/duckdb) are deliberately NOT imported by handlers.
build-lambdas:
	rm -rf build/lambda_pkg build/ofac_ingest.zip build/lambda_bundle.zip && mkdir -p build
	.venv/bin/pip install --quiet --target build/lambda_pkg --no-deps .
	.venv/bin/pip install --quiet --target build/lambda_pkg requests
	cp lambdas/ofac_ingest/handler.py build/lambda_pkg/ofac_ingest_handler.py
	cp lambdas/resolution_trigger/handler.py build/lambda_pkg/resolution_trigger_handler.py
	cd build/lambda_pkg && zip -qr ../lambda_bundle.zip . -x "*.pyc" -x "*__pycache__*"

build-wheel:
	rm -f build/meridian-*.whl
	.venv/bin/pip wheel --quiet --no-deps -w build .

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
