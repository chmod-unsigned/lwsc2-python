.SILENT:
.PHONY: clean pip-update pip-install run

VENV := .venv-nogil
PYTHON := $(VENV)/bin/python3.13t
PIP := $(VENV)/bin/pip
PY := lwsc

clean:
	rm -rf $(VENV)

$(VENV):
	python3.13t -m venv $(VENV)

pip-update: $(VENV)
	$(PYTHON) -m pip install --upgrade pip

$(VENV)/.pip-installed: $(VENV) requirements.txt
	$(PIP) install -r requirements.txt
	touch $(VENV)/.pip-installed

pip-install: pip-update $(VENV)/.pip-installed

run: pip-install
	$(PYTHON) src/$(PY).py