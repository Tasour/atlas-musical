.PHONY: install dev analysis download run test lint

install:
	python3 -m pip install -e .

dev:
	python3 -m pip install -e ".[dev]"

analysis:
	python3 -m pip install -e ".[analysis,download]"

download:
	python3 -m analysis.download

run:
	python3 server.py

test:
	pytest

lint:
	ruff check .
	node --check app/app.js
