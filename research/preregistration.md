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
| SHA-256 | `dd6b39b457731f5506f4e6616331687563159615e51f2d085a075666809dbd41` |
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

None. (Any post-freeze change to the analysis plan must be logged here with
date, commit, and rationale, before evaluation results are interpreted.)
