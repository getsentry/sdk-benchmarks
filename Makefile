.PHONY: install test lint format

install:
	pip install -e ".[dev]"

test:
	pytest tests/

lint:
	ruff check .

format:
	ruff format .
