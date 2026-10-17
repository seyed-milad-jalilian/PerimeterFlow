# Paper Figure Scripts

**Tracked** home for scripts that generate *paper-specific* figures
(`research/paper/draft-paper.md`). Rendered output goes to the gitignored
`research/figures/`.

Scope rules:

- Report figures stay in [`report/generate_figures.py`](../../report/generate_figures.py)
  (`generate_ablation_figure` et al.) — do not fork them here.
- Scripts here must read result artifacts (`results/*.json`) as input and derive
  every number from them — zero manual numbers, same rule as `report/generated_metrics.tex`.
- Deterministic output: fixed seeds/ordering, no wall-clock-dependent content.
- Until the evaluation sweep (Seeds 11–40) has run, any figure generated from
  smoke artifacts (`small_repro.json`, `ensemble.json` in plumbing mode) is a
  layout check only and must never be cited or shown as a result.
