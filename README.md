# PerimeterFlow

## The Scientific Question

To what extent do sparse probe penetration (1%–10%), topological corridor selection bias, GPS multipath outliers, burst dropouts, and telemetry pipeline latency (τd ∈ {0 s, 30 s, 60 s}) degrade MFD state estimation and feedback perimeter control — and what is the isolated contribution of each defensive layer (stateful kinematic gating, stratified Horvitz-Thompson estimation with hysteresis PC-AKF, and residual-corrected Smith-PI control)?

The hypotheses (H1–H4), the strict calibration/evaluation seed partition (seeds 1–10 vs. 11–40), and the non-parametric inference protocol (paired Hodges-Lehmann, Cliff's delta, Wilcoxon signed-rank with Holm-Bonferroni correction) are **pre-registered** in [`docs/ANALYSIS_PLAN.md`](docs/ANALYSIS_PLAN.md) before any execution.

## System Architecture

```
[SUMO replay / pNEUMA] ──► [4:1 arterial probe bias + GPS noise + 3% spikes + burst dropouts]
                                    │
                                    ▼
              [Stateful kinematic quality gate (anchor-based, sequential)]
                                    │
                                    ▼
              [Stratified Horvitz-Thompson Edie estimator]
                                    │
                                    ▼
              [Two-branch Hysteresis PC-AKF (R_t inflated by ρ_reject(t))]
                                    │
                                    ▼
              [Residual-corrected Smith-PI perimeter controller]
                                    │
                                    ▼
              [Schema-validated JSON artifact + automated IEEE report]
```

Determinism guarantee: the `Mulberry32` 32-bit PRNG is implemented bit-identically in Python (`src/perimeterflow/prng.py`) and TypeScript (`web_worker/mfd_worker.ts`); golden parity vectors must agree to 1e-9 (`make parity`).

## Integrity Rules

1. **No fabricated numbers.** Until real episodes run, every exported artifact carries `"status": "planned"` with all metric fields `null`. Sweeps emit `"results-unreviewed"`; only CI-reproduced reruns promote to `"reproduced-in-ci"`.
2. **Known ground truth.** The two-reservoir replay engine integrates accumulation from known inflows/outflows, so N(t) is 100% known and every estimator error is exactly measurable.
3. **Frozen evaluation partition.** All gains and hyperparameters are tuned exclusively on seeds 1–10; seeds 11–40 are touched only by `make sweep`.
4. **No manual numbers in the report.** Every metric in `report/main.tex` is injected via LaTeX macros generated from `results/ensemble.json` (`report/render_tex_macros.py`), rendering `[PENDING SWEEP]` when nothing has run.

## Three-Tier Reproduction

Tier 1 — laptop smoke run (minutes, plumbing check only, never for claims):

```bash
make reproduce-small
```

Tier 2 — containerized full sweep (calibrate on seeds 1–10, evaluate on seeds 11–40):

```bash
docker build -f deploy/Dockerfile -t perimeterflow .
docker run --rm -v "$PWD/results:/out" perimeterflow \
  calibrate --config configs/calibrate_seeds.yaml --output /out/calibrated_params.json
docker run --rm -v "$PWD/results:/out" perimeterflow \
  sweep --config configs/evaluate_seeds.yaml --params /out/calibrated_params.json --output /out/ensemble.json
```

Tier 3 — k3s IndexedJob, 30 evaluation seeds in parallel (4 pods, 2 Gi limit each):

```bash
kubectl apply -f deploy/k8s-indexed-job.yaml
```

Local automation entry points: `make test`, `make parity`, `make network`, `make sweep`, `make report`.

## Data

pNEUMA (naturalistic drone trajectories of Athens) is used only for offline estimation validation (`validate-pneuma`). Licenses, access procedure, and citations: [`DATA.md`](DATA.md).

## Limitations

See [`docs/THREATS_TO_VALIDITY.md`](docs/THREATS_TO_VALIDITY.md). Notably: closed-loop gating cannot be actuated on offline naturalistic logs; boundary loop detectors remain necessary to calibrate class penetration rates; the aggregate replay engine shares the MFD functional form with the filter model (deliberately exercised under ±20% misspecification, but it is not microsimulation).

## Citation

[`CITATION.cff`](CITATION.cff).
