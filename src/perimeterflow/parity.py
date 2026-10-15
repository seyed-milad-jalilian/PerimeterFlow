"""Deterministic parity-vector exporter for Python-to-TypeScript golden tests.

All vectors are computed from fixed synthetic inputs with the reference Python
implementations. They are reproducible test fixtures, not empirical results.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .controllers import ResidualCorrectedSmithPIController
from .estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from .prng import Mulberry32
from .quality_gate import (
    AcceptedSegment,
    GateConfig,
    ProbePing,
    run_stateful_quality_gate,
)

PARITY_TOLERANCE = 1e-9
PRNG_SEEDS = (1, 42, 12345)
FLOAT_COUNT = 10
GAUSSIAN_COUNT = 10
DEFAULT_EXPORT_PATH = Path("data/golden/parity_vectors.json")
AKF_SEED = 7
AKF_STEPS = 20
AKF_BLACKOUT_STEPS = (12, 13)
CONTROLLER_STEPS = 15
_CONTROLLER_Q_IN = (
    0.60, 0.80, 1.00, 1.20, 1.40, 1.50, 1.40, 1.20, 1.00, 0.80,
    0.60, 0.50, 0.70, 0.90, 1.10,
)
_CONTROLLER_N_DELAYED_OBS = (
    120.0, 108.0, 101.0, 96.0, 104.0, 111.0, 99.0, 92.0, 103.0, 109.0,
    97.0, 90.0, 105.0, 112.0, 100.0,
)


def _ping(veh_id, link_class, timestamp_s, x, y, speed, snap=0.0) -> ProbePing:
    return ProbePing(
        veh_id=veh_id,
        link_class=link_class,
        timestamp_s=timestamp_s,
        x_obs_m=x,
        y_obs_m=y,
        speed_obs_ms=speed,
        snap_dist_m=snap,
    )


def _prng_vectors() -> list[dict]:
    vectors = []
    for seed in PRNG_SEEDS:
        float_gen = Mulberry32(seed)
        floats = [float_gen.next_float() for _ in range(FLOAT_COUNT)]
        gaussian_gen = Mulberry32(seed)
        gaussians = [gaussian_gen.next_gaussian() for _ in range(GAUSSIAN_COUNT)]
        vectors.append({"seed": seed, "next_float": floats, "next_gaussian": gaussians})
    return vectors


def _gate_streams() -> list[tuple[str, list[ProbePing]]]:
    clean_two_vehicles = [
        _ping("veh_a", "arterial", 0.0, 0.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 10.0, 100.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 20.0, 200.0, 0.0, 10.0),
        _ping("veh_b", "local", 0.0, 0.0, 500.0, 15.0),
        _ping("veh_b", "local", 15.0, 225.0, 500.0, 15.0),
        _ping("veh_b", "local", 30.0, 450.0, 500.0, 15.0),
    ]
    outlier_spike = [
        _ping("veh_a", "arterial", 0.0, 0.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 5.0, 50.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 6.0, 100.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 11.0, 100.0, 0.0, 10.0),
        _ping("veh_a", "arterial", 12.0, 110.0, 0.0, 10.0, snap=13.0),
        _ping("veh_a", "arterial", 16.0, 140.0, 0.0, 10.0),
    ]
    gap_reset = [
        _ping("veh_a", "local", 0.0, 0.0, 0.0, 10.0),
        _ping("veh_a", "local", 10.0, 100.0, 0.0, 10.0),
        _ping("veh_a", "local", 26.0, 200.0, 0.0, 10.0),
        _ping("veh_a", "local", 40.0, 300.0, 0.0, 10.0),
        _ping("veh_b", "local", 0.0, 0.0, 0.0, -1.0),
        _ping("veh_b", "local", 5.0, 25.0, 0.0, 5.0),
    ]
    return [
        ("clean_two_vehicles", clean_two_vehicles),
        ("outlier_spike", outlier_spike),
        ("gap_reset", gap_reset),
    ]


def _gate_vectors() -> list[dict]:
    cfg = GateConfig()
    vectors = []
    for name, pings in _gate_streams():
        summary = run_stateful_quality_gate(pings, cfg)
        vectors.append(
            {
                "name": name,
                "config": asdict(cfg),
                "pings": [asdict(p) for p in pings],
                "segments": [asdict(s) for s in summary.segments],
                "rejection_rate": summary.rejection_rate,
                "total_pings": summary.total_pings,
                "rejected_spatial": summary.rejected_spatial,
                "rejected_kinematic": summary.rejected_kinematic,
            }
        )
    return vectors


def _estimator_vectors() -> list[dict]:
    class_specs = {
        "arterial": NetworkClassSpec(length_km=30.0, estimated_penetration=0.06),
        "local": NetworkClassSpec(length_km=45.0, estimated_penetration=0.015),
    }
    raw_segments = [
        ("veh_a1", "arterial", 0.0, 3600.0, 30000.0),
        ("veh_a2", "arterial", 60.0, 1800.0, 12000.0),
        ("veh_a3", "arterial", 120.0, 2400.0, 18000.0),
        ("veh_a4", "arterial", 180.0, 3600.0, 36000.0),
        ("veh_l1", "local", 0.0, 3600.0, 15000.0),
        ("veh_l2", "local", 60.0, 1200.0, 6000.0),
        ("veh_l3", "local", 120.0, 3000.0, 24000.0),
        ("veh_l4", "local", 180.0, 600.0, 3000.0),
    ]
    segments = [AcceptedSegment(*row) for row in raw_segments]
    k_hat, q_hat, n_hat = compute_stratified_edie(
        segments, class_specs, dt_window_s=3600.0, p_min=0.005
    )
    return [
        {
            "name": "stratified_edie_two_class",
            "dt_window_s": 3600.0,
            "p_min": 0.005,
            "class_specs": {name: asdict(spec) for name, spec in class_specs.items()},
            "segments": [asdict(seg) for seg in segments],
            "k_hat_veh_km": k_hat,
            "q_hat_veh_h": q_hat,
            "n_hat_veh": n_hat,
        }
    ]


def _akf_vectors() -> list[dict]:
    params = {
        "n_init": 120.0,
        "n_crit": 100.0,
        "n_jam": 200.0,
        "m_max_load": 1.5,
        "hysteresis_drop_ratio": 0.82,
        "q_var": 20.0,
        "r_base": 120.0,
        "alpha_gate": 2.5,
    }
    rng = Mulberry32(AKF_SEED)
    kf = HysteresisAwarePCAKF(
        n_init=params["n_init"],
        n_crit=params["n_crit"],
        n_jam=params["n_jam"],
        m_max_load=params["m_max_load"],
        hysteresis_drop_ratio=params["hysteresis_drop_ratio"],
        q_var=params["q_var"],
        r_base=params["r_base"],
        alpha_gate=params["alpha_gate"],
    )
    steps: list[dict] = []
    n_est: list[float] = []
    p_cov: list[float] = []
    for k in range(AKF_STEPS):
        q_in_veh_s = 0.5 + 0.3 * rng.next_float()
        u_gate = 0.8 + 0.2 * rng.next_float()
        p_eff = 0.02 + 0.06 * rng.next_float()
        rejection_rate = 0.4 * rng.next_float()
        z_obs_n: float | None = 130.0 + 25.0 * rng.next_gaussian()
        if k in AKF_BLACKOUT_STEPS:
            # Total sensor blackout steps exercise the prediction-only branch.
            z_obs_n = None
            rejection_rate = 0.97
        n_est.append(kf.step(q_in_veh_s, u_gate, z_obs_n, p_eff, rejection_rate))
        p_cov.append(kf.p_cov)
        steps.append(
            {
                "q_in_veh_s": q_in_veh_s,
                "u_gate": u_gate,
                "z_obs_n": z_obs_n,
                "p_eff": p_eff,
                "rejection_rate": rejection_rate,
                "dt_s": 60.0,
            }
        )
    return [
        {
            "name": "akf_mulberry32_seed7_20_steps",
            "seed": AKF_SEED,
            "params": params,
            "steps": steps,
            "n_est": n_est,
            "p_cov": p_cov,
        }
    ]


def _controller_vectors() -> list[dict]:
    vectors = []
    for name, delay_steps in (
        ("smith_pi_delay3_15_steps", 3),
        ("smith_pi_delay0_15_steps", 0),
    ):
        kf = HysteresisAwarePCAKF(n_init=120.0, n_crit=100.0, n_jam=200.0, m_max_load=1.5)
        ctrl = ResidualCorrectedSmithPIController(n_crit=100.0, delay_steps=delay_steps)
        u_seq: list[float] = []
        for q_in, n_delayed_obs in zip(_CONTROLLER_Q_IN, _CONTROLLER_N_DELAYED_OBS):
            u_seq.append(ctrl.compute_u(n_delayed_obs, q_in, kf))
        vectors.append(
            {
                "name": name,
                "delay_steps": delay_steps,
                "n_crit": 100.0,
                "kp_norm": 0.85,
                "ki_norm": 0.22,
                "u_min": 0.15,
                "dt_s": 60.0,
                "kf_params": {
                    "n_init": 120.0,
                    "n_crit": 100.0,
                    "n_jam": 200.0,
                    "m_max_load": 1.5,
                    "hysteresis_drop_ratio": 0.82,
                    "q_var": 20.0,
                    "r_base": 120.0,
                    "alpha_gate": 2.5,
                },
                "q_in_stream": list(_CONTROLLER_Q_IN),
                "n_delayed_obs_stream": list(_CONTROLLER_N_DELAYED_OBS),
                "u": u_seq,
            }
        )
    return vectors


def generate_parity_vectors() -> dict:
    return {
        "tolerance": PARITY_TOLERANCE,
        "prng_vectors": _prng_vectors(),
        "gate_vectors": _gate_vectors(),
        "estimator_vectors": _estimator_vectors(),
        "akf_vectors": _akf_vectors(),
        "controller_vectors": _controller_vectors(),
    }


def export_golden_vectors(path: Path = DEFAULT_EXPORT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(generate_parity_vectors(), indent=2, allow_nan=False)
    path.write_text(payload + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export deterministic Python-side parity vectors.")
    parser.add_argument("--path", type=Path, default=DEFAULT_EXPORT_PATH)
    args = parser.parse_args()
    export_golden_vectors(args.path)
    print(f"parity vectors written to {args.path}")


if __name__ == "__main__":
    main()
