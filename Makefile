.PHONY: install dev analysis download discover run test lint

install:
	python3 -m pip install -e .

dev:
	python3 -m pip install -e ".[dev]"

analysis:
	python3 -m pip install -e ".[analysis,download]"

download:
	python3 -m analysis.download

discover:
	python3 -m analysis.discover --target 50

run:
	python3 server.py

test:
	pytest

lint:
	ruff check .
	node --check app/app.js
