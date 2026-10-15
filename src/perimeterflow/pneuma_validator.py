import csv
from dataclasses import dataclass
import math
from pathlib import Path
from .estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate


@dataclass(frozen=True)
class PneumaValidationResult:
    slice_id: str
    penetration_rate: float
    nrmse_unstratified_pct: float
    nrmse_stratified_pcakf_pct: float
    closed_loop_actuation_supported: bool = False


def evaluate_pneuma_trajectory_slice(
    csv_path: Path,
    penetration_rate: float = 0.03,
) -> PneumaValidationResult:
    """
    Evaluates offline MFD accumulation estimation accuracy on a pNEUMA trajectory CSV slice.
    Explicitly enforces that closed-loop perimeter control cannot be counterfactually actuated
    on historical trajectory logs.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"pNEUMA trajectory slice not found: {csv_path}")

    pings_by_window: dict[int, list[ProbePing]] = {}
    true_n_by_window: dict[int, float] = {}

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t_s = float(row["timestamp_s"])
            w_idx = int(t_s // 60.0)
            true_n_by_window[w_idx] = float(row["true_accumulation_veh"])
            if int(row.get("is_sampled_probe", "1")) == 1:
                pings_by_window.setdefault(w_idx, []).append(
                    ProbePing(
                        veh_id=str(row["veh_id"]),
                        link_class=str(row["link_class"]),
                        timestamp_s=t_s,
                        x_obs_m=float(row["x_obs_m"]),
                        y_obs_m=float(row["y_obs_m"]),
                        speed_obs_ms=float(row["speed_obs_ms"]),
                        snap_dist_m=float(row.get("snap_dist_m", 1.0)),
                    )
                )

    windows = sorted(true_n_by_window.keys())
    kf = HysteresisAwarePCAKF(n_init=120.0, n_crit=350.0, n_jam=900.0, m_max_load=0.85)
    err_unstrat: list[float] = []
    err_prop: list[float] = []
    trues: list[float] = []

    for w in windows:
        w_pings = pings_by_window.get(w, [])
        gate_res = run_stateful_quality_gate(w_pings, GateConfig())

        unstrat_specs = {
            "arterial": NetworkClassSpec(length_km=6.0, estimated_penetration=penetration_rate),
            "local": NetworkClassSpec(length_km=12.0, estimated_penetration=penetration_rate),
        }
        strat_specs = {
            "arterial": NetworkClassSpec(length_km=6.0, estimated_penetration=min(0.9, penetration_rate * 2.0)),
            "local": NetworkClassSpec(length_km=12.0, estimated_penetration=max(0.002, penetration_rate * 0.5)),
        }

        _, _, n_unstrat = compute_stratified_edie(gate_res.segments, unstrat_specs)
        _, _, n_strat_ht = compute_stratified_edie(gate_res.segments, strat_specs)
        n_akf = kf.step(0.65, 1.0, n_strat_ht, penetration_rate, gate_res.rejection_rate)

        n_true = true_n_by_window[w]
        trues.append(n_true)
        err_unstrat.append(n_unstrat - n_true)
        err_prop.append(n_akf - n_true)

    span = max(1.0, max(trues) - min(trues))
    nrmse_u = (math.sqrt(sum(e ** 2 for e in err_unstrat) / len(trues)) / span) * 100.0
    nrmse_p = (math.sqrt(sum(e ** 2 for e in err_prop) / len(trues)) / span) * 100.0

    return PneumaValidationResult(
        slice_id=csv_path.stem,
        penetration_rate=penetration_rate,
        nrmse_unstratified_pct=nrmse_u,
        nrmse_stratified_pcakf_pct=nrmse_p,
        closed_loop_actuation_supported=False,
    )
