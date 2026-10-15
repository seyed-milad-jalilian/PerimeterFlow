"""Offline estimation validation on empirical pNEUMA drone trajectories.

Reads vehicle trajectory CSVs from data/pneuma_subset/ (one row per ping:
veh_id, t_s, x_m, y_m, optional speed_ms), runs the stateful kinematic
quality gate and the stratified Horvitz-Thompson Edie estimator over fixed
one-minute windows, and emits a descriptive JSON report. This validator makes
no control-loop claims: closed-loop gating cannot be actuated on offline
naturalistic logs (docs/THREATS_TO_VALIDITY.md).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .estimators import NetworkClassSpec, compute_stratified_edie
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate

DEFAULT_PNEUMA_DIR = Path("data/pneuma_subset")
WINDOW_S = 60.0
DEFAULT_CLASS_LENGTHS_KM = {"arterial": 10.8, "local": 6.0}


def load_pneuma_pings(subset_dir: Path) -> list[ProbePing]:
    """Load probe pings from every CSV in the subset directory.

    Supported columns (header required): veh_id, t_s, x_m, y_m, and optionally
    speed_ms and link_class. When speed_ms is absent it is derived from the
    finite difference of consecutive positions of the same vehicle; when
    link_class is absent, pings are labelled 'local'.
    """
    subset_dir = Path(subset_dir)
    csv_files = sorted(subset_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"no trajectory CSVs found in {subset_dir}; place pNEUMA extracts "
            "there following DATA.md"
        )
    pings: list[ProbePing] = []
    for csv_path in csv_files:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = {name.strip().lower(): name for name in (reader.fieldnames or [])}
            required = ("veh_id", "t_s", "x_m", "y_m")
            missing = [c for c in required if c not in fields]
            if missing:
                raise ValueError(
                    f"{csv_path} is missing required columns: {missing}"
                )
            rows_by_vehicle: dict[str, list[dict]] = {}
            for row in reader:
                rows_by_vehicle.setdefault(row[fields["veh_id"]], []).append(row)
            for veh_rows in rows_by_vehicle.values():
                veh_rows.sort(key=lambda r: float(r[fields["t_s"]]))
                prev_t: float | None = None
                prev_x = prev_y = 0.0
                for row in veh_rows:
                    t = float(row[fields["t_s"]])
                    x = float(row[fields["x_m"]])
                    y = float(row[fields["y_m"]])
                    if "speed_ms" in fields and row[fields["speed_ms"]]:
                        speed = float(row[fields["speed_ms"]])
                    elif prev_t is not None and t > prev_t:
                        speed = ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5 / (t - prev_t)
                    else:
                        speed = 0.0
                    link_class = (
                        row[fields["link_class"]].strip()
                        if "link_class" in fields and row[fields["link_class"]]
                        else "local"
                    )
                    snap = (
                        float(row[fields["snap_dist_m"]])
                        if "snap_dist_m" in fields and row[fields["snap_dist_m"]]
                        else 0.0
                    )
                    pings.append(
                        ProbePing(
                            veh_id=row[fields["veh_id"]],
                            link_class=link_class,
                            timestamp_s=t,
                            x_obs_m=x,
                            y_obs_m=y,
                            speed_obs_ms=speed,
                            snap_dist_m=snap,
                        )
                    )
                    prev_t, prev_x, prev_y = t, x, y
    return pings


def validate_on_pneuma(
    subset_dir: Path = DEFAULT_PNEUMA_DIR,
    class_lengths_km: dict[str, float] | None = None,
    penetration: float = 1.0,
) -> dict:
    """Gate + stratified Edie validation on naturalistic trajectories.

    penetration defaults to 1.0 because pNEUMA tracks every vehicle in the
    study area: the estimator recovers the drone-measured accumulation
    directly, and window errors describe the pipeline's behavior on real
    kinematics rather than a control outcome.
    """
    lengths = class_lengths_km or dict(DEFAULT_CLASS_LENGTHS_KM)
    pings = load_pneuma_pings(subset_dir)
    gate_cfg = GateConfig()
    summary = run_stateful_quality_gate(pings, gate_cfg)

    t_start = min(p.timestamp_s for p in pings)
    t_end = max(p.timestamp_s for p in pings)
    specs = {
        klass: NetworkClassSpec(length_km=length, estimated_penetration=penetration)
        for klass, length in lengths.items()
    }

    windows: list[dict] = []
    w_index = 0
    t_cursor = t_start
    while t_cursor <= t_end:
        w_end = t_cursor + WINDOW_S
        segments = [
            s
            for s in summary.segments
            if t_cursor <= s.timestamp_s < w_end
        ]
        if segments:
            k_hat, q_hat, n_hat = compute_stratified_edie(
                segments, specs, dt_window_s=WINDOW_S
            )
        else:
            k_hat = q_hat = n_hat = 0.0
        windows.append(
            {
                "window_index": w_index,
                "t_start_s": t_cursor,
                "t_end_s": min(w_end, t_end),
                "n_segments": len(segments),
                "k_hat_veh_km": k_hat,
                "q_hat_veh_h": q_hat,
                "n_hat_veh": n_hat,
            }
        )
        t_cursor = w_end
        w_index += 1

    return {
        "validator": "pneuma_offline_estimation",
        "subset_dir": str(subset_dir),
        "window_s": WINDOW_S,
        "total_pings": summary.total_pings,
        "rejection_rate": summary.rejection_rate,
        "rejected_spatial": summary.rejected_spatial,
        "rejected_kinematic": summary.rejected_kinematic,
        "accepted_segments": len(summary.segments),
        "vehicles_observed": len({p.veh_id for p in pings}),
        "horizon_s": [t_start, t_end],
        "windows": windows,
    }


def export_validation_report(out_path: Path, subset_dir: Path = DEFAULT_PNEUMA_DIR) -> dict:
    report = validate_on_pneuma(subset_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate estimation on pNEUMA trajectories.")
    parser.add_argument("--subset", type=Path, default=DEFAULT_PNEUMA_DIR)
    parser.add_argument("--output", type=Path, default=Path("results/pneuma_validation.json"))
    args = parser.parse_args()
    report = export_validation_report(args.output, args.subset)
    print(
        f"pNEUMA validation: {report['total_pings']} pings, "
        f"rejection rate {report['rejection_rate']:.3f} -> {args.output}"
    )
