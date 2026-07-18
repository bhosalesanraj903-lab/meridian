.PHONY: install test test-all lint gen ingest resolve screen build-lambdas

# One bundle zip serves every Lambda (handlers are renamed <name>_handler.py);
# heavy deps (splink/pandas/duckdb) are deliberately NOT imported by handlers.
build-lambdas:
	rm -rf build/lambda_pkg build/ofac_ingest.zip build/lambda_bundle.zip && mkdir -p build
	.venv/bin/pip install --quiet --target build/lambda_pkg --no-deps .
	.venv/bin/pip install --quiet --target build/lambda_pkg requests
	cp lambdas/ofac_ingest/handler.py build/lambda_pkg/ofac_ingest_handler.py
	cp lambdas/resolution_trigger/handler.py build/lambda_pkg/resolution_trigger_handler.py
	cp lambdas/gold_notifier/handler.py build/lambda_pkg/gold_notifier_handler.py
	cp lambdas/flow_widget/handler.py build/lambda_pkg/flow_widget_handler.py
	cd build/lambda_pkg && zip -qr ../lambda_bundle.zip . -x "*.pyc" -x "*__pycache__*"

build-wheel:
	rm -f build/meridian-*.whl
	.venv/bin/pip wheel --quiet --no-deps -w build .

# Vendor every Glue-job dependency as a prebuilt wheel for the Glue Python
# Shell platform (cp39/manylinux2014). Installing from these S3 wheels removes
# PyPI resolution from job startup entirely — see INC-001.
build-wheelhouse:
	rm -rf build/wheelhouse && mkdir -p build/wheelhouse
	.venv/bin/pip download --only-binary=:all: \
		--platform manylinux2014_x86_64 --python-version 3.9 \
		--implementation cp --abi cp39 --abi abi3 --abi none \
		-d build/wheelhouse \
		"splink==4.0.16" "duckdb==1.1.3" "pandas==2.2.3" "pyarrow==17.0.0" \
		"rapidfuzz==3.9.7" "igraph==0.11.9" "numpy==1.26.4" "requests==2.32.5"

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

status:
	$(PY) tools/status.py
