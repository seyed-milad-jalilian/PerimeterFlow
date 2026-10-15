# Pre-Registered Research & Statistical Analysis Plan

## 1. Research Question
To what extent do sparse probe penetration ($1\% \le p \le 10\%$), topological corridor bias, GPS multipath outliers, burst dropouts, and telemetry pipeline latency ($\tau_d \in \{0\text{s}, 30\text{s}, 60\text{s}\}$) degrade MFD state estimation and feedback perimeter control, and what is the isolated contribution of each defensive layer (stateful kinematic gating, stratified Horvitz-Thompson estimation with hysteresis PC-AKF, and residual-corrected Smith-PI control)?

## 2. Pre-Registered Hypotheses
- **H1 (Spatial Bias Recovery):** Under non-uniform probe sampling (arterial links having $4\times$ higher probe penetration than local streets at fleet-wide $p \le 5\%$), unstratified Edie estimation exhibits systematic positive bias in accumulation. Stratified link-class Horvitz-Thompson weighting anchored by boundary detector counts significantly reduces accumulation $\text{NRMSE}(N)$.
- **H2 (Stateful Kinematic Gating):** Under combined Gaussian GPS noise and $3\%$ multipath spikes, a stateful sequential quality gate (evaluating kinematics strictly against the last accepted valid ping per vehicle) achieves lower $\text{NRMSE}(N)$ and lower false-rejection rates than stateless pairwise differencing or unfiltered estimation.
- **H3 (Hysteresis & Model-Misspecification Robustness):** A two-branch hysteresis PC-AKF that scales observation noise covariance $R_t$ via gate rejection rate $\rho_{\text{reject}}(t)$ maintains lower $\text{NRMSE}(N)$ than static-gain Kalman filtering and naive scaling, even when reference MFD capacity parameters ($N_{\text{crit}}, M_{\text{max}}$) are misspecified by $\pm 20\%$ and class penetration estimates $\hat{p}_c$ err by $\pm 30\%$.
- **H4 (Latency-Compensated Perimeter Control):** Under telemetry pipeline delays of $\tau_d \in \{30\text{s}, 60\text{s}\}$, a residual-corrected Smith-PI perimeter controller achieves lower Total Network Delay ($\text{TND}$, in $\text{veh}\cdot\text{h}$) than a baseline normalized PI controller whose gains $(K_p, K_i)$ are independently tuned for the exact same delay regime.

## 3. Strict Partitioning of Seeds
- **Calibration Set (`Seeds 1..10`, $n_{\text{cal}} = 10$):** Used strictly to fit baseline reference MFD curves, select filter hyperparameter $\alpha_{\text{gate}}$, and tune $(K_p, K_i)$ gains for PI and Smith-PI controllers.
- **Evaluation Set (`Seeds 11..40`, $n_{\text{eval}} = 30$):** Held out strictly for final evaluation. All parameters are frozen prior to running `Seeds 11..40`. Statistical tests, tables, and figures are computed exclusively from these 30 evaluation seeds.

## 4. Experimental Factors & Ablation Matrix
- **Fleet Penetration ($p$):** $\{0.01, 0.02, 0.05, 0.10\}$
- **Spatial Bias Regime:** `uniform` ($1:1$ arterial-to-local) vs. `corridor_biased` ($4:1$ arterial-to-local)
- **Telemetry Pipeline Delay ($\tau_d$):** $\{0\text{s}, 30\text{s}, 60\text{s}\}$
- **Ablation Variants ($2 \times 2 \times 2$ factorial on estimation and control):**
  1. `G0_F0_C0`: Unfiltered Edie + No Filter + Baseline Tuned PI
  2. `G1_F0_C0`: Stateful Gate + No Filter + Baseline Tuned PI
  3. `G0_F1_C0`: Unfiltered Edie + Stratified PC-AKF + Baseline Tuned PI
  4. `G1_F1_C0`: Stateful Gate + Stratified PC-AKF + Baseline Tuned PI
  5. `G1_F1_C1`: Stateful Gate + Stratified PC-AKF + Residual-Corrected Smith-PI
- **Robustness Stress Tests:**
  - MFD parameter misspecification: $\delta_{\text{MFD}} \in \{-20\%, 0\%, +20\%\}$
  - Boundary penetration estimation error: $\delta_{\hat{p}} \in \{-30\%, 0\%, +30\%\}$

## 5. Primary Metrics & Non-Parametric Protocol
- **Estimation Metric:** $\text{NRMSE}(N)$ over 90 one-minute windows, normalized by the observed true-accumulation range:
  $$\text{NRMSE}(N) = \frac{\sqrt{\frac{1}{T}\sum_{t=1}^T (\hat{N}_t - N_{\text{true},t})^2}}{\max_t(N_{\text{true},t}) - \min_t(N_{\text{true},t})} \times 100\%$$
- **Control Metric:** Total Network Delay ($\text{TND}$, in $\text{veh}\cdot\text{h}$) over the 5400s episode.
- **Inference:** Paired Hodges-Lehmann median difference ($\hat{\Delta}_{\text{HL}}$) with $95\%$ bootstrap CI, Cliff's delta ($\delta$), and Wilcoxon signed-rank test adjusted via Holm-Bonferroni step-down procedure ($\alpha = 0.05$).
- **Reporting rule:** All negative, null, or statistically non-significant comparisons are reported with identical prominence to positive findings.
