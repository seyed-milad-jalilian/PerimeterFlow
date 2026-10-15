.PHONY: init-planned test parity reproduce-small calibrate sweep report clean

PYTHON := uv run python
PYTEST := uv run pytest

init-planned:
	$(PYTHON) -m perimeterflow.cli init-planned --config configs/evaluate_seeds.yaml --output results/ensemble.json
	$(PYTHON) report/render_tex_macros.py results/ensemble.json report/generated_metrics.tex

test: init-planned
	$(PYTEST) tests/ -v

parity:
	$(PYTHON) -m perimeterflow.cli export-golden data/golden/parity_vectors.json
	cd web_worker && npx vitest run

reproduce-small:
	$(PYTHON) -m perimeterflow.cli sweep --config configs/small_repro.yaml --output results/small_repro.json

calibrate:
	$(PYTHON) -m perimeterflow.cli calibrate --config configs/calibrate_seeds.yaml --output results/calibrated_params.json

sweep: calibrate
	$(PYTHON) -m perimeterflow.cli sweep --config configs/evaluate_seeds.yaml --params results/calibrated_params.json --output results/ensemble.json
	$(PYTHON) report/render_tex_macros.py results/ensemble.json report/generated_metrics.tex
	$(PYTHON) report/generate_figures.py results/ensemble.json report/figures

report:
	$(PYTHON) report/render_tex_macros.py results/ensemble.json report/generated_metrics.tex
	cd report && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex

network:
	$(PYTHON) -m perimeterflow.cli generate-network --output results/network

clean:
	rm -rf build/ dist/ *.egg-info report/*.aux report/*.log report/*.out report/figures
