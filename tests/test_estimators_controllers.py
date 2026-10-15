import math
from perimeterflow.controllers import ResidualCorrectedSmithPIController
from perimeterflow.estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from perimeterflow.quality_gate import AcceptedSegment


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
