import json
import math
from pathlib import Path
from perimeterflow.controllers import ResidualCorrectedSmithPIController
from perimeterflow.estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from perimeterflow.quality_gate import AcceptedSegment
from perimeterflow.traci_runner import EpisodeConfig, FractionalObservationDelayBuffer, run_closed_loop_episode


def test_stratified_edie_eliminates_corridor_bias() -> None:
    segments = [
        AcceptedSegment(f"a_{i}", "arterial", 60.0, 60.0, 600.0) for i in range(10)
    ] + [
        AcceptedSegment(f"l_{j}", "local", 60.0, 60.0, 300.0) for j in range(5)
    ]

    strat_specs = {
        "arterial": NetworkClassSpec(length_km=10.0, estimated_penetration=0.10),
        "local": NetworkClassSpec(length_km=20.0, estimated_penetration=0.025),
    }
    _, _, n_hat_strat = compute_stratified_edie(segments, strat_specs, dt_window_s=60.0)
    assert math.isclose(n_hat_strat, 300.0, rel_tol=1e-9)


def test_pcakf_covariance_positive_definite_under_complete_blackout() -> None:
    kf = HysteresisAwarePCAKF(n_init=250.0, n_crit=420.0, n_jam=1150.0, m_max_load=0.95)
    for _ in range(20):
        n_val = kf.step(q_in_veh_s=0.8, u_gate=0.7, z_obs_n=None, p_eff=0.0, rejection_rate=1.0)
        assert 0.0 <= n_val <= kf.n_jam
        assert kf.p_cov > 0.0


def test_smith_pi_zero_delay_matches_baseline_pi_exactly() -> None:
    kf = HysteresisAwarePCAKF(n_init=300.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    ctrl_zero = ResidualCorrectedSmithPIController(n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=0)

    u1 = ctrl_zero.compute_u(440.0, 0.9, kf)
    assert math.isclose(u1, 0.893, rel_tol=1e-9)


def test_integer_delay_reproduces_frozen_golden_vectors_bit_for_bit() -> None:
    golden = json.loads(Path("data/golden/parity_vectors.json").read_text(encoding="utf-8"))
    kf = HysteresisAwarePCAKF(n_init=200.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    ctrl = ResidualCorrectedSmithPIController(n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=1)

    u_steps = [
        ctrl.compute_u(220.0, 0.8, kf, dt_s=60.0),
        ctrl.compute_u(310.0, 0.9, kf, dt_s=60.0),
        ctrl.compute_u(430.0, 0.95, kf, dt_s=60.0),
    ]
    assert u_steps == golden["expected_u_steps"]


def test_fractional_delay_buffer_blends_half_window_with_initial_seed() -> None:
    buf = FractionalObservationDelayBuffer(delay_steps=0, delay_frac=0.5, n_init=140.0)
    z_del_0 = buf.push_and_read(210.0)
    assert z_del_0 == 0.5 * 210.0 + 0.5 * 140.0
    z_del_1 = buf.push_and_read(265.0)
    assert z_del_1 == 0.5 * 265.0 + 0.5 * 210.0


def test_half_window_smith_pi_genuinely_compensates_sub_window_phase_lag() -> None:
    kf = HysteresisAwarePCAKF(n_init=200.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    ctrl_baseline = ResidualCorrectedSmithPIController(n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=0)
    ctrl_half = ResidualCorrectedSmithPIController(
        n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=0, delay_frac=0.5
    )

    u_baseline: list[float] = []
    u_half: list[float] = []
    for _ in range(6):
        u_baseline.append(ctrl_baseline.compute_u(500.0, 0.9, kf, dt_s=60.0))
        u_half.append(ctrl_half.compute_u(500.0, 0.9, kf, dt_s=60.0))

    assert u_half[0] == u_baseline[0]
    assert any(abs(a - b) > 1e-6 for a, b in zip(u_half[1:], u_baseline[1:]))
    assert all(u < 1.0 for u in u_baseline[1:])


def test_half_window_delay_regime_distinct_from_zero_and_full_window_regimes() -> None:
    cfg_common = dict(seed=1, penetration_rate=0.05, bias_mode="corridor_biased")

    ep_c1_zero = run_closed_loop_episode(EpisodeConfig(variant="G1_F1_C1", delay_s=0, **cfg_common))
    ep_c1_half = run_closed_loop_episode(EpisodeConfig(variant="G1_F1_C1", delay_s=30, **cfg_common))
    ep_c1_full = run_closed_loop_episode(EpisodeConfig(variant="G1_F1_C1", delay_s=60, **cfg_common))
    ep_c0_half = run_closed_loop_episode(EpisodeConfig(variant="G1_F1_C0", delay_s=30, **cfg_common))

    ep_c0_zero = run_closed_loop_episode(EpisodeConfig(variant="G1_F1_C0", delay_s=0, **cfg_common))

    assert ep_c1_zero.u_gate_series == ep_c0_zero.u_gate_series
    assert ep_c1_zero.nrmse_pct == ep_c0_zero.nrmse_pct

    assert ep_c1_half.u_gate_series != ep_c0_half.u_gate_series
    assert ep_c1_half.u_gate_series != ep_c1_zero.u_gate_series
    assert ep_c1_full.u_gate_series != ep_c1_half.u_gate_series
    assert ep_c1_full.u_gate_series != ep_c1_zero.u_gate_series
