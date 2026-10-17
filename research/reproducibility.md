# Reproducibility Protocol

Research-facing record of the reproducibility protocol. The executable source of
truth is the [`Makefile`](../Makefile); tier overview lives in
[`README.md` §7](../README.md#7-quick-start-and-three-tier-reproducibility).

## Three tiers

1. **Tier 1 — Laptop, < 5 min:** `make test` (pytest + Hypothesis), `make parity`
   (Python ↔ TypeScript parity ≤ 1e-9 via golden vectors), `make reproduce-small`
   (2 calibration seeds through the closed loop — plumbing only, **never citable**).
2. **Tier 2 — Full pre-registered protocol:** `make calibrate` (3×3 (Kp, Ki) grid on
   Seeds 1–10 only; gains frozen before any evaluation episode) → `make sweep`
   (30 held-out Seeds 11–40 × 5 ablation variants) → `make report` (auto-generated
   LaTeX macros, zero manual numbers, ablation figure, IEEE two-pass PDF).
3. **Tier 3 — Cloud-native k3s parallel sweep:** same protocol, parallelized; see
   [`README.md` §9](../README.md#9-cloud-native-deployment-tier-3) and `deploy/`.

## Seed firewall (non-negotiable)

Per [`docs/ANALYSIS_PLAN.md` §3](../docs/ANALYSIS_PLAN.md):

- **Calibration, Seeds 1–10:** fit reference MFD curves, select gate hyperparameter
  α_gate, tune (Kp, Ki) for PI and Smith-PI. Gains frozen before evaluation.
- **Evaluation, Seeds 11–40:** held out strictly. All statistical tests, tables,
  and figures are computed **exclusively** from these 30 seeds.
- **Smoke firewall:** any `make reproduce-small` output (e.g. `results/small_repro.json`,
  which runs `evaluation_seeds = [1, 2]`) verifies plumbing only and must never
  appear in any table, figure, or claim.

## Environment freeze

To be recorded in the sweep run's artifacts and completed here when the sweep runs:

| Component | Version / Source |
| --- | --- |
| Python | ≥ 3.11 (3.12 in CI and Docker), locked by [`uv.lock`](../uv.lock) |
| Node.js / TypeScript toolchain | ≥ 22, per `package.json` (parity suite, vitest) |
| SUMO / TraCI | *(fill at sweep time — `sumo --version`)* |
| LaTeX distribution | *(fill at report time)* |
| Sweep git SHA | *(fill — must equal `meta.git_sha` in every artifact)* |
| Determinism gate | Python ↔ TypeScript parity ≤ 1e-9 (`make parity`) |

## Artifact provenance

Every result artifact (`results/*.json`) is a JSON document validated against
[`data/schemas/mfd_artifact.schema.json`](../data/schemas/mfd_artifact.schema.json)
and carries in `meta`:

- `artifact_id`, `run_id`, `generated_at_utc`
- `git_sha`, `config_sha256`, `data_sha256` — code/config/data provenance
- `status` — lifecycle state (`planned` → …; metrics are strictly `null` until the
  corresponding run has executed)
- `calibration_seeds`, `evaluation_seeds` — the seed firewall made machine-checkable
- `mode`, `license`

## Pre-sweep checklist

1. `make parity` green (≤ 1e-9).
2. All shipped artifacts carry `"status": "planned"` with `null` metrics.
3. SUMO/TraCI and LaTeX versions recorded above and in the run config.
4. Frozen gains from `make calibrate` committed before any Seed 11–40 episode.
5. `meta.evaluation_seeds` of every sweep artifact ⊆ {11..40}.
