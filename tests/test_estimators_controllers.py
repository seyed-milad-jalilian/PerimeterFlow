"""Stage 3 estimation and control verification tests.

All scenarios are synthetic and fully deterministic; expected values are
derived analytically inside each test, so nothing here constitutes an
empirical claim about any real network.
"""

import math

from perimeterflow.controllers import ResidualCorrectedSmithPIController
from perimeterflow.estimators import (
    HysteresisAwarePCAKF,
    NetworkClassSpec,
    compute_stratified_edie,
)
from perimeterflow.prng import Mulberry32
from perimeterflow.quality_gate import AcceptedSegment


def _seg(veh_id: str, link_class: str, timestamp_s: float, tau_s: float, d_m: float) -> AcceptedSegment:
    return AcceptedSegment(veh_id=veh_id, link_class=link_class, timestamp_s=timestamp_s, tau_s=tau_s, d_m=d_m)


def test_stratified_edie_removes_four_to_one_corridor_bias_overestimation():
    """Equal-length classes carry equal TRUE traffic; probes are 4:1
    arterial-biased (p_arterial = 4p, p_local = p). Stratified HT weighting
    with per-class penetration recovers N, while a naive single-class
    estimate that divides the pooled biased sample by the nominal fleet-wide
    penetration p over-estimates accumulation."""
    dt_window_s = 3600.0
    dt_hours = dt_window_s / 3600.0
    n_true = 2000.0  # 1000 veh per class, each present for the full hour

    p = 0.02
    specs = {
        "arterial": NetworkClassSpec(length_km=50.0, estimated_penetration=4.0 * p),
        "local": NetworkClassSpec(length_km=50.0, estimated_penetration=p),
    }
    # Every observed vehicle cruises 30 km/h for the whole window:
    # tau = 3600 s, d = 30000 m. 80 arterial + 20 local probes = 4:1 bias.
    segments = [_seg(f"a{i:03d}", "arterial", 60.0 * i, 3600.0, 30000.0) for i in range(80)]
    segments += [_seg(f"l{i:03d}", "local", 60.0 * i, 3600.0, 30000.0) for i in range(20)]

    k_hat, q_hat, n_hat = compute_stratified_edie(segments, specs, dt_window_s=dt_window_s)

    assert math.isfinite(k_hat) and k_hat > 0.0
    assert math.isfinite(q_hat) and q_hat > 0.0
    stratified_rel_err = abs(n_hat - n_true) / n_true
    assert stratified_rel_err < 1e-6

    # Naive analysis: one pooled class, nominal penetration p, same window.
    pooled_veh_hours = sum(seg.tau_s for seg in segments) / 3600.0
    naive_n = pooled_veh_hours / p / dt_hours
    naive_rel_err = abs(naive_n - n_true) / n_true
    assert naive_n > n_true  # over-estimation from arterial oversampling
    assert naive_rel_err > 0.5
    assert naive_rel_err > 100.0 * stratified_rel_err


def test_covariance_stays_positive_and_state_bounded_under_total_blackout():
    kf = HysteresisAwarePCAKF(n_init=150.0, n_crit=100.0, n_jam=200.0, m_max_load=1.2)
    for k in range(500):
        q_in = 0.9 + 0.1 * math.sin(0.1 * k)
        u_gate = 0.6 + 0.1 * math.cos(0.07 * k)
        n_est = kf.step(q_in, u_gate, z_obs_n=None, p_eff=0.001, rejection_rate=1.0)
        assert math.isfinite(kf.p_cov)
        assert kf.p_cov > 0.0
        assert math.isfinite(n_est)
        assert 0.0 <= n_est <= kf.n_jam
    # Pure prediction recursion: p_pred = f^2 * p + q_var with q_var = 20
    # keeps the covariance at or above the process noise floor forever.
    assert kf.p_cov >= 20.0


def test_delay_zero_smith_pi_equals_baseline_normalized_pi_exactly():
    rng = Mulberry32(7)
    n_crit = 100.0
    n_obs = [n_crit + 120.0 * (rng.next_float() - 0.5) for _ in range(30)]
    errors = [(n - n_crit) / n_crit for n in n_obs]

    kf = HysteresisAwarePCAKF(n_init=n_crit, n_crit=n_crit, n_jam=200.0, m_max_load=1.5)
    ctrl = ResidualCorrectedSmithPIController(n_crit=n_crit, delay_steps=0)
    u_smith = [ctrl.compute_u(n, 1.0, kf) for n in n_obs]

    # Baseline normalized PI: identical formula, identical op order.
    kp, ki, u_min = 0.85, 0.22, 0.15
    u_prev, e_prev = 1.0, 0.0
    u_baseline = []
    for e in errors:
        delta_u = -kp * (e - e_prev) - ki * e
        u_new = max(u_min, min(1.0, u_prev + delta_u))
        u_baseline.append(u_new)
        u_prev, e_prev = u_new, e

    assert u_smith == u_baseline  # exact float equality, no tolerance
    assert len(ctrl.actuation_history) == 0
    assert list(ctrl.model_pred_history) == [n_crit]
    assert min(u_smith) >= u_min
    assert max(u_smith) <= 1.0
    assert min(u_smith) < 1.0  # the sequence actually moves and clips low-bound dynamics


def test_delayed_smith_pi_uses_rollout_history_and_residual():
    q_stream = [0.6, 0.8, 1.0, 1.2, 1.4, 1.5, 1.4, 1.2, 1.0, 0.8]
    # Observations lag the true accumulation trend (telemetry pipeline delay).
    obs_stream = [110.0, 118.0, 130.0, 142.0, 150.0, 146.0, 138.0, 126.0, 114.0, 104.0]

    def run(delay_steps: int):
        kf = HysteresisAwarePCAKF(n_init=120.0, n_crit=100.0, n_jam=200.0, m_max_load=1.5)
        ctrl = ResidualCorrectedSmithPIController(n_crit=100.0, delay_steps=delay_steps)
        u_seq = [ctrl.compute_u(n_obs, q, kf) for q, n_obs in zip(q_stream, obs_stream)]
        return ctrl, u_seq

    _ctrl0, u0 = run(0)
    ctrl1, u1 = run(1)

    # delay_steps=1 maintains exactly one past actuation for the rollout and
    # a model-delay history of maxlen = delay_steps + 1.
    assert len(ctrl1.actuation_history) == 1
    past_q, past_u = ctrl1.actuation_history[0]
    assert past_q == q_stream[-1]
    assert past_u == u1[-1]
    assert len(ctrl1.model_pred_history) == 2

    # First call sees an empty history and must degenerate to pure PI.
    assert u1[0] == u0[0]
    # From the second call on, the rollout + Smith residual correction must
    # change the commanded input relative to the memoryless controller.
    assert u1[1:] != u0[1:]
    assert all(0.15 <= u <= 1.0 for u in u1)


def test_hysteresis_unloading_branch_reduces_outflow_by_drop_ratio():
    kf = HysteresisAwarePCAKF(
        n_init=90.0,
        n_crit=100.0,
        n_jam=200.0,
        m_max_load=1.5,
        hysteresis_drop_ratio=0.82,
    )
    n_val = 90.0  # > 0.7 * n_crit
    loading = kf.mfd_outflow(n_val, is_unloading=False)
    unloading = kf.mfd_outflow(n_val, is_unloading=True)
    assert unloading < loading
    assert math.isclose(unloading, 0.82 * loading, rel_tol=1e-12)

    # Below the 0.7 * n_crit arming threshold the branches coincide.
    low = 60.0
    assert kf.mfd_outflow(low, is_unloading=True) == kf.mfd_outflow(low, is_unloading=False)
