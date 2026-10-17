# Hypotheses → Artifacts → Report Map

Planned wiring between the pre-registered hypotheses and the report outputs.
**No results exist yet**: the sweep (Seeds 11–40) has not run, so every metric
below is `null`/`planned` per the honesty contract. This map defines what will be
extracted where — it must be finalized **before** the sweep runs.

Artifact fields below refer to `summary_table` rows in `results/*.json`
(schema: [`data/schemas/mfd_artifact.schema.json`](../data/schemas/mfd_artifact.schema.json)),
with `condition_id` encoding `<p>_<bias_mode>_delay<τ>_<variant>`, e.g.
`p05_uniform_delay0_G1_F1_C0`.

## Mapping

| Hypothesis | Claim (short) | Artifact field(s) | Contrasting conditions | Report output |
| --- | --- | --- | --- | --- |
| **H1** Spatial bias recovery | Stratified HT weighting anchored by boundary counts reduces accumulation bias vs. unstratified Edie under 4:1 corridor-biased sampling | `nrmse_median_pct`, `nrmse_iqr_pct` | `bias_mode=corridor_biased`, unstratified (`G0_F0_C0`) vs. stratified estimation (F1 variants) | [`tab:results`](../report/main.tex) |
| **H2** Stateful kinematic gating | Stateful sequential gate beats stateless/unfiltered on accuracy and false rejections under Gaussian noise + 3% multipath | `nrmse_median_pct`, `nrmse_iqr_pct` + gate-level rejection metrics *(see open item 1)* | `G1_F0_C0` vs. `G0_F0_C0` under noise conditions | `tab:results` |
| **H3** Hysteresis & misspecification robustness | Hysteresis PC-AKF (R_t scaled by ρ_reject) stays lower-NRMSE under ±20% MFD misspecification and ±30% penetration-estimate error | `nrmse_median_pct`, `nrmse_iqr_pct` on stress-test rows *(see open item 2)* | `G1_F1_C0` vs. static-gain Kalman / naive scaling under δ_MFD, δ_p̂ | ablation figure (`generate_ablation_figure`) |
| **H4** Latency-compensated control | Smith-PI beats normalized PI on Total Network Delay at τ_d ∈ {30 s, 60 s} | `tnd_median_veh_h`, `tnd_iqr_veh_h` | `delay_s ∈ {30, 60}`, `C0` vs. `C1` (same delay regime, independently tuned gains) | `tab:results` |

## Statistical inference (frozen)

Paired Hodges-Lehmann median difference (Δ̂_HL) with 95% bootstrap CI, Cliff's δ,
and Wilcoxon signed-rank with Holm-Bonferroni step-down adjustment (α = 0.05),
computed **exclusively on Seeds 11–40**. Negative/null/non-significant findings are
reported with identical prominence. See
[`docs/ANALYSIS_PLAN.md` §5](../docs/ANALYSIS_PLAN.md).

## Report pipeline

- `report/render_tex_macros.py` → `report/generated_metrics.tex` (zero manual numbers).
- `report/generate_figures.py::generate_ablation_figure` → ablation figure PDF under
  `report/figures/`.
- Paper-specific figures: scripts go in [`figures-src/`](./figures-src/README.md);
  rendered PDFs land in the gitignored `figures/`.

## Open items (resolve before the sweep)

1. **H2 gate metrics:** the smoke artifact's `summary_table` carries `nrmse_*` and
   `tnd_*` only. Confirm how false-rejection rate (and ρ_reject(t) traces) are
   represented in the artifact schema — extend `mfd_artifact.schema.json` and this
   map before running Seeds 11–40, never after.
2. **H3 stress rows:** confirm how δ_MFD / δ_p̂ are encoded in `condition_id` (or a
   separate field) so stress-test comparisons are extractable without re-parsing.
3. Confirm the exact stratified-vs-unstratified contrast set for H1 against the
   ablation matrix (`G0_F0_C0` vs. which F1 rows) and record it here.
