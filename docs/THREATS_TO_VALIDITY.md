# Threats to Validity

This document is an honest, exhaustive enumeration of the known limitations of the
PerimeterFlow research design: the abstraction choices, the corruption and network
models, the estimation and control assumptions, and the statistical protocol. It is
written **before** any experiment is executed, so that it cannot be retro-fitted to
excuse inconvenient results. No empirical numbers appear here; every numeric result
field in this repository is `null` and every artifact carries `"status": "planned"`
until real simulation and replay runs produce and independently reproduce them.

## 1. Model Validity

- **Two-reservoir abstraction.** The metropolitan network is aggregated into a small
  number of reservoirs (a perimeter-controlled boundary pair on a grid topology), and
  the Macroscopic Fundamental Diagram (MFD) is applied per reservoir. This assumes
  near-homogeneous spatial distribution of vehicles within each reservoir
  (the "well-mixed" assumption). Real cities exhibit persistent spatial heterogeneity,
  and a reservoir-mean accumulation can mask localized gridlock that the reservoir
  average never approaches the jam threshold.
- **Idealized production curve.** The two-branch outflow model (loading branch,
  unloading branch scaled by a fixed hysteresis drop ratio) is a parsimonious
  idealization. Capacity drop dynamics in reality are stochastic, transient, and
  dependent on downstream queue interaction; the fixed branch ratio is a modeling
  convenience, not a measured universal constant.
- **Unimodal, car-only dynamics.** Buses, trucks, two-wheelers, pedestrians, and
  conflicting turning movements are not modeled. Passenger-car-equivalent effects are
  therefore outside the validity envelope of any conclusion drawn here.
- **Aggregate gating abstraction.** Perimeter control actuates a single dimensionless
  gate factor on boundary inflow rather than optimizing individual signal timings.
  The mapping from gate factor to feasible real-world signal plans is not modeled,
  and internal signal coordination effects are not captured.
- **Accumulation-based control.** The controller regulates reservoir accumulation
  only. It cannot observe or directly act on within-reservoir queue spillback, and it
  provides no formal stability guarantee under simultaneous saturation, delay, and
  model error; gridlock avoidance is measured, not proven.

## 2. Network Validity

- **Synthetic regular grid.** Experiments run on a synthetically generated regular
  grid with an explicit arterial/local edge classification. Regular Manhattan-type
  topologies differ systematically from irregular real-world street networks in block
  lengths, turning fractions, and intersection density. Transfer of quantitative
  conclusions to real networks is not established.
- **Arbitrary partitioning.** The boundary between the two reservoirs, and hence the
  perimeter location, is a design choice. Different partitionings may change both
  estimation difficulty and controllability; no sensitivity study is pre-registered.
- **Synthetic demand.** The demand profile is a deterministic hysteresis-shaped
  loading/unloading profile rather than an empirical origin-destination matrix. Peak
  shapes, temporal asymmetries, and demand stochasticity of real cities are only
  loosely represented.

## 3. Data Validity

- **Simulation-derived ground truth.** The "100% known ground truth" guarantee holds
  because trajectories are recorded from the simulator itself. Any bias in the
  simulator's car-following, lane-changing, and routing models is inherited by the
  experiments as unobservable ground-truth bias. Real deployments do not possess
  such ground truth.
- **pNEUMA validation is offline-only.** The naturalistic drone-trajectory dataset
  (downtown Athens) can only be used for open-loop replay estimation. Closed-loop
  perimeter actuation cannot be evaluated on recorded trajectories, so the control
  hypotheses (H4) are exclusively simulation-supported. This limitation is
  irreducible with present data.
- **Single-dataset external validity.** pNEUMA covers one city, a limited set of
  days, and specific collection conditions (daylight, weather, drone altitude and
  occlusion regimes). Generalization to other cities, sensor mixes, or adverse
  conditions is unverified.
- **Dataset availability and licensing.** `data/pneuma_subset/` is intentionally an
  empty placeholder: the subset is added only by a user who has obtained the dataset
  under its own distribution terms (see `DATA.md`). Any quantitative claim validated
  on pNEUMA must therefore be reproduced locally by the reader.

## 4. Estimation Validity

- **Penetration estimation depends on boundary loops.** Class-level penetration
  estimates are anchored by boundary detector counts. If boundary loop coverage or
  composition is itself biased (misclassification, partial instrumentation, detector
  drift), the inverse-penetration correction inherits and can amplify that bias.
  In deployments without full boundary instrumentation the correction quality
  degrades in ways the present protocol does not bound.
- **Penetration floor clipping.** The estimator floors class penetration at a small
  positive constant. Near and below that floor the estimator saturates; the behavior
  is conservative (it prevents division blow-ups) but systematically under-corrects
  at extremely low penetration.
- **Simplified corruption models.** GPS noise is injected as zero-mean Gaussian;
  multipath as isolated large-position outliers at a fixed probability; dropouts as
  Markovian bursts. Real corruption is spatially correlated, heavy-tailed, and
  infrastructure-dependent (urban canyons, tunnels, phone-based sampling gaps).
  Robustness claims are valid only inside these injected envelopes.
- **Quality gate false rejections.** The kinematic gate bounds speed and acceleration
  by urban-plausible constants. Legitimate harsh decelerations, stop-and-go
  oscillations, or map-matching artifacts near thresholds can be falsely rejected,
  inflating the rejection rate that in turn inflates observation covariance.
- **Window discretization.** Estimation proceeds in fixed-width time windows that
  assume approximate stationarity within each window. Fast transients at regime
  change are averaged, and window-edge segments are attributed to a single window.
- **Kalman filter assumptions.** The filter assumes Gaussian process and observation
  noise and uses a locally linearized outflow Jacobian. Robustness to MFD parameter
  misspecification and penetration estimation error is claimed only within the
  pre-registered misspecification envelopes; nothing outside those envelopes is
  established.

## 5. Control Validity

- **Model-based prediction inherits model error.** The Smith predictor rolls the
  possibly misspecified MFD model forward through the pipeline delay. The residual
  correction fed back from the delayed measurement uses a fixed blending gain that
  is a heuristic, not an optimized or proven-stable choice.
- **Idealized latency.** Pipeline delay is modeled as a constant integer multiple of
  the control window. Jitter, variable latency, packet loss, and out-of-order delivery
  are not modeled.
- **Baseline fairness.** The baseline PI controller is granted the same calibration
  budget as the proposed controller, tuned per delay regime on the calibration seeds.
  Nevertheless, if the tuning procedure converges differently for the two variants,
  the comparison may be biased in either direction; the tuning protocol itself is
  part of what is being tested.
- **No actuation friction.** Driver compliance, rerouting around gated boundaries,
  queue spillback across the perimeter, and feasible-set constraints on signal plans
  are not modeled. Closed-loop field behavior may be materially different.

## 6. Statistical and Inferential Validity

- **Residual optimism after partitioning.** The strict split between calibration
  seeds and evaluation seeds prevents seed-level overfitting, but hyperparameters are
  still selected within the same simulated environment; overfitting to the environment
  itself (its network, demand, and corruption generators) remains possible.
- **Limited power.** The evaluation set contains thirty seeds. Small true effects may
  be statistically undetectable; a null result must not be read as a demonstration of
  absence of effect.
- **Family of tests.** The pre-registered hypothesis family is corrected jointly via
  the Holm-Bonferroni step-down procedure. Any analysis outside this pre-registered
  family is exploratory by construction and will be labeled as such if reported.
- **Distribution-free but not assumption-free.** Wilcoxon signed-rank tests, Cliff's
  delta, and Hodges-Lehmann estimates assume paired, exchangeable differences;
  bootstrap confidence intervals inherit resampling variability at this sample size.
- **No practical-significance thresholds.** Effect sizes are reported as measured;
  no smallest-effect-of-interest is pre-registered, so readers must judge practical
  significance themselves.

## 7. Reproducibility Threats

- **Cross-platform floating point.** The deterministic core PRNG is integer-exact by
  construction, but the Box-Muller transform and filter arithmetic use
  floating-point transcendentals whose implementations differ across libm versions
  and CPU architectures. Cross-language parity is asserted to a fixed numerical
  tolerance by golden-vector tests; bitwise equality is not claimed.
- **Simulator and toolchain drift.** Simulator behavior can change between builds and
  configurations. Dependencies are pinned via a lockfile, and artifacts record
  provenance hashes of configuration and data, but byte-level reproducibility across
  environments is not guaranteed.
- **Human review remains necessary.** Schema validation, provenance hashing, CI
  parity checks, and the status lifecycle are mechanical honesty guards; they do not
  replace scientific review of a completed artifact before its status advances to a
  reviewed, reproduced state.

## 8. Status of Evidence

At the time of this writing, no experiment has been executed within this repository.
All numeric result fields across all artifacts are `null`, and all artifacts carry
`"status": "planned"`. Every statement in this document concerns design limitations,
not empirical findings; nothing here should be cited as a measurement of any kind.
