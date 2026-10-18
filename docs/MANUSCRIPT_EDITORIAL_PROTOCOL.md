# Manuscript Editorial & Scientific Reporting Protocol

**Version:** 1.0
**Scope:** All journal-facing manuscripts generated from this repository
(*Transportation Research Part C: Emerging Technologies*, *Transportation
Research Part B: Methodological*, *IEEE Transactions on Intelligent
Transportation Systems*, *Communications in Transportation Research*).

---

## 1. Purpose

This protocol defines the formal scientific reporting and reproducibility
standard that every manuscript produced from the PerimeterFlow repository must
satisfy before submission. It exists to guarantee that every quantitative
claim in a manuscript is mechanically traceable to a pre-registered analysis
plan, a versioned code artifact, and a machine-verified result artifact — and
that the manuscript text contains **no manually transcribed numbers**.

---

## 2. Zero-Manual-Number Macro Injection

**Rule M1 —** Every numeric result in a manuscript (metric values, seed
counts, confidence intervals, effect sizes, software versions, artifact
identifiers) must be injected via the auto-generated macro file:

```latex
\input{generated_metrics.tex}
```

**Rule M2 —** No metric may be typed by hand into manuscript prose or tables.
Every macro used must be defined in `report/generated_metrics.tex`, which is
produced exclusively by `report/render_tex_macros.py` from the validated
result artifact (`results/ensemble.json`).

**Rule M3 —** If a required metric is missing from the macro file (e.g., the
sweep has not yet been run), the manuscript must show the macro's pending
placeholder (`\texttt{[PENDING SWEEP]}`) rather than a substituted number.

**Rule M4 —** The rendering script must fail loudly (non-zero exit) if the
underlying artifact fails schema validation (`data/schemas/mfd_artifact.schema.json`)
or if its `status` is not `reproduced-in-ci`.

---

## 3. Bibliography Locking

**Rule B1 —** The single bibliography source of truth for all manuscripts is
`report/bibliography.bib`. Manual inline `\bibitem` lists are permitted only
inside `report/main.tex` (the IEEE single-file draft) and must be regenerated
from `report/bibliography.bib` whenever either source changes.

**Rule B2 —** Every reference cited in any manuscript must exist in
`report/bibliography.bib` and must also be recorded in Section 14 (References)
of the pre-registered proposal (`research/research-proposal.md`). The two
lists are cross-checked before submission.

**Rule B3 —** Conference papers or working papers without a confirmed
publisher DOI must not carry speculative DOI URLs. arXiv preprints are cited
by their arXiv identifier, not by a `10.48550/arXiv.*` DOI URL, so that
automated Crossref screening at Elsevier/IEEE passes with 100% validity.

---

## 4. Terminology Preservation

**Rule T1 —** Standard Macroscopic Fundamental Diagram (MFD) and traffic
control terminology must be used exactly as in the primary literature:
*MFD*, *perimeter control*, *gating*, *stratified Horvitz–Thompson Edie
estimator*, *physics-constrained adaptive Kalman filter (PC-AKF)*,
*residual-corrected Smith-PI controller*, *Total Network Delay (TND)*,
*accumulation*, *production*. No synonym-swapping, paraphrase inflation, or
"humanizing" rewording of established technical terms is permitted.

**Rule T2 —** Units follow the binding nomenclature table in
`docs/ANALYSIS_PLAN.md` §5.1: reported Edie macroscopic flow $\hat{Q}(t)$ in
veh/h ($\Delta t_h = \Delta t / 3600$); the discrete-time state-space
mass-balance inside the PC-AKF and Smith-PI rollout in veh/s
($Q_{\text{in}}(t)$, $\Phi(N)$ multiplied by $\Delta t = 60$ s).

---

## 5. Journal Compliance Matrix

| Venue | LaTeX class | Constraints |
| :--- | :--- | :--- |
| *Transportation Research Part C / Part B* (Elsevier) | `cas-dc` (`report/manuscript_elsevier.tex`) | Elsevier declaration block mandatory (CRediT, Competing Interests, Data & Code Availability, Declaration of Generative AI); structured or unstructured abstract ≤ 250 words; continuous line numbering for review. |
| *IEEE Transactions on Intelligent Transportation Systems* | `IEEEtran` (`report/main.tex`) | Two-column `IEEEtran`; `thebibliography` acceptable for the internal draft, BibTeX for submission; IEEE breadth requirement: at least one non-traffic-sphere related-work paragraph. |
| *Communications in Transportation Research* | `cas-dc` variant | **12-page hard limit** (references excluded); a full replication package (code + configs + result artifacts + golden parity vectors) must accompany the submission. |

---

## 6. Reproducibility & Provenance

**Rule R1 —** Every manuscript must state the artifact Git commit
(`\ArtifactGitSHA`) and artifact status (`\ArtifactStatus`) at submission
time, and must reference the pre-registered plan
(`docs/ANALYSIS_PLAN.md`, SHA-256 verified in Git provenance).

**Rule R2 —** The seed firewall (calibration seeds 1–10 vs. evaluation seeds
11–40) must be described verbatim in the Experimental Protocol section of
every manuscript; no evaluation seed may appear in calibration results.

**Rule R3 —** The Python ↔ TypeScript ($\le 10^{-9}$) parity harness must be
cited as the independent client-side verification path for every reported
number.

**Rule R4 —** The Amsterdam NDW validation scope must be stated honestly:
historical trajectory replay only, with
`closed_loop_actuation_supported = False` (closed-loop perimeter actuation
cannot be counterfactually exercised on offline logs).

---

## 7. Ethical Declarations (COPE / Elsevier)

Every Elsevier-class manuscript (`cas-dc`) must contain the following
declaration sections, completed without placeholder text at submission:

1. **CRediT authorship contribution statement** — using the 14 CRediT roles.
2. **Declaration of competing interest** — all financial and personal
   relationships with other people or organizations that could inappropriately
   influence the work must be disclosed, or absence declared.
3. **Data and code availability** — repository URL, MIT license, artifact
   commit hash, and the location of every generated artifact.
4. **Declaration of generative AI in the writing process** — if generative AI
   tooling contributed to drafting, code development, or figure production,
   the assistance must be declared per the publisher's policy (what tool, for
   which purpose, under which human verification), in line with COPE
   transparency guidance. Where no generative AI assistance was used, an
   explicit negative declaration is required.

**Rule E1 —** Declarations are part of the compiled manuscript; a build that
omits any declaration section is considered failing.

---

## 8. Submission Gate

A manuscript may leave the repository only when all of the following hold:

- `make report` (IEEE) and the Elsevier build both compile without warnings
  about undefined macros or missing citations.
- `report/generated_metrics.tex` regenerates byte-identically from the
  current, schema-valid artifact.
- The pre-registration protocol freeze hash matches the current
  `docs/ANALYSIS_PLAN.md` SHA-256.
- All Section 7 declarations are present and non-placeholder.
