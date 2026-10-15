export class Mulberry32 {
  private state: number;
  constructor(seed: number) {
    this.state = seed >>> 0;
  }
  public nextFloat(): number {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let t = this.state;
    t = Math.imul(t ^ (t >>> 15), t | 1) >>> 0;
    t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
    t = (t ^ (t >>> 14)) >>> 0;
    return t / 4294967296.0;
  }
  public nextGaussian(mean = 0.0, std = 1.0): number {
    const u1 = Math.max(1e-12, this.nextFloat());
    const u2 = this.nextFloat();
    const z0 = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
    return mean + z0 * std;
  }
}

export interface ProbePing {
  readonly veh_id: string;
  readonly link_class: "arterial" | "local";
  readonly timestamp_s: number;
  readonly x_obs_m: number;
  readonly y_obs_m: number;
  readonly speed_obs_ms: number;
  readonly snap_dist_m: number;
}

export interface AcceptedSegment {
  readonly veh_id: string;
  readonly link_class: "arterial" | "local";
  readonly timestamp_s: number;
  readonly tau_s: number;
  readonly d_m: number;
}

export interface GateConfig {
  readonly v_max_ms: number;
  readonly a_max_ms2: number;
  readonly a_min_ms2: number;
  readonly max_dt_gap_s: number;
  readonly max_map_snap_dist_m: number;
}

export const DEFAULT_GATE_CONFIG: GateConfig = {
  v_max_ms: 22.22,
  a_max_ms2: 4.5,
  a_min_ms2: -6.5,
  max_dt_gap_s: 15.0,
  max_map_snap_dist_m: 12.0,
};

interface VehAnchor {
  t: number;
  x: number;
  y: number;
  v: number;
}

export function runStatefulQualityGate(
  pings: readonly ProbePing[],
  cfg: GateConfig = DEFAULT_GATE_CONFIG
): { segments: AcceptedSegment[]; rejection_rate: number } {
  const sorted = [...pings].sort((a, b) =>
    a.veh_id === b.veh_id ? a.timestamp_s - b.timestamp_s : a.veh_id.localeCompare(b.veh_id)
  );
  const anchors = new Map<string, VehAnchor>();
  const segments: AcceptedSegment[] = [];
  let rejected = 0;

  for (const p of sorted) {
    if (p.snap_dist_m > cfg.max_map_snap_dist_m || Number.isNaN(p.x_obs_m) || Number.isNaN(p.y_obs_m)) {
      rejected += 1;
      continue;
    }
    const state = anchors.get(p.veh_id);
    if (state === undefined || p.timestamp_s - state.t > cfg.max_dt_gap_s) {
      if (p.speed_obs_ms >= 0.0 && p.speed_obs_ms <= cfg.v_max_ms) {
        anchors.set(p.veh_id, { t: p.timestamp_s, x: p.x_obs_m, y: p.y_obs_m, v: p.speed_obs_ms });
        segments.push({ veh_id: p.veh_id, link_class: p.link_class, timestamp_s: p.timestamp_s, tau_s: 0.0, d_m: 0.0 });
      } else {
        rejected += 1;
      }
      continue;
    }

    const dt = p.timestamp_s - state.t;
    if (dt <= 0.0) {
      rejected += 1;
      continue;
    }
    const dist = Math.hypot(p.x_obs_m - state.x, p.y_obs_m - state.y);
    const vCalc = dist / dt;
    const aCalc = (vCalc - state.v) / dt;

    if (vCalc < 0.0 || vCalc > cfg.v_max_ms || aCalc > cfg.a_max_ms2 || aCalc < cfg.a_min_ms2) {
      rejected += 1;
      continue;
    }

    anchors.set(p.veh_id, { t: p.timestamp_s, x: p.x_obs_m, y: p.y_obs_m, v: vCalc });
    segments.push({ veh_id: p.veh_id, link_class: p.link_class, timestamp_s: p.timestamp_s, tau_s: dt, d_m: dist });
  }

  const rejectionRate = sorted.length > 0 ? rejected / sorted.length : 1.0;
  return { segments, rejection_rate: rejectionRate };
}
