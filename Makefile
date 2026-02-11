.PHONY: install dev run docker-build docker-up docker-down sandbox-build lint test clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

run:
	python -m senti

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

sandbox-build:
	docker build -t senti-search:latest sandbox_images/search/
	docker build -t senti-gdrive:latest sandbox_images/gdrive/
	docker build -t senti-email:latest sandbox_images/email_proxy/
	docker build -t senti-python:latest sandbox_images/python_runner/

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

test:
	pytest tests/ -v

clean:
	rm -rf data/senti.db data/logs/*.log
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
