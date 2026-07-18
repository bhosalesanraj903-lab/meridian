.PHONY: up down ps logs test lint gen ingest

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

test:
	pytest -q tests/

lint:
	ruff check .

gen:
	python generator/generate_customers.py --count 5000 --seed 42

ingest:
	python ingestion/ofac/ofac_ingest.py
