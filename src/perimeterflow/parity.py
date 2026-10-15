"""Deterministic parity-vector exporter for Python-to-TypeScript golden tests.

All vectors are computed from fixed synthetic inputs with the reference Python
implementations. They are reproducible test fixtures, not empirical results.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .prng import Mulberry32
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate

PARITY_TOLERANCE = 1e-9
PRNG_SEEDS = (1, 42, 12345)
FLOAT_COUNT = 10
GAUSSIAN_COUNT = 10
DEFAULT_EXPORT_PATH = Path("data/golden/parity_vectors.json")


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


def generate_parity_vectors() -> dict:
    return {
        "tolerance": PARITY_TOLERANCE,
        "prng_vectors": _prng_vectors(),
        "gate_vectors": _gate_vectors(),
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
