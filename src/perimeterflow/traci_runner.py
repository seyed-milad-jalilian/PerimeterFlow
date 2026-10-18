from collections import deque
from dataclasses import dataclass
import math
from pathlib import Path
from .controllers import ResidualCorrectedSmithPIController
from .estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from .prng import Mulberry32
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate


@dataclass(frozen=True)
class EpisodeConfig:
    seed: int
    penetration_rate: float = 0.02
    bias_mode: str = "corridor_biased"  # 'uniform' | 'corridor_biased'
    delay_s: float = 60.0
    variant: str = "G1_F1_C1"           # G{0,1}_F{0,1}_C{0,1}
    mfd_misspec_ratio: float = 0.0      # -0.20, 0.0, +0.20
    pen_est_error_ratio: float = 0.0    # -0.30, 0.0, +0.30
    kp_norm: float = 0.85
    ki_norm: float = 0.22


class FractionalObservationDelayBuffer:
    """
    Telemetry delay buffer supporting fractional (sub-window) observation delays.

    A delay of tau_d = (d_int + theta) * dt is applied by linearly interpolating the
    observation history: z_del(t) = (1 - theta) z(t - d_int) + theta z(t - d_int - 1),
    with all pre-episode history clamped to the initial accumulation n_init
    (z(s) = n_init for s < 0). At theta = 0 the delivered value is exactly
    z(t - d_int), matching the legacy integer-step buffer.
    """

    def __init__(self, delay_steps: int, delay_frac: float, n_init: float):
        self.delay_steps = max(0, int(delay_steps))
        self.delay_frac = float(delay_frac)
        self._history: list[float] = [float(n_init)]

    def push_and_read(self, z_t: float) -> float:
        self._history.append(z_t)
        t_now = len(self._history) - 2
        s_recent = t_now - self.delay_steps
        i_recent = s_recent + 1 if s_recent >= 0 else 0
        i_prev = s_recent if s_recent >= 1 else 0
        return (1.0 - self.delay_frac) * self._history[i_recent] + self.delay_frac * self._history[i_prev]



@dataclass(frozen=True)
class EpisodeResult:
    seed: int
    variant: str
    penetration_rate: float
    bias_mode: str
    delay_s: float
    nrmse_pct: float
    tnd_veh_h: float
    n_true_series: list[float]
    n_est_series: list[float]
    u_gate_series: list[float]


def run_closed_loop_episode(cfg: EpisodeConfig, work_dir: Path | None = None) -> EpisodeResult:
    """
    Executes a 90-minute (5400s, T=90 windows of 60s) closed-loop two-reservoir episode.
    Extracts 100% ground-truth accumulation, injects 4:1 arterial corridor sampling bias,
    Gaussian GPS noise, 3% multipath jumps, and Markovian burst dropouts, and actuates
    perimeter gating every 60s.
    """
    rng = Mulberry32(cfg.seed)
    use_gate = "G1" in cfg.variant
    use_filter = "F1" in cfg.variant
    use_smith = "C1" in cfg.variant
    dt_s = 60.0
    delay_s_val = max(0.0, float(cfg.delay_s))
    delay_steps = int(delay_s_val // dt_s)
    delay_frac = (delay_s_val - delay_steps * dt_s) / dt_s

    l_arterial_km = 9.6
    l_local_km = 19.2
    n_crit_true = 420.0
    n_jam_true = 1150.0
    m_max_true = 0.95

    n_crit_model = n_crit_true * (1.0 + cfg.mfd_misspec_ratio)
    m_max_model = m_max_true * (1.0 + cfg.mfd_misspec_ratio)

    if cfg.bias_mode == "corridor_biased":
        p_art_true = min(0.95, cfg.penetration_rate * 2.0)
        p_loc_true = max(0.002, cfg.penetration_rate * 0.5)
    else:
        p_art_true = cfg.penetration_rate
        p_loc_true = cfg.penetration_rate

    p_art_est = max(0.002, p_art_true * (1.0 + cfg.pen_est_error_ratio))
    p_loc_est = max(0.002, p_loc_true * (1.0 + cfg.pen_est_error_ratio))

    kf = HysteresisAwarePCAKF(
        n_init=140.0,
        n_crit=n_crit_model,
        n_jam=n_jam_true,
        m_max_load=m_max_model,
    )
    controller = ResidualCorrectedSmithPIController(
        n_crit=n_crit_model,
        kp_norm=cfg.kp_norm,
        ki_norm=cfg.ki_norm,
        delay_steps=delay_steps if use_smith else 0,
        delay_frac=delay_frac if use_smith else 0.0,
    )

    n_init = 140.0
    obs_delay_buffer: deque[float] = deque(maxlen=delay_steps + 1)
    frac_obs_buffer = FractionalObservationDelayBuffer(
        delay_steps=delay_steps,
        delay_frac=delay_frac,
        n_init=n_init,
    )
    n_true = n_init
    n_prev_true = n_init
    external_queue_veh = 0.0
    u_current = 1.0

    n_true_series: list[float] = []
    n_est_series: list[float] = []
    u_gate_series: list[float] = []
    total_delay_veh_s = 0.0

    for step_idx in range(90):
        t_window_start = step_idx * 60.0
        if t_window_start < 1200.0:
            q_demand_s = 0.72 + 0.05 * rng.next_gaussian()
        elif t_window_start < 3200.0:
            q_demand_s = 1.28 + 0.06 * rng.next_gaussian()
        else:
            q_demand_s = 0.38 + 0.03 * rng.next_gaussian()
        q_demand_s = max(0.1, q_demand_s)

        is_unloading_true = (n_true < n_prev_true) and (n_true > 0.75 * n_crit_true)
        m_peak = m_max_true * (0.81 if is_unloading_true else 1.0)
        if n_true <= n_crit_true:
            outflow_s = m_peak * (n_true / n_crit_true) * (2.0 - (n_true / n_crit_true))
        else:
            ratio = (n_true - n_crit_true) / (n_jam_true - n_crit_true)
            outflow_s = m_peak * max(0.05, 1.0 - ratio ** 2)

        inflow_admitted_s = q_demand_s * u_current + min(external_queue_veh / 60.0, 0.45 * u_current)
        external_queue_veh = max(0.0, external_queue_veh + 60.0 * (q_demand_s - inflow_admitted_s))

        n_prev_true = n_true
        n_true = max(20.0, min(n_jam_true, n_true + 60.0 * (inflow_admitted_s - outflow_s) + rng.next_gaussian(0.0, 3.5)))

        n_art_true = n_true * 0.46
        n_loc_true = n_true * 0.54
        v_art_true = max(2.2, 13.5 * (1.0 - 0.65 * (n_true / n_jam_true)))
        v_loc_true = max(1.5, 8.5 * (1.0 - 0.75 * (n_true / n_jam_true)))

        pings: list[ProbePing] = []
        n_art_probes = max(1, int(round(n_art_true * p_art_true)))
        n_loc_probes = max(0, int(round(n_loc_true * p_loc_true)))

        for cls_label, n_probes, v_cls in (("arterial", n_art_probes, v_art_true), ("local", n_loc_probes, v_loc_true)):
            for p_idx in range(n_probes):
                vid = f"{cls_label}_{step_idx}_{p_idx}"
                x_pos = 0.0
                for sub_t in range(0, 60, 5):
                    if rng.next_float() < 0.08:
                        continue
                    dt_step = 5.0
                    x_pos += v_cls * dt_step
                    noise_x = rng.next_gaussian(0.0, 2.5)
                    if rng.next_float() < 0.03:
                        noise_x += 55.0
                    pings.append(
                        ProbePing(
                            veh_id=vid,
                            link_class=cls_label,
                            timestamp_s=t_window_start + float(sub_t),
                            x_obs_m=x_pos + noise_x,
                            y_obs_m=0.0,
                            speed_obs_ms=max(0.0, v_cls + rng.next_gaussian(0.0, 0.8)),
                            snap_dist_m=abs(rng.next_gaussian(0.0, 3.0)),
                        )
                    )

        if use_gate:
            gate_res = run_stateful_quality_gate(pings, GateConfig())
            segments = gate_res.segments
            rej_rate = gate_res.rejection_rate
        else:
            gate_res = run_stateful_quality_gate(
                pings,
                GateConfig(v_max_ms=999.0, a_max_ms2=999.0, a_min_ms2=-999.0, max_map_snap_dist_m=999.0),
            )
            segments = gate_res.segments
            rej_rate = 0.0

        if use_filter:
            class_specs = {
                "arterial": NetworkClassSpec(length_km=l_arterial_km, estimated_penetration=p_art_est),
                "local": NetworkClassSpec(length_km=l_local_km, estimated_penetration=p_loc_est),
            }
            _, _, n_raw_ht = compute_stratified_edie(segments, class_specs, dt_window_s=60.0)
            n_est = kf.step(
                q_in_veh_s=q_demand_s,
                u_gate=u_current,
                z_obs_n=n_raw_ht,
                p_eff=cfg.penetration_rate,
                rejection_rate=rej_rate,
                dt_s=60.0,
            )
        else:
            uniform_specs = {
                "arterial": NetworkClassSpec(length_km=l_arterial_km, estimated_penetration=cfg.penetration_rate),
                "local": NetworkClassSpec(length_km=l_local_km, estimated_penetration=cfg.penetration_rate),
            }
            _, _, n_est = compute_stratified_edie(segments, uniform_specs, dt_window_s=60.0)

        if delay_frac == 0.0:
            obs_delay_buffer.append(n_est)
            n_delayed_obs = obs_delay_buffer[0]
        else:
            n_delayed_obs = frac_obs_buffer.push_and_read(n_est)

        u_current = controller.compute_u(
            n_delayed_obs=n_delayed_obs,
            q_in_current=q_demand_s,
            kf_model=kf,
            dt_s=60.0,
        )

        freeflow_speed = 11.5
        avg_net_speed = (n_art_true * v_art_true + n_loc_true * v_loc_true) / max(1.0, n_true)
        in_net_delay_s = n_true * 60.0 * max(0.0, 1.0 - (avg_net_speed / freeflow_speed))
        queue_delay_s = external_queue_veh * 60.0
        total_delay_veh_s += in_net_delay_s + queue_delay_s

        n_true_series.append(n_true)
        n_est_series.append(n_est)
        u_gate_series.append(u_current)

    rmse = math.sqrt(sum((est - tru) ** 2 for est, tru in zip(n_est_series, n_true_series)) / len(n_true_series))
    denom = max(1.0, max(n_true_series) - min(n_true_series))
    nrmse_pct = (rmse / denom) * 100.0
    tnd_veh_h = total_delay_veh_s / 3600.0

    return EpisodeResult(
        seed=cfg.seed,
        variant=cfg.variant,
        penetration_rate=cfg.penetration_rate,
        bias_mode=cfg.bias_mode,
        delay_s=cfg.delay_s,
        nrmse_pct=nrmse_pct,
        tnd_veh_h=tnd_veh_h,
        n_true_series=n_true_series,
        n_est_series=n_est_series,
        u_gate_series=u_gate_series,
    )
