.PHONY: up down logs migrate seed test coverage lint format shell webhook smoke

ifeq ($(OS),Windows_NT)
  PY := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,python)
else
  PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
endif

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	docker compose exec web python manage.py migrate

seed:
	docker compose exec web python manage.py seed_data

test:
	pytest

coverage:
	pytest --cov --cov-report=term-missing --cov-fail-under=90

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

shell:
	docker compose exec web python manage.py shell

webhook:
	@echo "Usage: python scripts/simulate_webhook.py --provider-reference <ref> --amount <amount> [--times 3]"
	python scripts/simulate_webhook.py --provider-reference $(REF) --amount $(AMOUNT) --times 3

smoke:
	$(PY) scripts/api_smoke_test.py --flush-throttle
