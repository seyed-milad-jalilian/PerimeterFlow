.PHONY: init-planned test parity reproduce-small calibrate sweep report clean

PYTHON := uv run python
PYTEST := uv run pytest

init-planned:
	$(PYTHON) -c "from pathlib import Path; from perimeterflow.stats_eval import write_planned_skeleton_artifact; write_planned_skeleton_artifact(Path('results/ensemble.json'), Path('configs/evaluate_seeds.yaml'))"
	$(PYTHON) report/render_tex_macros.py

test: init-planned
	$(PYTEST) tests/ -v

parity:
	$(PYTHON) -m perimeterflow.cli --export-golden data/golden/parity_vectors.json
	npx vitest run web_worker/parity.test.ts

reproduce-small:
	$(PYTHON) -m perimeterflow.cli --config configs/small_repro.yaml --output results/small_repro.json

calibrate:
	$(PYTHON) -m perimeterflow.cli --config configs/calibrate_seeds.yaml --mode calibrate --output results/calibrated_params.json

sweep:
	$(PYTHON) -m perimeterflow.cli --config configs/evaluate_seeds.yaml --params results/calibrated_params.json --output results/ensemble.json
	$(PYTHON) report/render_tex_macros.py
	$(PYTHON) report/generate_figures.py

report:
	$(PYTHON) report/render_tex_macros.py
	$(PYTHON) report/generate_figures.py
	cd report && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex

clean:
	rm -rf build/ dist/ *.egg-info report/*.aux report/*.log report/*.out
