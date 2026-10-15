"""PerimeterFlow command-line platform.

Subcommands (mirrored by the Makefile and the K8s IndexedJob):
  generate-network  build the deterministic 8x8 two-reservoir SUMO bundle
  export-golden     export Python reference parity vectors for the Vitest tests
  init-planned      export the schema-valid pre-run ("planned") artifact
  calibrate         tune normalized PI gains on calibration seeds 1..10 only
  sweep             run the held-out evaluation seeds and export the artifact
  worker            single IndexedJob worker episode (seed = offset + JOB_INDEX)
  validate-pneuma   offline estimation validation on pNEUMA trajectories

Integrity rule enforced here: no command fabricates empirical numbers. The
sweep writes "results-unreviewed" artifacts only from episodes that actually
ran; init-planned writes null metrics with status "planned".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from . import parity
from .pneuma_validator import DEFAULT_PNEUMA_DIR, export_validation_report
from .stats_eval import (
    CALIBRATION_SEEDS,
    write_planned_skeleton_artifact,
    write_results_artifact,
)
from .traci_runner import EpisodeConfig, episode_metrics, run_replay_episode, run_sumo_episode

GAIN_GRID: tuple[tuple[float, float], ...] = (
    (0.40, 0.10),
    (0.60, 0.15),
    (0.85, 0.22),
    (1.05, 0.30),
    (1.25, 0.40),
)


def load_config(config_path: Path) -> dict:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or "seeds" not in config:
        raise ValueError(f"{config_path} is not a valid PerimeterFlow run configuration")
    return config


def config_to_episode(config: dict, seed: int) -> EpisodeConfig:
    return EpisodeConfig(
        seed=seed,
        episode_length_s=int(config["episode_length_s"]),
        dt_window_s=float(config["dt_window_s"]),
        penetration_rate=float(config["penetration_rate"]),
        bias_mode=str(config["bias_mode"]),
        delay_s=int(config["delay_s"]),
        mfd_ncrit_factor=float(config.get("mfd_ncrit_factor", 1.0)),
        mfd_mmax_factor=float(config.get("mfd_mmax_factor", 1.0)),
        penetration_estimation_factor=float(config.get("penetration_estimation_factor", 1.0)),
    )


def _episode_for_mode(config: dict, seed: int, sumocfg: Path | None):
    episode = config_to_episode(config, seed)
    if sumocfg is not None:
        return run_sumo_episode(episode, Path(sumocfg))
    return run_replay_episode(episode)


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_generate_network(args: argparse.Namespace) -> int:
    from .network_gen import generate_network

    summary = generate_network(Path(args.output))
    print(f"net:     {summary['net']}")
    print(f"demand:  {summary['demand']}")
    print(f"sumocfg: {summary['sumocfg']}")
    print(f"class lengths (km): {summary['class_lengths_km']}")
    return 0


def cmd_export_golden(args: argparse.Namespace) -> int:
    parity.export_golden_vectors(Path(args.path))
    print(f"parity vectors written to {args.path}")
    return 0


def cmd_init_planned(args: argparse.Namespace) -> int:
    artifact = write_planned_skeleton_artifact(Path(args.output), Path(args.config))
    print(f"planned skeleton artifact written to {args.output} (status={artifact['meta']['status']})")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Gain tuning on the calibration partition ONLY (seeds 1..10).

    Each candidate (Kp, Ki) pair is scored by the mean Total Network Delay of
    the proposed pipeline across the calibration seeds; the best pair is
    frozen and written for the sweep. Evaluation seeds are never touched.
    """
    config = load_config(Path(args.config))
    seeds = [int(s) for s in config["seeds"]]
    if sorted(seeds) != CALIBRATION_SEEDS:
        print(
            "calibration must use exactly the pre-registered calibration seeds 1..10",
            file=sys.stderr,
        )
        return 2
    sumocfg = Path(args.sumocfg) if args.sumocfg else None
    best: dict | None = None
    for kp, ki in GAIN_GRID:
        tnd_values: list[float] = []
        for seed in seeds:
            episode = config_to_episode(config, seed)
            episode = EpisodeConfig(**{**episode.__dict__, "tuned_gains": (kp, ki)})
            result = _calibration_episode(config, seed, kp, ki, sumocfg)
            metrics = episode_metrics(result, episode)
            tnd_values.append(metrics["proposed"]["tnd_veh_h"])
        mean_tnd = sum(tnd_values) / len(tnd_values)
        print(f"gains Kp={kp:.2f} Ki={ki:.2f}: mean TND = {mean_tnd:.3f} veh*h")
        if best is None or mean_tnd < best["mean_tnd_veh_h"]:
            best = {
                "kp_norm": kp,
                "ki_norm": ki,
                "mean_tnd_veh_h": mean_tnd,
                "per_seed_tnd_veh_h": tnd_values,
            }
    payload = {
        "calibration_seeds": seeds,
        "criterion": "mean_total_network_delay_veh_h",
        "gain_grid": [list(pair) for pair in GAIN_GRID],
        "selected": best,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"calibrated gains written to {args.output}: Kp={best['kp_norm']} Ki={best['ki_norm']}")
    return 0


def _calibration_episode(
    config: dict, seed: int, kp: float, ki: float, sumocfg: Path | None
):
    episode = config_to_episode(config, seed)
    episode = EpisodeConfig(**{**episode.__dict__, "tuned_gains": (kp, ki)})
    if sumocfg is not None:
        return run_sumo_episode(episode, Path(sumocfg))
    return run_replay_episode(episode)


def cmd_sweep(args: argparse.Namespace) -> int:
    """Run the pre-registered evaluation sweep over the held-out seeds.

    The two pipeline variants compared per the analysis plan are:
      unfiltered_pi    raw unstratified Edie estimate feeding a plain PI loop
      gated_akf_smith  stateful gate + stratified HT + hysteresis PC-AKF + Smith-PI
    """
    config = load_config(Path(args.config))
    seeds = [int(s) for s in config["seeds"]]
    if args.params:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
        gains = (float(params["selected"]["kp_norm"]), float(params["selected"]["ki_norm"]))
    else:
        gains = (0.85, 0.22)
    sumocfg = Path(args.sumocfg) if args.sumocfg else None
    mode = "simulation" if sumocfg is not None else "replay"

    metrics_by_variant: dict[str, dict[str, list[float]]] = {
        "unfiltered_pi": {"nrmse_pct": [], "tnd_veh_h": []},
        "gated_akf_smith": {"nrmse_pct": [], "tnd_veh_h": []},
    }
    for seed in seeds:
        episode = config_to_episode(config, seed)
        episode = EpisodeConfig(**{**episode.__dict__, "tuned_gains": gains})
        result = _episode_for_mode(config, seed, sumocfg)
        metrics = episode_metrics(result, episode)
        for variant, values in metrics.items():
            key = "unfiltered_pi" if variant == "baseline" else "gated_akf_smith"
            metrics_by_variant[key]["nrmse_pct"].append(values["nrmse_pct"])
            metrics_by_variant[key]["tnd_veh_h"].append(values["tnd_veh_h"])
        print(
            f"seed {seed}: NRMSE baseline={metrics['baseline']['nrmse_pct']:.3f}% "
            f"proposed={metrics['proposed']['nrmse_pct']:.3f}% | "
            f"TND baseline={metrics['baseline']['tnd_veh_h']:.3f} "
            f"proposed={metrics['proposed']['tnd_veh_h']:.3f} veh*h"
        )

    artifact = write_results_artifact(
        Path(args.output), Path(args.config), mode, metrics_by_variant
    )
    ok = _validate_and_report(artifact)
    print(f"sweep artifact written to {args.output} (status={artifact['meta']['status']})")
    return 0 if ok else 3


def cmd_worker(args: argparse.Namespace) -> int:
    """Single IndexedJob episode: seed = seed-offset + JOB_INDEX (or --seed)."""
    seed = args.seed
    if seed is None:
        index = os.environ.get("JOB_INDEX")
        if index is None:
            print("worker requires --seed or the JOB_INDEX environment variable", file=sys.stderr)
            return 2
        seed = int(args.seed_offset) + int(index)
    config = load_config(Path(args.config))
    params_gains = (0.85, 0.22)
    if args.params:
        params = json.loads(Path(args.params).read_text(encoding="utf-8"))
        params_gains = (float(params["selected"]["kp_norm"]), float(params["selected"]["ki_norm"]))
    episode = config_to_episode(config, seed)
    episode = EpisodeConfig(**{**episode.__dict__, "tuned_gains": params_gains})
    result = _episode_for_mode(config, seed, Path(args.sumocfg) if args.sumocfg else None)
    metrics = episode_metrics(result, episode)
    payload = {
        "seed": seed,
        "mode": "simulation" if args.sumocfg else "replay",
        "metrics": metrics,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"worker episode for seed {seed} written to {args.output}")
    return 0


def cmd_validate_pneuma(args: argparse.Namespace) -> int:
    report = export_validation_report(Path(args.output), Path(args.subset))
    print(
        f"pNEUMA validation: {report['total_pings']} pings across "
        f"{report['vehicles_observed']} vehicles, rejection rate "
        f"{report['rejection_rate']:.3f} -> {args.output}"
    )
    return 0


def _validate_and_report(artifact: dict) -> bool:
    from .stats_eval import validate_artifact

    return validate_artifact(artifact)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="perimeterflow", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate-network", help="build the deterministic SUMO bundle")
    p.add_argument("--output", type=str, default="results/network")
    p.set_defaults(func=cmd_generate_network)

    p = sub.add_parser("export-golden", help="export golden parity vectors")
    p.add_argument("path", nargs="?", default=str(parity.DEFAULT_EXPORT_PATH))
    p.set_defaults(func=cmd_export_golden)

    p = sub.add_parser("init-planned", help="export the planned (pre-run) artifact")
    p.add_argument("--config", default="configs/evaluate_seeds.yaml")
    p.add_argument("--output", default="results/ensemble.json")
    p.set_defaults(func=cmd_init_planned)

    p = sub.add_parser("calibrate", help="tune gains on calibration seeds 1..10")
    p.add_argument("--config", default="configs/calibrate_seeds.yaml")
    p.add_argument("--output", default="results/calibrated_params.json")
    p.add_argument("--sumocfg", default=None, help="run against a real SUMO network")
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("sweep", help="run held-out evaluation seeds and export the artifact")
    p.add_argument("--config", default="configs/evaluate_seeds.yaml")
    p.add_argument("--params", default=None, help="calibrated_params.json from calibrate")
    p.add_argument("--output", default="results/ensemble.json")
    p.add_argument("--sumocfg", default=None, help="run against a real SUMO network")
    p.set_defaults(func=cmd_sweep)

    p = sub.add_parser("worker", help="single IndexedJob worker episode")
    p.add_argument("--config", default="configs/evaluate_seeds.yaml")
    p.add_argument("--params", default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--seed-offset", type=int, default=11)
    p.add_argument("--output", default=None)
    p.add_argument("--sumocfg", default=None)
    p.set_defaults(func=cmd_worker)

    p = sub.add_parser("validate-pneuma", help="offline validation on pNEUMA trajectories")
    p.add_argument("--subset", type=str, default=str(DEFAULT_PNEUMA_DIR))
    p.add_argument("--output", type=str, default="results/pneuma_validation.json")
    p.set_defaults(func=cmd_validate_pneuma)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "worker" and args.output is None:
        seed_hint = args.seed if args.seed is not None else "index"
        args.output = f"results/worker_{seed_hint}.json"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
