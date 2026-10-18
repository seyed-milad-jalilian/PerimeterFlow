# Pre-registration Record

## Status

- The statistical analysis plan is **frozen** in [`docs/ANALYSIS_PLAN.md`](../docs/ANALYSIS_PLAN.md):
  hypotheses H1–H4, strict seed partitioning (calibration 1–10 / evaluation 11–40),
  experimental factors and ablation matrix, primary metrics, and the non-parametric
  inference protocol.
- No external registry deposit has been made yet (**registry TBD**). This file
  records the freeze evidence so that the plan's immutability is verifiable from
  this commit onward, regardless of registry choice.

## Freeze evidence

| Field | Value |
| --- | --- |
| Frozen plan | `docs/ANALYSIS_PLAN.md` |
| SHA-256 | `87c30a046e9cef0572a842774857230ce136b5d041edd5387b4d997c5d1201dd` |
| Verified at commit | `99acd494c34dd5006c316b5bec9f00d2b2a5de9f` |
| Verified on (UTC) | 2026-10-16 |
| Computed with | PowerShell `Get-FileHash -Algorithm SHA256` |

### Re-verify

```bash
git rev-parse HEAD
sha256sum docs/ANALYSIS_PLAN.md          # POSIX
Get-FileHash docs\ANALYSIS_PLAN.md -Algorithm SHA256   # PowerShell
```

The hash must match at the recorded commit. If the plan file changes after the
evaluation sweep has started, the change must be documented below as an
amendment — never silently.

## Registry deposit (to be completed)

- Registry:
- Deposit timestamp (UTC):
- Deposit DOI / URL:
- Deposited snapshot hash:

## Amendments

1. **2026-10-18 — Pre-sweep amendment (before any evaluation seed is executed).**
   Section **5.1 "Nomenclature & Units"** was added to `docs/ANALYSIS_PLAN.md`,
   documenting the binding unit conventions (reported Edie macroscopic flow
   $\hat{Q}(t)$ in $\text{veh/h}$ via $\Delta t_h = \Delta t/3600$; state-space
   mass-balance quantities $Q_{\text{in}}(t)$, $\Phi(N)$ in $\text{veh/s}$
   multiplied by $\Delta t = 60\,\text{s}$). Rationale: unit-conversion
   documentation supporting Decision Records D3 and D10 in `docs/DECISIONS.md`
   and the fractional sub-window latency rollout. No hypothesis, seed
   partition, experimental factor, metric, or inference rule was modified.
   **The SHA-256 in the Freeze evidence table above and in the Research
   Proposal header must be re-computed against the amended file before the
   first evaluation seed (`Seed 11`) is run** (`sha256sum
   docs/ANALYSIS_PLAN.md`). Any post-freeze change to the analysis plan must be
   logged here with date, commit, and rationale, before evaluation results are
   interpreted.
