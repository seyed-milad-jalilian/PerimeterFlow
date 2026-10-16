# PerimeterFlow: Bias-Aware MFD State Estimation and Latency-Compensated Perimeter Control

## Research Question
To what extent do sparse probe penetration ($1\% \le p \le 10\%$), topological arterial corridor bias ($4:1$), GPS multipath outliers, Markovian burst dropouts, and cloud pipeline latency ($\tau_d \in \{0\text{s}, 30\text{s}, 60\text{s}\}$) degrade Macroscopic Fundamental Diagram (MFD) accumulation estimation and feedback perimeter gating, and what is the isolated contribution of each defensive layer?

## Architecture & Methodology
1. **Stateful Anchor-Preserving Kinematic Quality Gate (`src/perimeterflow/quality_gate.py`):** Evaluates velocity and acceleration strictly against the last accepted valid ping per vehicle, preventing isolated GPS multipath jumps from invalidating subsequent valid observations.
2. **Stratified Link-Class Horvitz-Thompson Edie Estimator (`src/perimeterflow/estimators.py`):** Corrects spatial selection bias across arterial corridors and local streets using class length scaling and boundary detector anchor counts.
3. **Two-Branch Hysteresis PC-AKF (`src/perimeterflow/estimators.py`):** Distinguishes loading vs. unloading network production capacity and dynamically inflates observation noise covariance $R_t$ via the gate rejection rate $\rho_{\text{reject}}(t)$.
4. **Residual-Corrected Smith-PI Controller (`src/perimeterflow/controllers.py`):** Compensates telemetry pipeline delay via forward MFD conservation rollout over past gating actions, reducing strictly to a normalized PI controller at $\tau_d = 0\text{s}$.

## Three-Tier Reproducibility Protocol
- **Tier 1 (Laptop Quick Verification, < 5 min):**
  ```bash
  make test
  make parity
  make reproduce-small
  ```
- **Tier 2 (Full Pre-Registered Calibration & 30-Seed Evaluation Sweep):**
  ```bash
  make calibrate
  make sweep
  make report
  ```
- **Tier 3 (Cloud-Native Kubernetes `k3s` Parallel IndexedJob):**
  ```bash
  kubectl apply -f deploy/k8s-indexed-job.yaml
  ```

## License
Code and simulation manifests are licensed under MIT (`CITATION.cff`). External validation dataset metadata follows `DATA.md`.
