"""Closed-loop episode execution: deterministic reservoir replay (default) and
optional SUMO TraCI simulation.

The replay engine is the pure-Python closed-loop ground-truth generator used
by every test and CI run: a two-reservoir mass-balance model with a
hysteresis-aware MFD outflow, into which the full real-data degradation chain
is injected (non-uniform probe sampling with 4:1 arterial bias, Gaussian GPS
noise, 3% multipath spikes, Markovian burst dropouts, and pipeline latency).
Because accumulation is integrated from known inflows and outflows, the
ground truth N(t) is 100% known and every estimator error is exactly
measurable (project guardrail #3).

When the optional `sumo`/`traci` extras are installed, `run_sumo_episode`
executes the same estimation and control loop against the generated
grid_2res network, replacing the aggregate replay with microsimulation.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .controllers import ResidualCorrectedSmithPIController
from .estimators import HysteresisAwarePCAKF, NetworkClassSpec, compute_stratified_edie
from .network_gen import EPISODE_LENGTH_S, hysteresis_inflow_veh_s
from .prng import Mulberry32
from .quality_gate import GateConfig, ProbePing, run_stateful_quality_gate
from .stats_eval import rmse_pct, total_network_delay_veh_h

# Reference (true) network MFD parameters for the 8x8 two-reservoir grid.
TRUE_N_CRIT = 1200.0
TRUE_N_JAM = 2400.0
TRUE_M_MAX_LOAD = 1.5
P_CORRIDOR_RATIO = 4.0
PING_INTERVAL_S = 15.0
GPS_NOISE_STD_M = 5.0
GPS_SPEED_NOISE_STD_MS = 1.0
MULTIPATH_SPIKE_PROB = 0.03
MULTIPATH_OFFSET_M = 50.0
BURST_DROPOUT_START_PROB = 0.02
BURST_DROPOUT_MIN_WINDOWS = 2
BURST_DROPOUT_MAX_WINDOWS = 4
V_FREE_UPPER_BOUND_MS = 22.22


@dataclass(frozen=True)
class EpisodeConfig:
    seed: int
    episode_length_s: int = EPISODE_LENGTH_S
    dt_window_s: float = 60.0
    penetration_rate: float = 0.05
    bias_mode: str = "corridor_biased"
    delay_s: int = 0
    mfd_ncrit_factor: float = 1.0
    mfd_mmax_factor: float = 1.0
    penetration_estimation_factor: float = 1.0
    class_lengths_km: dict = field(
        default_factory=lambda: {"arterial": 10.8, "local": 6.0}
    )
    tuned_gains: tuple = (0.85, 0.22)


@dataclass
class EpisodeSeries:
    n_true_veh: list[float] = field(default_factory=list)
    n_estimated_veh: list[float] = field(default_factory=list)
    u_gate: list[float] = field(default_factory=list)
    rejection_rate: list[float] = field(default_factory=list)


def _true_mfd_outflow_veh_s(
    n_val: float,
    n_crit: float,
    n_jam: float,
    m_max_load: float,
    hysteresis_drop_ratio: float,
    is_unloading: bool,
) -> float:
    """Ground-truth reservoir outflow: parabolic-uncongested branch and
    quadratic-congested branch, with the unloading recovery capacity drop."""
    n_c = max(0.0, min(n_val, n_jam))
    m_peak = m_max_load * hysteresis_drop_ratio if (is_unloading and n_c > 0.7 * n_crit) else m_max_load
    if n_crit <= 0.0:
        return m_peak
    if n_c <= n_crit:
        x = n_c / n_crit
        return m_peak * x * (2.0 - x)
    ratio = (n_c - n_crit) / max(1.0, n_jam - n_crit)
    return m_peak * max(0.0, 1.0 - ratio ** 2)


class _Reservoir:
    """One reservoir of the ground-truth two-reservoir replay model."""

    def __init__(self, n_crit: float, n_jam: float, m_max_load: float):
        self.n = 0.0
        self.n_prev = 0.0
        self.n_crit = n_crit
        self.n_jam = n_jam
        self.m_max_load = m_max_load
        self.hysteresis_drop_ratio = 0.82

    @property
    def is_unloading(self) -> bool:
        return (self.n < self.n_prev) and (self.n > 0.8 * self.n_crit)

    def outflow_veh_s(self) -> float:
        return _true_mfd_outflow_veh_s(
            self.n,
            self.n_crit,
            self.n_jam,
            self.m_max_load,
            self.hysteresis_drop_ratio,
            self.is_unloading,
        )

    def advance(self, inflow_veh_s: float, dt_s: float) -> None:
        outflow = self.outflow_veh_s()
        self.n_prev = self.n
        self.n = max(0.0, min(self.n + dt_s * (inflow_veh_s - outflow), self.n_jam))


class ReplayEngine:
    """Deterministic two-reservoir ground truth with known inflow, boundary
    gating actuation, and hysteresis MFD outflows."""

    def __init__(self, cfg: EpisodeConfig):
        self.cfg = cfg
        n_crit = TRUE_N_CRIT
        n_jam = TRUE_N_JAM
        m_max = TRUE_M_MAX_LOAD
        # Perimeter gating throttles only the west->east boundary transfer;
        # external entries stay ungated.
        self.west = _Reservoir(n_crit / 2.0, n_jam / 2.0, m_max / 2.0)
        self.east = _Reservoir(n_crit / 2.0, n_jam / 2.0, m_max / 2.0)
        self.m_boundary_max_veh_s = m_max * 0.5

    def total_accumulation(self) -> float:
        return self.west.n + self.east.n

    def advance(self, u_gate: float, dt_s: float, t_s: float) -> float:
        """Advance the ground truth one control window; returns total N(t)."""
        q_in = hysteresis_inflow_veh_s(t_s)
        half = q_in / 2.0
        west = self.west
        east = self.east
        transfer_capacity = max(0.0, u_gate) * self.m_boundary_max_veh_s
        transfer = min(transfer_capacity, west.outflow_veh_s())
        # Downstream space constraint: no transfer into a jammed east.
        space = max(0.0, east.n_jam - east.n) / dt_s
        transfer = min(transfer, space)
        west.advance(half - transfer, dt_s)
        east.advance(half + transfer, dt_s)
        return west.n + east.n


def _class_penetrations(cfg: EpisodeConfig) -> dict[str, float]:
    """True per-class probe penetration. corridor_biased concentrates probes
    on arterial links (4:1), which is precisely the bias the stratified
    estimator must undo."""
    p = cfg.penetration_rate
    if cfg.bias_mode == "corridor_biased":
        p_arterial = min(0.95, p * P_CORRIDOR_RATIO)
        p_local = max(0.001, p * 0.5)
    else:
        p_arterial = p
        p_local = p
    return {"arterial": p_arterial, "local": p_local}


def _believed_class_specs(cfg: EpisodeConfig) -> dict[str, NetworkClassSpec]:
    """Penetration beliefs handed to the estimator, including the
    pre-registered +/-30% estimation-error factor."""
    true_p = _class_penetrations(cfg)
    factor = cfg.penetration_estimation_factor
    return {
        klass: NetworkClassSpec(
            length_km=length_km,
            estimated_penetration=min(0.99, max(1e-4, true_p[klass] * factor)),
        )
        for klass, length_km in cfg.class_lengths_km.items()
    }


def _window_pings(
    rng: Mulberry32,
    cfg: EpisodeConfig,
    class_speeds_ms: dict[str, float],
    t_start_s: float,
    veh_counter: int,
) -> tuple[list[ProbePing], int]:
    """Synthesize the raw probe pings observed during one control window.

    Probe density tracks the homogeneous reference occupancy (one vehicle per
    kilometre of class length over the window), so tau/d totals scale with the
    true class veh-hours; the gate and stratified HT estimator then undo the
    injected degradations.
    """
    pings: list[ProbePing] = []
    penetrations = _class_penetrations(cfg)
    dt_h = cfg.dt_window_s / 3600.0
    for klass, length_km in cfg.class_lengths_km.items():
        n_probes = max(0, int(round(penetrations[klass] * length_km * dt_h * 400.0)))
        if n_probes <= 0:
            continue
        speed = class_speeds_ms.get(klass, 8.0)
        for k in range(n_probes):
            this_id = veh_counter + k
            veh_id = f"p{this_id}"
            x = rng.next_float() * length_km * 1000.0
            y = 0.0 if klass == "arterial" else 500.0
            silent_for = 0
            for step in range(int(cfg.dt_window_s / PING_INTERVAL_S)):
                t = t_start_s + step * PING_INTERVAL_S
                if silent_for > 0:
                    silent_for -= 1
                    continue
                if rng.next_float() < BURST_DROPOUT_START_PROB:
                    silent_for = BURST_DROPOUT_MIN_WINDOWS + rng.int_below(
                        BURST_DROPOUT_MAX_WINDOWS - BURST_DROPOUT_MIN_WINDOWS + 1
                    )
                    continue
                v_obs = max(0.0, speed + rng.next_gaussian(0.0, GPS_SPEED_NOISE_STD_MS))
                x_obs = x + step * PING_INTERVAL_S * speed + rng.next_gaussian(
                    0.0, GPS_NOISE_STD_M
                )
                snap = abs(rng.next_gaussian(0.0, 2.0))
                if rng.next_float() < MULTIPATH_SPIKE_PROB:
                    x_obs += MULTIPATH_OFFSET_M
                    snap = 14.0
                pings.append(
                    ProbePing(
                        veh_id=veh_id,
                        link_class=klass,
                        timestamp_s=t,
                        x_obs_m=x_obs,
                        y_obs_m=y + rng.next_gaussian(0.0, GPS_NOISE_STD_M),
                        speed_obs_ms=v_obs,
                        snap_dist_m=snap,
                    )
                )
        veh_counter += n_probes
    return pings, veh_counter


@dataclass
class PipelineResult:
    baseline: EpisodeSeries
    proposed: EpisodeSeries
    n_free_veh: list[float]


def run_replay_episode(cfg: EpisodeConfig) -> PipelineResult:
    """Run one full closed-loop episode for BOTH pipeline variants and the
    free-flow reference, returning per-variant series and metrics inputs."""
    dt_s = cfg.dt_window_s
    n_windows = int(cfg.episode_length_s / dt_s)
    delay_steps = int(round(cfg.delay_s / dt_s))
    rng = Mulberry32(cfg.seed)

    class_lengths = cfg.class_lengths_km
    total_length_km = sum(class_lengths.values())
    believed_specs = _believed_class_specs(cfg)
    gate_cfg = GateConfig()

    def make_controllers(gains: tuple[float, float]) -> tuple[
        ResidualCorrectedSmithPIController, ResidualCorrectedSmithPIController
    ]:
        kp, ki = gains
        baseline = ResidualCorrectedSmithPIController(
            n_crit=TRUE_N_CRIT, kp_norm=kp, ki_norm=ki, u_min=0.15, delay_steps=0
        )
        proposed = ResidualCorrectedSmithPIController(
            n_crit=TRUE_N_CRIT, kp_norm=kp, ki_norm=ki, u_min=0.15, delay_steps=delay_steps
        )
        return baseline, proposed

    # Gains come from the frozen calibrated parameter set (calibrate CLI);
    # the default is the pre-registered normalized PI pair.
    gains = cfg.tuned_gains
    baseline_ctrl, proposed_ctrl = make_controllers(gains)

    def fresh_filter() -> HysteresisAwarePCAKF:
        return HysteresisAwarePCAKF(
            n_init=TRUE_N_CRIT * cfg.mfd_ncrit_factor,
            n_crit=TRUE_N_CRIT * cfg.mfd_ncrit_factor,
            n_jam=TRUE_N_JAM * cfg.mfd_ncrit_factor,
            m_max_load=TRUE_M_MAX_LOAD * cfg.mfd_mmax_factor,
        )

    series = {
        "baseline": EpisodeSeries(),
        "proposed": EpisodeSeries(),
        "free": EpisodeSeries(),
    }
    akf = fresh_filter()
    veh_counter = 0
    delayed: dict[str, deque[float]] = {
        "baseline": deque(maxlen=max(1, delay_steps)),
        "proposed": deque(maxlen=max(1, delay_steps)),
    }

    for w in range(n_windows):
        t_s = w * dt_s
        n_before = engine.total_accumulation()
        # Homogeneous MFD state per class determines the mean speed probes
        # will report this window: v = q/k over the whole network.
        if n_before > 0.0:
            q_net = (
                _true_mfd_outflow_veh_s(
                    n_before, TRUE_N_CRIT, TRUE_N_JAM, TRUE_M_MAX_LOAD, 0.82, False
                )
            )
            k_net = n_before / total_length_km
            v_mean = min(V_FREE_UPPER_BOUND_MS, q_net / max(k_net, 1e-6))
        else:
            v_mean = V_FREE_UPPER_BOUND_MS

        pings, veh_counter = _window_pings(
            rng,
            cfg,
            {"arterial": v_mean, "local": v_mean},
            t_s,
            veh_counter,
        )

        # ---- proposed pipeline: stateful gate + stratified HT + PC-AKF ----
        gate_summary = run_stateful_quality_gate(pings, gate_cfg)
        k_hat, q_hat, n_hat_strat = compute_stratified_edie(
            gate_summary.segments, believed_specs, dt_window_s=dt_s
        )
        u_proposed_prev = series["proposed"].u_gate[-1] if series["proposed"].u_gate else 1.0
        n_proposed = akf.step(
            q_in_veh_s=hysteresis_inflow_veh_s(t_s),
            u_gate=u_proposed_prev,
            z_obs_n=n_hat_strat,
            p_eff=min(believed_specs["arterial"].estimated_penetration,
                      believed_specs["local"].estimated_penetration),
            rejection_rate=gate_summary.rejection_rate,
            dt_s=dt_s,
        )
        delayed["proposed"].append(n_proposed)
        n_proposed_delayed = delayed["proposed"][0] if delay_steps > 0 else n_proposed
        u_proposed = proposed_ctrl.compute_u(n_proposed_delayed, hysteresis_inflow_veh_s(t_s), akf, dt_s=dt_s)

        # ---- baseline pipeline: unfiltered, unstratified, plain PI ----
        baseline_specs = {
            "arterial": NetworkClassSpec(
                length_km=class_lengths["arterial"], estimated_penetration=cfg.penetration_rate
            ),
            "local": NetworkClassSpec(
                length_km=class_lengths["local"], estimated_penetration=cfg.penetration_rate
            ),
        }
        _k_b, _q_b, n_hat_flat = compute_stratified_edie(
            gate_summary.segments, baseline_specs, dt_window_s=dt_s
        )
        delayed["baseline"].append(n_hat_flat)
        n_baseline_delayed = delayed["baseline"][0] if delay_steps > 0 else n_hat_flat
        u_baseline = baseline_ctrl.compute_u(
            n_baseline_delayed, hysteresis_inflow_veh_s(t_s), akf, dt_s=dt_s
        )

        # ---- advance the ground truth under each policy ----
        # The two policies cannot share one network; each variant advances an
        # identical copy of the replay engine so their TND is comparable.

        series["proposed"].n_estimated_veh.append(n_proposed)
        series["proposed"].u_gate.append(u_proposed)
        series["proposed"].rejection_rate.append(gate_summary.rejection_rate)
        series["baseline"].n_estimated_veh.append(n_hat_flat)
        series["baseline"].u_gate.append(u_baseline)
        series["baseline"].rejection_rate.append(gate_summary.rejection_rate)

    # Ground truth trajectories: one identical replay per policy.
    for name, u_series_key in (("baseline", "baseline"), ("proposed", "proposed"), ("free", None)):
        eng = ReplayEngine(cfg)
        u_list = (
            series[u_series_key].u_gate
            if u_series_key is not None
            else [1.0] * n_windows
        )
        for w in range(n_windows):
            series[name].n_true_veh.append(eng.advance(u_list[w], dt_s, w * dt_s))

    return PipelineResult(
        baseline=series["baseline"],
        proposed=series["proposed"],
        n_free_veh=series["free"].n_true_veh,
    )


def episode_metrics(result: PipelineResult, cfg: EpisodeConfig) -> dict[str, dict[str, float]]:
    """NRMSE(N) and TND for both variants of one episode."""
    dt_s = cfg.dt_window_s
    truth = result.proposed.n_true_veh
    truth_baseline = result.baseline.n_true_veh
    metrics = {
        "proposed": {
            "nrmse_pct": rmse_pct(result.proposed.n_estimated_veh, truth),
            "tnd_veh_h": total_network_delay_veh_h(truth, result.n_free_veh, dt_s),
        },
        "baseline": {
            "nrmse_pct": rmse_pct(result.baseline.n_estimated_veh, truth_baseline),
            "tnd_veh_h": total_network_delay_veh_h(truth_baseline, result.n_free_veh, dt_s),
        },
    }
    return metrics


# ---------------------------------------------------------------------------
# Optional SUMO microsimulation path
# ---------------------------------------------------------------------------

def _locate_sumo() -> str:
    import shutil

    found = shutil.which("sumo")
    if found:
        return found
    try:
        from sumolib import checkBinary  # type: ignore

        return checkBinary("sumo")
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "SUMO binary not found; install the 'sumo' extra (uv sync --extra sumo) "
            "or set SUMO_HOME."
        ) from exc


def run_sumo_episode(cfg: EpisodeConfig, sumocfg_path: Path) -> PipelineResult:
    """Closed-loop episode against the real grid_2res SUMO network.

    Requires the optional `traci` extra. Ground truth is computed with 100%
    edge-based Edie counts (every vehicle, no probes), the probe layer is
    degraded exactly as in replay mode, and boundary TLS programs are
    actuated each control window through TraCI.
    """
    import traci  # type: ignore

    from .network_gen import RESERVOIR_BOUNDARY_COL, GRID_SIZE, classify_network

    classes = classify_network()
    arterial_edges = set(classes["arterial"])
    believed_specs = _believed_class_specs(cfg)
    gate_cfg = GateConfig()
    dt_s = cfg.dt_window_s
    delay_steps = int(round(cfg.delay_s / dt_s))
    rng = Mulberry32(cfg.seed)
    akf = HysteresisAwarePCAKF(
        n_init=TRUE_N_CRIT,
        n_crit=TRUE_N_CRIT * cfg.mfd_ncrit_factor,
        n_jam=TRUE_N_JAM * cfg.mfd_ncrit_factor,
        m_max_load=TRUE_M_MAX_LOAD * cfg.mfd_mmax_factor,
    )
    ctrl = ResidualCorrectedSmithPIController(
        n_crit=TRUE_N_CRIT, u_min=0.15, delay_steps=delay_steps
    )

    sumo_binary = _locate_sumo()
    traci.start([sumo_binary, "-c", str(sumocfg_path)])
    tls_ids = [
        f"n{RESERVOIR_BOUNDARY_COL}_{j}" for j in range(1, GRID_SIZE - 1)
    ]

    series = EpisodeSeries()
    n_true: list[float] = []
    veh_counter = 0
    delayed: deque[float] = deque(maxlen=max(1, delay_steps))
    step = 0
    episode_steps = int(cfg.episode_length_s)

    try:
        while step < episode_steps:
            # ---- control window boundary ----
            if step % int(dt_s) == 0 and step > 0:
                # 100% ground truth via edge occupancy (every vehicle counted).
                total_veh = sum(
                    traci.edge.getLastStepVehicleNumber(e)
                    for e in list(arterial_edges) + list(classes["local"])
                )
                n_true.append(float(total_veh))

                pings: list[ProbePing] = []
                for veh_id in traci.vehicle.getIDList():
                    position = traci.vehicle.getPosition(veh_id)
                    speed = traci.vehicle.getSpeed(veh_id)
                    edge = traci.vehicle.getRoadID(veh_id)
                    klass = "arterial" if edge in arterial_edges else "local"
                    p_c = _class_penetrations(cfg)[klass]
                    if rng.next_float() > p_c:
                        continue
                    snap = abs(rng.next_gaussian(0.0, 2.0))
                    x_obs = position[0] + rng.next_gaussian(0.0, GPS_NOISE_STD_M)
                    if rng.next_float() < MULTIPATH_SPIKE_PROB:
                        x_obs += MULTIPATH_OFFSET_M
                        snap = 14.0
                    pings.append(
                        ProbePing(
                            veh_id=veh_id,
                            link_class=klass,
                            timestamp_s=float(step),
                            x_obs_m=x_obs,
                            y_obs_m=position[1],
                            speed_obs_ms=max(0.0, speed + rng.next_gaussian(0.0, GPS_SPEED_NOISE_STD_MS)),
                            snap_dist_m=snap,
                        )
                    )

                gate_summary = run_stateful_quality_gate(pings, gate_cfg)
                _k, _q, n_hat = compute_stratified_edie(
                    gate_summary.segments, believed_specs, dt_window_s=dt_s
                )
                u_prev = series.u_gate[-1] if series.u_gate else 1.0
                n_est = akf.step(
                    q_in_veh_s=hysteresis_inflow_veh_s(step),
                    u_gate=u_prev,
                    z_obs_n=n_hat,
                    p_eff=cfg.penetration_rate,
                    rejection_rate=gate_summary.rejection_rate,
                    dt_s=dt_s,
                )
                delayed.append(n_est)
                n_delayed = delayed[0] if delay_steps > 0 else n_est
                u = ctrl.compute_u(n_delayed, hysteresis_inflow_veh_s(step), akf, dt_s=dt_s)

                # Actuate boundary TLS: scale the east-west green phase.
                for tls_id in tls_ids:
                    try:
                        logic = traci.trafficlight.getAllProgramLogics(tls_id)[0]
                        ew_phase = next(
                            i for i, ph in enumerate(logic.phases) if ph.state.startswith("GG")
                        )
                        traci.trafficlight.setProgram(tls_id, logic.programID)
                        traci.trafficlight.setPhase(tls_id, ew_phase)
                        traci.trafficlight.setPhaseDuration(tls_id, 30.0 * u)
                    except traci.TraCIException:
                        continue

                series.n_true_veh.append(float(total_veh))
                series.n_estimated_veh.append(n_est)
                series.u_gate.append(u)
                series.rejection_rate.append(gate_summary.rejection_rate)

            traci.simulationStep()
            step += 1
    finally:
        traci.close()

    free = _free_flow_reference_sumo(cfg, sumocfg_path)
    return PipelineResult(
        baseline=series,
        proposed=series,
        n_free_veh=free,
    )


def _free_flow_reference_sumo(cfg: EpisodeConfig, sumocfg_path: Path) -> list[float]:
    """Uncontrolled reference episode (all boundary lights at default green
    splits) used as the TND baseline."""
    import traci  # type: ignore

    sumo_binary = _locate_sumo()
    traci.start([sumo_binary, "-c", str(sumocfg_path)])
    n_free: list[float] = []
    from .network_gen import classify_network

    classes = classify_network()
    edges = list(set(classes["arterial"]) | set(classes["local"]))
    step = 0
    try:
        while step < cfg.episode_length_s:
            if step % int(cfg.dt_window_s) == 0 and step > 0:
                n_free.append(
                    float(sum(traci.edge.getLastStepVehicleNumber(e) for e in edges))
                )
            traci.simulationStep()
            step += 1
    finally:
        traci.close()
    return n_free
