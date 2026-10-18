# Design & Mathematical Decisions

This document records the key technical and mathematical decisions behind
PerimeterFlow, the alternatives considered, and the rationale for the choices that
were made. It is written before execution, so it explains intent rather than
post-hoc justification of results.

## D1 — Mulberry32 as the cross-language deterministic PRNG

**Decision.** All stochasticity (probe sampling, GPS noise, dropout processes) is
drawn from a 32-bit Mulberry32 generator implemented identically in Python and in
TypeScript for the browser Web Worker.

**Rationale.**
- Mulberry32's state update is pure 32-bit integer arithmetic (`+`, XOR, shifts,
  multiply-and-keep-low-32). JavaScript's `Math.imul` and unsigned shift operators
  map these exactly, and Python replicates them with bitwise masking to 32 bits.
  No floating-point state crosses language boundaries.
- Box-Muller Gaussian draws use only `log`, `cos`, `sqrt`, with the first uniform
  clamped away from zero to avoid `log(0)`; the sequence of uniforms consumed per
  Gaussian is fixed, so both languages draw in the same order.
- Consequence: simulation runs on a server and interactive runs in a browser
  traverse identical random sequences. Golden parity vectors are exported and
  asserted to match between the two implementations to a tight numerical tolerance,
  guarding against silent drift.
- Alternatives rejected: language-native RNGs (no parity), PCG/xoshiro (superior
  statistical properties but wider 64/128-bit state that is not exactly portable
  across the JS number model).

## D2 — Stateful sequential quality gate

**Decision.** Probe pings are filtered sequentially against each vehicle's *last
accepted valid anchor* (time, position, speed), never against the previously
received ping.

**Rationale.**
- A stateless pairwise gate lets a single GPS multipath spike become the reference
  for the next observation, causing a cascade of false rejections and wiping out
  true travel-time information exactly when data is worst.
- With the anchor design, a rejected ping leaves the anchor untouched, so the
  next genuine observation is compared against known-good state and is preserved.
- Ordered decision precedence inside the gate: (1) spatial validity — NaN
  coordinates or map-snap distance beyond threshold are rejected first, so a
  positional outlier can never enter kinematic testing; (2) anchor (re)initialization
  — a first ping or a time gap beyond the reset threshold seeds a new anchor with a
  zero-duration, zero-distance segment (it contributes no travel time by design);
  (3) kinematic validity — computed speed and acceleration against the anchor must
  lie within urban-plausible bounds; backward time steps are rejected.
- The per-ping rejection rate emitted by the gate is the signal later reused to
  inflate observation covariance in the filter (see D4), tying data-quality
  degradation directly to estimation conservatism.

## D3 — Stratified Horvitz-Thompson / Edie estimator

**Decision.** Network-level density and flow are estimated by stratifying segments
into link classes (arterial vs local), accumulating gated travel time and distance
per class, dividing by a floor-protected class penetration estimate, normalizing by
class and total lane-kilometers, and anchoring class penetration to boundary
detector counts.

**Rationale.**
- Under corridor selection bias (probes over-representing arterials), a single
  unstratified inverse-penetration correction inherits the arterial over-weighting
  and produces a systematic positive accumulation bias. Stratification removes the
  differential exposure by weighting each class by its own penetration.
- Boundary-loop anchoring gives the penetration estimate an infrastructure-based
  reference rather than a self-referential probe-based one.
- The penetration floor prevents division blow-ups at extremely low penetration;
  the cost is conservative under-correction near the floor (documented in
  `THREATS_TO_VALIDITY.md`).
- Edie's generalized definitions are used so that time-based and distance-based
  traffic quantities are integrated consistently over the observation window.

**Stratified Penetration Identification ($\hat{p}_c$ anchoring).**
Class-specific penetration estimates $\hat{p}_c(t)$ with
$c \in \{\text{arterial}, \text{local}\}$ are anchored via *screenline loop
counts*: boundary detector stations cut the reservoir into screenlines, and the
observed loop volume crossing each screenline is divided by the gated probe
volume of the same class over the identical time window. This yields a
class-stratified penetration anchor that is *independent* of the probe-sampling
process itself (preventing self-referential estimation). Because the screenline
decomposition can only misattribute traffic between the two link classes — a
bound quantifiable from the loop density along the screenline — the robustness
stress factor $\delta_{\hat{p}} \in \{-30\%, 0\%, +30\%\}$ in Hypothesis $H_3$
directly upper-bounds any residual screenline decomposition error: it inflates
and deflates the anchored $\hat{p}_c(t)$ by 30%, covering the plausible range of
misattribution without requiring an explicit screenline re-estimation inside the
closed-loop runner.

**Nomenclature & Units.** Edie macroscopic flow $\hat{Q}(t)$ is reported in
$\text{veh/h}$ (converted via $\Delta t_h = \Delta t / 3600$), whereas the
discrete-time state-space mass-balance equation inside the PC-AKF and the
Smith-PI rollout operates in $\text{veh/s}$ ($Q_{\text{in}}(t)$ and $\Phi(N)$
in $\text{veh/s}$ multiplied by $\Delta t = 60\,\text{s}$). The full binding
table lives in `docs/ANALYSIS_PLAN.md` §5.1.

## D4 — Two-branch hysteresis physics-constrained adaptive Kalman filter

**Decision.** Accumulation is propagated by a mass-balance equation with a
two-branch outflow function: a loading branch, and an unloading branch with a fixed
reduced maximum that engages only when the accumulation estimate is decreasing while
still congested (above a fraction of critical accumulation). Observation covariance
is inflated dynamically by both penetration deficit and the gate rejection rate:
`R_t = R_base · (p_ref / max(p_eff, floor)) · exp(alpha_gate · rho_reject)`. The
outflow Jacobian is evaluated analytically for covariance propagation, the state is
clamped to the physical range `[0, N_jam]`, and the update is skipped entirely
(data strictly followed to prediction) under sensor blackout or unusable
observations.

**Rationale.**
- Congested recovery genuinely differs from loading in observed MFD behavior; a
  single-branch model underestimates outflow hysteresis and mis-times the gate.
  Engaging the unloading branch only under the declining-and-congested condition
  prevents the branch from flapping during free-flow oscillation.
- Covariance inflation makes the filter provably more skeptical exactly when
  evidence is weakest (low penetration, many rejected pings), which is the honest
  response; the exponential form keeps inflation smooth and bounded in practice.
- Skipping the update under blackout keeps the covariance propagation meaningful
  (a pure prediction step) instead of pretending the missing observation carried
  information.
- State clamping sacrifices mathematical elegance for physical validity: a filter
  that reports negative vehicles or super-jam accumulation would corrupt the
  downstream controller.

## D5 — Residual-corrected Smith-PI perimeter controller

**Decision.** The controller maintains (a) a ring buffer of past boundary inflows
and gate commands of length equal to the delay in steps, and (b) a ring buffer of
its own delayed model predictions. At each step it rolls the observed *delayed*
accumulation forward through the model across the buffered actuations, then applies
a residual correction blending the model's stale delayed prediction with the actual
delayed observation. The gate command is an incremental PI law on a dimensionless
normalized error with hard saturation to `[u_min, 1.0]`.

**Rationale.**
- A classic Smith predictor compensates known dead time by simulating the plant
  model forward; feeding back the model mismatch observed at the delayed time
  station (with a fixed blending gain, chosen conservatively at one half) corrects
  slow model drift without destabilizing the fast loop.
- Normalizing the error by critical accumulation makes the same gains meaningful
  across network sizes and demand regimes, and makes the controller's behavior
  invariant to rescaling of the MFD.
- Exact degeneracy requirement: with zero delay the rollout and residual machinery
  must reduce exactly to the plain normalized PI controller. This is asserted
  mathematically in tests, so the "Smith" structure is provably a strict
  generalization rather than a separate heuristic.
- Saturation clipping provides anti-windup behavior by construction, since the
  integral action is incremental and bounded by the clip.

## D6 — Strict seed partitioning (calibration vs evaluation)

**Decision.** Seeds `1..10` are reserved exclusively for calibration tasks (fitting
reference MFD curves, selecting the filter hyperparameter, tuning both controllers
per delay regime). Seeds `11..40` are frozen before any evaluation run and used
exclusively for final statistics.

**Rationale.**
- A single-seed or shared-seed workflow lets design choices leak into evaluation,
  turning every reported number into an optimistic upper bound. The partition makes
  the evaluation set genuinely unseen at parameter-selection time.
- Thirty paired evaluation seeds support the pre-registered non-parametric protocol
  (Wilcoxon signed-rank with Holm-Bonferroni correction, Hodges-Lehmann median
  differences with bootstrap intervals, Cliff's delta) without parametric
  distributional assumptions on simulation outputs, which are typically skewed and
  heavy-tailed.
- The freeze is enforceable procedurally: evaluation configs reference only the
  evaluation seed list, and artifacts record both seed partitions explicitly so any
  violation is visible in the provenance block.

## D7 — JSON Schema provenance with a status lifecycle

**Decision.** Every result artifact is a JSON document validated by a Draft
2020-12 schema that (a) requires a full provenance block — artifact and run
identifiers, git commit hash pattern, SHA-256 hashes of the exact configuration and
input data, UTC generation timestamp, mode, license, and both seed partitions — and
(b) defines an explicit status enum: `planned`, `running`, `results-unreviewed`,
`reproduced-in-ci`. All numeric result fields are typed as number-or-null.

**Rationale.**
- Null-permitting result fields let a pre-run artifact be fully valid while
  containing *zero* numbers: the repository's honesty contract is machine-checked
  rather than aspirational. An artifact cannot exist in a valid state with
  invented metrics and a `planned` status.
- Content hashes of configuration and data make an artifact reproducible in
  principle: given the hash, the exact inputs that produced the numbers are
  identifiable, and any mutation of inputs invalidates old artifacts.
- The status lifecycle encodes the review pipeline: numbers exist first as
  unreviewed, and only become citable after independent reproduction in CI.
  Schema tests assert both that clean planned artifacts validate and that
  provenance-missing payloads are rejected.

## D8 — Virtual uv project with src-layout imports

**Decision.** The Python project is a *virtual* uv project (`package = false`):
dependencies are managed and locked, but the package itself is never built or
installed. Pytest is configured to import the package directly from `src/` via
`pythonpath`, and the dev dependency group carries test, property-testing, schema,
and lint tooling.

**Rationale.**
- A research codebase of scripts and libraries does not need an installable
  distribution; skipping the build removes an entire class of packaging failures
  and keeps the workflow to `uv sync` + `uv run`.
- The `src/` layout prevents the common failure mode where tests silently import
  the working-directory copy instead of the installed package; with
  `pythonpath = ["src"]` there is exactly one import path under test.
- No version field exists anywhere by project rule; since the project is not built
  or distributed, no version metadata is required.

## D9 — YAML configuration as the CLI contract

**Decision.** All experiment entry points consume the same YAML field vocabulary:
`seeds`, `penetration_rate`, `bias_mode`, `delay_s`, `episode_length_s`,
`dt_window_s`, and explicit misspecification factors for the MFD critical
accumulation, MFD maximum outflow, and penetration estimation. The three shipped
configs (calibration seeds, evaluation seeds, small smoke-test) differ only in
values, not in shape.

**Rationale.**
- A single field vocabulary across configs means the calibration, evaluation, and
  smoke-test paths exercise identical code paths, so the smoke test is a genuine
  (if short) dry run of the experiment machinery rather than a parallel toy path.
- Misspecification factors are first-class fields, not hidden constants, so the
  pre-registered robustness envelopes (H3) are visible and auditable in
  configuration.
- The smoke-test config is explicitly labeled as such: reduced episode length, a
  couple of seeds drawn only from the calibration partition, zero delay, and no
  misspecification. It exists to verify plumbing on a laptop, never to support
  empirical claims — evaluation claims require the full evaluation config.

## D10 — Fractional sub-window latency rollout ($\theta$ decomposition)

**Decision.** Telemetry pipeline latency $\tau_d$ is decomposed into an integer
window count $d_{\text{int}} = \lfloor \tau_d / \Delta t \rfloor$ and a
sub-window fraction $\theta = (\tau_d \bmod \Delta t)/\Delta t \in [0, 1)$
instead of flooring to $d = \lfloor \tau_d / \Delta t \rfloor$ alone. The
fractional decomposition applies to three mechanisms, mirrored bit-for-bit in
both Python and TypeScript: (i) the fractionally delayed telemetry observation
$z_{\text{del}}(t) = (1-\theta) z(t-d_{\text{int}}) + \theta z(t-d_{\text{int}}-1)$
delivered identically to the baseline PI (C0) and the Smith-PI (C1); (ii) a
fractional Euler step of duration $\theta \Delta t$ over the most recent
actuation $(q_{t-1}, u_{t-1})$, appended after the $d_{\text{int}}$ full-step
rollout; and (iii) the residual correction blended against the fractional
interpolation of the stored model-prediction buffer,
$N_{\text{model,del}}(t) = (1-\theta) P(t-d_{\text{int}}) + \theta P(t-d_{\text{int}}-1)$,
with degenerate fallback to the head of the history when fewer than two
predictions are available.

**Rationale.**
- Under pure flooring, $\tau_d = 30\,\text{s}$ with $\Delta t = 60\,\text{s}$
  collapses to $d = 0$, making the half-window latency regime mathematically
  indistinguishable from zero delay and rendering the H3/H4 stress levels
  degenerate. The fractional decomposition preserves the pre-registered
  $\tau_d \in \{0\,\text{s}, 30\,\text{s}, 60\,\text{s}\}$ levels as genuinely
  distinct control regimes.
- Exact degeneracy is retained at both endpoints: $\tau_d = 0$
  ($d_{\text{int}} = 0$, $\theta = 0$) collapses bit-for-bit to the tuned
  normalized PI baseline, and $\tau_d = \Delta t$ ($d_{\text{int}} = 1$,
  $\theta = 0$) reproduces the legacy integer-step rollout exactly. Both
  invariants are locked by golden parity vectors and asserted in unit tests to
  $10^{-9}$ tolerance.
- The fractionally delayed observation is consumed identically by C0 and C1, so
  the experimental contrast isolates the compensation mechanism (rollout +
  residual correction) from the telemetry pathway itself.
