from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class GateConfig:
    v_max_ms: float = 22.22           # 80 km/h urban speed ceiling
    a_max_ms2: float = 4.5            # Max plausible urban acceleration
    a_min_ms2: float = -6.5           # Max plausible emergency deceleration
    max_dt_gap_s: float = 15.0        # Segment reset gap threshold
    max_map_snap_dist_m: float = 12.0 # Max perpendicular distance to road axis


@dataclass(frozen=True)
class ProbePing:
    veh_id: str
    link_class: str                   # 'arterial' | 'local'
    timestamp_s: float
    x_obs_m: float
    y_obs_m: float
    speed_obs_ms: float
    snap_dist_m: float


@dataclass(frozen=True)
class AcceptedSegment:
    veh_id: str
    link_class: str
    timestamp_s: float
    tau_s: float                      # Valid travel time increment
    d_m: float                        # Valid travel distance increment


@dataclass(frozen=True)
class GateSummary:
    segments: list[AcceptedSegment]
    rejection_rate: float
    total_pings: int
    rejected_spatial: int
    rejected_kinematic: int


@dataclass
class _VehAnchor:
    t: float
    x: float
    y: float
    v: float


def run_stateful_quality_gate(pings: Iterable[ProbePing], cfg: GateConfig = GateConfig()) -> GateSummary:
    """
    Sequential kinematic filter.
    Compares incoming pings strictly against the LAST ACCEPTED VALID observation,
    preventing an isolated GPS outlier from invalidating the subsequent true observation.
    """
    sorted_pings = sorted(pings, key=lambda p: (p.veh_id, p.timestamp_s))
    anchors: dict[str, _VehAnchor] = {}
    accepted: list[AcceptedSegment] = []

    total = 0
    rej_spatial = 0
    rej_kinematic = 0

    for p in sorted_pings:
        total += 1
        if p.snap_dist_m > cfg.max_map_snap_dist_m or math.isnan(p.x_obs_m) or math.isnan(p.y_obs_m):
            rej_spatial += 1
            continue

        state = anchors.get(p.veh_id)
        if state is None or (p.timestamp_s - state.t) > cfg.max_dt_gap_s:
            if 0.0 <= p.speed_obs_ms <= cfg.v_max_ms:
                anchors[p.veh_id] = _VehAnchor(p.timestamp_s, p.x_obs_m, p.y_obs_m, p.speed_obs_ms)
                accepted.append(AcceptedSegment(p.veh_id, p.link_class, p.timestamp_s, 0.0, 0.0))
            else:
                rej_kinematic += 1
            continue

        dt = p.timestamp_s - state.t
        if dt <= 0.0:
            rej_kinematic += 1
            continue

        dist = math.hypot(p.x_obs_m - state.x, p.y_obs_m - state.y)
        v_calc = dist / dt
        a_calc = (v_calc - state.v) / dt

        if (v_calc < 0.0) or (v_calc > cfg.v_max_ms) or (a_calc > cfg.a_max_ms2) or (a_calc < cfg.a_min_ms2):
            rej_kinematic += 1
            continue

        anchors[p.veh_id] = _VehAnchor(p.timestamp_s, p.x_obs_m, p.y_obs_m, v_calc)
        accepted.append(AcceptedSegment(p.veh_id, p.link_class, p.timestamp_s, dt, dist))

    rej_rate = float(rej_spatial + rej_kinematic) / float(total) if total > 0 else 1.0
    return GateSummary(accepted, rej_rate, total, rej_spatial, rej_kinematic)
