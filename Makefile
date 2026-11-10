.PHONY: dev test setup demo reset samples
PY=.venv/bin/python
setup:
	python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m playwright install chromium
	$(PY) -m vendorcheck.adapters.ifsc --download
dev:
	$(PY) -m vendorcheck
test:
	$(PY) -m pytest -q
samples:
	$(PY) scripts/make_samples.py
demo:
	$(PY) scripts/run_demo.py
reset:
	rm -f data/vendorcheck.db
