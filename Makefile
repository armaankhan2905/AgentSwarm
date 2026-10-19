PYTHON ?= .venv/bin/python

.PHONY: test test-portable backend-test frontend-test build backend-run

test: backend-test frontend-test

test-portable:
	$(PYTHON) scripts/test.py

backend-test:
	$(PYTHON) -m pytest -q

frontend-test:
	npm --prefix frontend test

build:
	npm --prefix frontend run build

backend-run:
	$(PYTHON) -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
