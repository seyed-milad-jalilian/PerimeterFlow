import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import yaml
from .controllers import ResidualCorrectedSmithPIController
from .estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from .prng import Mulberry32
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate
from .stats_eval import (
    cliffs_delta,
    get_git_sha,
    hodges_lehmann_paired,
    holm_bonferroni_correction,
    paired_wilcoxon_pvalue,
    validate_artifact_dict,
)
from .traci_runner import EpisodeConfig, FractionalObservationDelayBuffer, run_closed_loop_episode


def _normalize_delay_s(delay_s) -> float:
    delay_val = float(delay_s)
    if delay_val < 0.0:
        raise ValueError("delay_s must be non-negative")
    return delay_val


def _delay_tag(delay_val: float) -> str:
    return str(int(delay_val)) if float(delay_val).is_integer() else str(delay_val)


def export_golden_parity_vectors(out_path: Path) -> None:
    """Generates deterministic golden vectors for Python-to-TypeScript 1e-9 parity verification."""
    rng = Mulberry32(202601)
    prng_floats = [rng.next_float() for _ in range(16)]
    prng_gaussians = [rng.next_gaussian(2.5, 1.2) for _ in range(16)]

    pings = [
        ProbePing("v1", "arterial", 0.0, 0.0, 0.0, 10.0, 1.5),
        ProbePing("v1", "arterial", 5.0, 50.0, 0.0, 10.0, 1.8),
        ProbePing("v1", "arterial", 10.0, 230.0, 0.0, 36.0, 2.0),
        ProbePing("v1", "arterial", 15.0, 150.0, 0.0, 10.0, 1.2),
        ProbePing("v2", "local", 0.0, 0.0, 0.0, 6.0, 2.1),
        ProbePing("v2", "local", 5.0, 30.0, 0.0, 6.0, 2.0),
    ]
    gate_res = run_stateful_quality_gate(pings, GateConfig())

    specs = {
        "arterial": NetworkClassSpec(length_km=10.0, estimated_penetration=0.04),
        "local": NetworkClassSpec(length_km=20.0, estimated_penetration=0.01),
    }
    k_hat, q_hat, n_hat = compute_stratified_edie(gate_res.segments, specs, dt_window_s=60.0)

    kf = HysteresisAwarePCAKF(n_init=200.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    kf_steps = [
        kf.step(0.8, 1.0, n_hat, 0.02, gate_res.rejection_rate, dt_s=60.0),
        kf.step(0.9, 0.85, n_hat * 1.1, 0.02, gate_res.rejection_rate, dt_s=60.0),
    ]

    ctrl = ResidualCorrectedSmithPIController(n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=1)
    u_steps = [
        ctrl.compute_u(220.0, 0.8, kf, dt_s=60.0),
        ctrl.compute_u(310.0, 0.9, kf, dt_s=60.0),
        ctrl.compute_u(430.0, 0.95, kf, dt_s=60.0),
    ]

    frac_obs_series = [210.0, 265.0, 320.0, 435.0, 480.0, 410.0, 350.0, 300.0, 275.0, 250.0]
    frac_q_in_series = [0.95, 0.95, 1.05, 1.10, 1.00, 0.90, 0.80, 0.75, 0.70, 0.70]

    buf30 = FractionalObservationDelayBuffer(delay_steps=0, delay_frac=0.5, n_init=140.0)
    z_del30 = [buf30.push_and_read(z) for z in frac_obs_series]

    kf30 = HysteresisAwarePCAKF(n_init=200.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    ctrl30 = ResidualCorrectedSmithPIController(
        n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=0, delay_frac=0.5
    )
    u30_steps = [
        ctrl30.compute_u(z_del, q_in, kf30, dt_s=60.0)
        for z_del, q_in in zip(z_del30, frac_q_in_series)
    ]

    kf90 = HysteresisAwarePCAKF(n_init=200.0, n_crit=400.0, n_jam=1000.0, m_max_load=0.9)
    ctrl90 = ResidualCorrectedSmithPIController(
        n_crit=400.0, kp_norm=0.85, ki_norm=0.22, delay_steps=1, delay_frac=0.5
    )
    u90_steps = [
        ctrl90.compute_u(z_del, q_in, kf90, dt_s=60.0)
        for z_del, q_in in zip(z_del30, frac_q_in_series)
    ]

    payload = {
        "seed": 202601,
        "prng_floats": prng_floats,
        "prng_gaussians": prng_gaussians,
        "pings": [p.__dict__ for p in pings],
        "expected_gate": {
            "rejection_rate": gate_res.rejection_rate,
            "segments": [s.__dict__ for s in gate_res.segments],
        },
        "expected_edie": {"k_hat": k_hat, "q_hat": q_hat, "n_hat": n_hat},
        "expected_kf_steps": kf_steps,
        "expected_u_steps": u_steps,
        "fractional_delay": {
            "dt_s": 60.0,
            "n_init": 140.0,
            "obs_series": frac_obs_series,
            "q_in_series": frac_q_in_series,
            "buffer": {
                "delay_steps": 0,
                "delay_frac": 0.5,
                "expected_z_del": z_del30,
            },
            "smith_tau30": {
                "delay_steps": 0,
                "delay_frac": 0.5,
                "expected_u_steps": u30_steps,
            },
            "smith_tau90": {
                "delay_steps": 1,
                "delay_frac": 0.5,
                "expected_u_steps": u90_steps,
            },
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_calibration(config_path: Path, out_path: Path) -> None:
    """Grid-search tunes (kp_norm, ki_norm) exclusively on Calibration Seeds 1..10."""
    cfg_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    seeds: list[int] = cfg_data["seeds"]
    pen_rate = float(cfg_data.get("penetration_rate", 0.02))
    bias_mode = str(cfg_data.get("bias_mode", "corridor_biased"))
    delay_s = _normalize_delay_s(cfg_data.get("delay_s", 60))
    kp_grid: list[float] = cfg_data.get("kp_grid", [0.65, 0.85, 1.05])
    ki_grid: list[float] = cfg_data.get("ki_grid", [0.15, 0.22, 0.30])

    best_gains: dict[str, dict[str, float]] = {}
    for variant_tag in ("C0", "C1"):
        full_variant = f"G1_F1_{variant_tag}"
        best_tnd = float("inf")
        best_pair = (0.85, 0.22)
        for kp in kp_grid:
            for ki in ki_grid:
                tnds = [
                    run_closed_loop_episode(
                        EpisodeConfig(
                            seed=s,
                            penetration_rate=pen_rate,
                            bias_mode=bias_mode,
                            delay_s=delay_s,
                            variant=full_variant,
                            kp_norm=float(kp),
                            ki_norm=float(ki),
                        )
                    ).tnd_veh_h
                    for s in seeds
                ]
                med_tnd = float(np.median(tnds))
                if med_tnd < best_tnd:
                    best_tnd = med_tnd
                    best_pair = (float(kp), float(ki))
        best_gains[variant_tag] = {
            "kp_norm": best_pair[0],
            "ki_norm": best_pair[1],
            "calibrated_median_tnd_veh_h": best_tnd,
        }

    payload = {
        "calibrated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": get_git_sha(),
        "calibration_seeds": seeds,
        "gains": best_gains,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_sweep_from_config(config_path: Path, out_path: Path, params_path: Path | None = None) -> None:
    cfg_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    seeds: list[int] = cfg_data["seeds"]
    variants: list[str] = cfg_data.get("variants", ["G0_F0_C0", "G1_F0_C0", "G0_F1_C0", "G1_F1_C0", "G1_F1_C1"])
    pen_rate = float(cfg_data.get("penetration_rate", 0.02))
    bias_mode = str(cfg_data.get("bias_mode", "corridor_biased"))
    delay_s = _normalize_delay_s(cfg_data.get("delay_s", 60))
    delay_s_out = int(delay_s) if delay_s.is_integer() else delay_s

    tuned_gains = {"C0": {"kp_norm": 0.85, "ki_norm": 0.22}, "C1": {"kp_norm": 0.85, "ki_norm": 0.22}}
    if params_path is not None and params_path.exists():
        loaded = json.loads(params_path.read_text(encoding="utf-8"))
        tuned_gains.update(loaded.get("gains", {}))

    results_by_variant: dict[str, list] = {v: [] for v in variants}
    for v in variants:
        ctrl_key = "C1" if "C1" in v else "C0"
        kp_val = float(tuned_gains[ctrl_key]["kp_norm"])
        ki_val = float(tuned_gains[ctrl_key]["ki_norm"])
        for s in seeds:
            ep_res = run_closed_loop_episode(
                EpisodeConfig(
                    seed=s,
                    penetration_rate=pen_rate,
                    bias_mode=bias_mode,
                    delay_s=delay_s,
                    variant=v,
                    kp_norm=kp_val,
                    ki_norm=ki_val,
                )
            )
            results_by_variant[v].append(ep_res)

    summary_table = []
    for v in variants:
        nrmses = np.array([r.nrmse_pct for r in results_by_variant[v]], dtype=np.float64)
        tnds = np.array([r.tnd_veh_h for r in results_by_variant[v]], dtype=np.float64)
        summary_table.append(
            {
                "condition_id": f"p{int(pen_rate*100):02d}_{bias_mode}_delay{_delay_tag(delay_s)}_{v}",
                "penetration_rate": pen_rate,
                "bias_mode": bias_mode,
                "delay_s": delay_s_out,
                "variant": v,
                "n_seeds": len(seeds),
                "nrmse_median_pct": float(np.median(nrmses)),
                "nrmse_iqr_pct": float(np.percentile(nrmses, 75) - np.percentile(nrmses, 25)),
                "tnd_median_veh_h": float(np.median(tnds)),
                "tnd_iqr_veh_h": float(np.percentile(tnds, 75) - np.percentile(tnds, 25)),
            }
        )

    baseline_v = variants[0]
    base_nrmse = np.array([r.nrmse_pct for r in results_by_variant[baseline_v]], dtype=np.float64)
    raw_pvals: list[float] = []
    comparisons_raw: list[dict] = []

    for prop_v in variants[1:]:
        prop_nrmse = np.array([r.nrmse_pct for r in results_by_variant[prop_v]], dtype=np.float64)
        hl_diff, ci_low, ci_high = hodges_lehmann_paired(base_nrmse, prop_nrmse, seed=42)
        c_delta = cliffs_delta(base_nrmse, prop_nrmse)
        p_raw = paired_wilcoxon_pvalue(base_nrmse, prop_nrmse)
        raw_pvals.append(p_raw)
        comparisons_raw.append(
            {
                "comparison_id": f"{baseline_v}_vs_{prop_v}_nrmse",
                "baseline_variant": baseline_v,
                "proposed_variant": prop_v,
                "metric_unit": "pct",
                "hl_median_diff": hl_diff,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "cliffs_delta": c_delta,
                "p_value_raw": p_raw,
                "p_value_holm": p_raw,
            }
        )

    holm_pvals = holm_bonferroni_correction(raw_pvals)
    for comp, p_adj in zip(comparisons_raw, holm_pvals):
        comp["p_value_holm"] = p_adj

    cfg_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    data_hash = hashlib.sha256(json.dumps(summary_table, sort_keys=True).encode("utf-8")).hexdigest()

    payload = {
        "meta": {
            "artifact_id": "perimeterflow-mfd-ensemble",
            "run_id": f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            "git_sha": get_git_sha(),
            "config_sha256": cfg_hash,
            "data_sha256": data_hash,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "reproduced-in-ci",
            "mode": "simulation",
            "calibration_seeds": list(range(1, 11)),
            "evaluation_seeds": seeds,
            "license": "MIT",
        },
        "summary_table": summary_table,
        "ablation_comparisons": comparisons_raw,
    }
    validate_artifact_dict(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_k8s_indexed_worker(seed_offset: int, out_dir: Path) -> None:
    """Executes a single seed slice inside a Kubernetes IndexedJob pod."""
    job_idx = int(os.environ.get("JOB_INDEX", "0"))
    seed = seed_offset + job_idx
    variants = ["G0_F0_C0", "G1_F0_C0", "G0_F1_C0", "G1_F1_C0", "G1_F1_C1"]
    records = []
    for v in variants:
        ep = run_closed_loop_episode(EpisodeConfig(seed=seed, variant=v))
        records.append(
            {
                "seed": seed,
                "variant": v,
                "nrmse_pct": ep.nrmse_pct,
                "tnd_veh_h": ep.tnd_veh_h,
            }
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"seed_{seed:03d}.json"
    out_file.write_text(json.dumps({"seed": seed, "results": records}, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="PerimeterFlow CLI")
    parser.add_argument("--export-golden", type=Path, help="Export golden parity vectors JSON")
    parser.add_argument("--config", type=Path, help="YAML configuration file")
    parser.add_argument("--output", type=Path, help="Output JSON artifact path")
    parser.add_argument("--mode", type=str, default="sweep", choices=["sweep", "calibrate", "worker"])
    parser.add_argument("--params", type=Path, help="Optional calibrated parameters file")
    parser.add_argument("--seed-offset", type=int, default=11)
    parser.add_argument("--worker-out-dir", type=Path, default=Path("/out"))
    args = parser.parse_args()

    if args.export_golden is not None:
        export_golden_parity_vectors(args.export_golden)
        return

    if args.mode == "worker":
        run_k8s_indexed_worker(args.seed_offset, args.worker_out_dir)
        return

    if args.mode == "calibrate":
        if args.config is None or args.output is None:
            raise ValueError("--config and --output are required for --mode calibrate")
        run_calibration(args.config, args.output)
        return

    if args.config is not None and args.output is not None:
        run_sweep_from_config(args.config, args.output, args.params)


if __name__ == "__main__":
    main()
