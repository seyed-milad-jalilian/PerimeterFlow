# Research Documentation

Research-facing documentation for PerimeterFlow: pre-registration, reproducibility,
hypothesis-to-artifact mapping, and manuscript materials.

**Status: pre-sweep.** The pre-registered evaluation sweep (Seeds 11–40) has **not**
been executed. Every metric referenced in these documents is `null` / `planned`
until the frozen protocol runs. See the honesty contract in the root
[`README.md`](../README.md#12-honesty-contract-artifacts-and-status-lifecycle).

## Layout

| Path | Purpose |
| --- | --- |
| `preregistration.md` | Freeze evidence (SHA-256, commit) for the frozen analysis plan; registry deposit record |
| `reproducibility.md` | Three-tier protocol, seed firewall, environment freeze, provenance checklist |
| `hypotheses-map.md` | Planned wiring: H1–H4 → artifact fields → report tables/figures |
| `threats-to-validity.md` | Full validity-threats analysis for the manuscript |
| `research-proposal.md` | Research proposal narrative |
| `data-dictionary.md` | Dataset and artifact field documentation |
| `bibliography.bib` | Shared BibTeX bibliography |
| `ethics.md` | Data governance and ethics statement |
| `paper/draft-paper.md` | Manuscript draft |
| `adr/` | Architecture/analysis decision records |
| `figures-src/` | **Tracked** scripts that generate paper figures |
| `figures/` | Generated figures — **gitignored** |
| `supplementary/` | Supplementary materials — **gitignored** |

## Canonical sources (do not duplicate here)

These live elsewhere and remain the single source of truth; this folder links,
never forks:

- [`docs/ANALYSIS_PLAN.md`](../docs/ANALYSIS_PLAN.md) — frozen pre-registered protocol (H1–H4, seeds, factors, metrics, inference)
- [`docs/DECISIONS.md`](../docs/DECISIONS.md) — design rationale D1–D9
- [`docs/THREATS_TO_VALIDITY.md`](../docs/THREATS_TO_VALIDITY.md) — canonical threats analysis
- [`DATA.md`](../DATA.md) — external data licenses and citations (Amsterdam trajectories)
- [`CITATION.cff`](../CITATION.cff) — citation metadata for the whole project
- [`data/schemas/mfd_artifact.schema.json`](../data/schemas/mfd_artifact.schema.json) — result artifact schema
- [`report/`](../report/) — LaTeX report pipeline (`main.tex`, `generated_metrics.tex`, `generate_figures.py`)

`research/threats-to-validity.md` and `research/preregistration.md` are
manuscript-facing extensions of the canonical docs and must reference, not copy,
their content.
