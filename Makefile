PYTHON ?= python

.PHONY: examples test falsify study figure metadata hygiene validate reproduce clean

examples:
	PYTHONPATH=src $(PYTHON) scripts/regenerate_examples.py

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

falsify:
	PYTHONPATH=src $(PYTHON) scripts/run_exact_falsification.py

study:
	bash scripts/run_study_all.sh

figure:
	$(PYTHON) scripts/make_figure.py --output-dir figures

metadata:
	$(PYTHON) scripts/validate_metadata.py

hygiene:
	$(PYTHON) scripts/scan_release.py

validate:
	PYTHONPATH=src $(PYTHON) scripts/run_release_validation.py

reproduce:
	bash scripts/reproduce_all.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	rm -rf build dist *.egg-info src/*.egg-info
