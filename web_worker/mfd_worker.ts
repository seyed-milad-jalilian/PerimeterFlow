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

export interface NetworkClassSpec {
  readonly length_km: number;
  readonly estimated_penetration: number;
}

export interface StratifiedEdieResult {
  readonly k_hat_veh_km: number;
  readonly q_hat_veh_h: number;
  readonly n_hat_veh: number;
}

export function computeStratifiedEdie(
  segments: readonly AcceptedSegment[],
  class_specs: Readonly<Record<string, NetworkClassSpec>>,
  dt_window_s: number = 60.0,
  p_min: number = 0.005
): StratifiedEdieResult {
  const class_keys = Object.keys(class_specs);
  let total_length_km = 0.0;
  for (const key of class_keys) {
    total_length_km += class_specs[key].length_km;
  }
  if (total_length_km <= 0.0) {
    throw new Error("Total network length must be positive");
  }

  const tau_by_class = new Map<string, number>();
  const d_by_class = new Map<string, number>();
  for (const key of class_keys) {
    tau_by_class.set(key, 0.0);
    d_by_class.set(key, 0.0);
  }

  for (const seg of segments) {
    const tau = tau_by_class.get(seg.link_class);
    const d = d_by_class.get(seg.link_class);
    if (tau !== undefined && d !== undefined) {
      tau_by_class.set(seg.link_class, tau + seg.tau_s);
      d_by_class.set(seg.link_class, d + seg.d_m / 1000.0);
    }
  }

  let n_hat_total = 0.0;
  let weighted_flow_sum = 0.0;
  const dt_hours = dt_window_s / 3600.0;

  for (const key of class_keys) {
    const spec = class_specs[key];
    const p_c = Math.max(spec.estimated_penetration, p_min);
    const total_veh_hours_c = (tau_by_class.get(key) as number) / 3600.0 / p_c;
    const total_veh_km_c = (d_by_class.get(key) as number) / p_c;

    n_hat_total += total_veh_hours_c / dt_hours;
    weighted_flow_sum += total_veh_km_c / dt_hours;
  }

  const k_hat = n_hat_total / total_length_km;
  const q_hat = weighted_flow_sum / total_length_km;
  return { k_hat_veh_km: k_hat, q_hat_veh_h: q_hat, n_hat_veh: n_hat_total };
}

export interface HysteresisAwarePCAKFParams {
  readonly n_init: number;
  readonly n_crit: number;
  readonly n_jam: number;
  readonly m_max_load: number;
  readonly hysteresis_drop_ratio?: number;
  readonly q_var?: number;
  readonly r_base?: number;
  readonly alpha_gate?: number;
}

export class HysteresisAwarePCAKF {
  readonly n_crit: number;
  readonly n_jam: number;
  readonly m_max_load: number;
  readonly m_max_unload: number;
  readonly q_var: number;
  readonly r_base: number;
  readonly alpha_gate: number;
  n_est: number;
  n_prev: number;
  p_cov: number;

  constructor(params: HysteresisAwarePCAKFParams) {
    this.n_est = params.n_init;
    this.n_prev = params.n_init;
    this.p_cov = 80.0;
    this.n_crit = params.n_crit;
    this.n_jam = params.n_jam;
    this.m_max_load = params.m_max_load;
    this.m_max_unload = params.m_max_load * (params.hysteresis_drop_ratio ?? 0.82);
    this.q_var = params.q_var ?? 20.0;
    this.r_base = params.r_base ?? 120.0;
    this.alpha_gate = params.alpha_gate ?? 2.5;
  }

  public mfdOutflow(n_val: number, is_unloading: boolean = false): number {
    const n_c = Math.max(0.0, Math.min(n_val, this.n_jam));
    const m_peak =
      is_unloading && n_c > 0.7 * this.n_crit ? this.m_max_unload : this.m_max_load;
    if (n_c <= this.n_crit) {
      return m_peak * (n_c / this.n_crit) * (2.0 - n_c / this.n_crit);
    }
    const ratio = (n_c - this.n_crit) / Math.max(1.0, this.n_jam - this.n_crit);
    return m_peak * Math.max(0.0, 1.0 - ratio * ratio);
  }

  public step(
    q_in_veh_s: number,
    u_gate: number,
    z_obs_n: number | null,
    p_eff: number,
    rejection_rate: number,
    dt_s: number = 60.0
  ): number {
    const is_unloading = this.n_est < this.n_prev && this.n_est > 0.8 * this.n_crit;
    const outflow = this.mfdOutflow(this.n_est, is_unloading);
    const n_pred = Math.max(
      0.0,
      Math.min(this.n_est + dt_s * (q_in_veh_s * u_gate - outflow), this.n_jam)
    );

    const eps = 1.0;
    const d_phi = (this.mfdOutflow(this.n_est + eps, is_unloading) - outflow) / eps;
    const f_jac = 1.0 - dt_s * d_phi;
    const p_pred = f_jac * f_jac * this.p_cov + this.q_var;

    this.n_prev = this.n_est;
    if (z_obs_n === null || Number.isNaN(z_obs_n) || p_eff <= 0.001 || rejection_rate >= 0.95) {
      this.n_est = n_pred;
      this.p_cov = p_pred;
      return this.n_est;
    }

    const r_t =
      this.r_base * (0.05 / Math.max(p_eff, 0.005)) * Math.exp(this.alpha_gate * rejection_rate);
    const k_gain = p_pred / (p_pred + r_t);
    this.n_est = Math.max(0.0, Math.min(n_pred + k_gain * (z_obs_n - n_pred), this.n_jam));
    this.p_cov = (1.0 - k_gain) * p_pred;
    return this.n_est;
  }
}

export interface ResidualCorrectedSmithPIControllerParams {
  readonly n_crit: number;
  readonly kp_norm?: number;
  readonly ki_norm?: number;
  readonly u_min?: number;
  readonly u_max?: number;
  readonly delay_steps?: number;
  readonly residual_gain?: number;
}

export class ResidualCorrectedSmithPIController {
  readonly n_crit: number;
  readonly kp_norm: number;
  readonly ki_norm: number;
  readonly u_min: number;
  readonly u_max: number;
  readonly delay_steps: number;
  readonly residual_gain: number;
  u_prev: number;
  err_prev: number;
  readonly actuation_history: Array<readonly [number, number]>;
  readonly model_pred_history: number[];

  constructor(params: ResidualCorrectedSmithPIControllerParams) {
    this.n_crit = Math.max(1.0, params.n_crit);
    this.kp_norm = params.kp_norm ?? 0.85;
    this.ki_norm = params.ki_norm ?? 0.22;
    this.u_min = params.u_min ?? 0.15;
    this.u_max = params.u_max ?? 1.0;
    this.delay_steps = Math.max(0, Math.trunc(params.delay_steps ?? 0));
    this.residual_gain = params.residual_gain ?? 0.5;
    this.u_prev = 1.0;
    this.err_prev = 0.0;
    this.actuation_history = [];
    this.model_pred_history = [];
    this.model_pred_history.push(this.n_crit);
  }

  public computeU(
    n_delayed_obs: number,
    q_in_current: number,
    kf_model: HysteresisAwarePCAKF,
    dt_s: number = 60.0
  ): number {
    let n_rollout: number;
    let n_effective: number;
    if (this.delay_steps === 0 || this.actuation_history.length === 0) {
      n_rollout = n_delayed_obs;
      n_effective = n_delayed_obs;
    } else {
      n_rollout = n_delayed_obs;
      for (const [past_q_in, past_u] of this.actuation_history) {
        const outflow = kf_model.mfdOutflow(n_rollout, false);
        n_rollout = Math.max(
          0.0,
          Math.min(n_rollout + dt_s * (past_q_in * past_u - outflow), kf_model.n_jam)
        );
      }

      const n_model_delayed = this.model_pred_history[0];
      const residual = n_delayed_obs - n_model_delayed;
      n_effective = Math.max(
        0.0,
        Math.min(n_rollout + this.residual_gain * residual, kf_model.n_jam)
      );
    }

    const err_t = (n_effective - this.n_crit) / this.n_crit;
    const delta_u = -this.kp_norm * (err_t - this.err_prev) - this.ki_norm * err_t;
    const u_new = Math.max(this.u_min, Math.min(this.u_max, this.u_prev + delta_u));

    if (this.delay_steps > 0) {
      this.actuation_history.push([q_in_current, u_new]);
      while (this.actuation_history.length > this.delay_steps) {
        this.actuation_history.shift();
      }
      this.model_pred_history.push(n_rollout);
      while (this.model_pred_history.length > this.delay_steps + 1) {
        this.model_pred_history.shift();
      }
    }

    this.u_prev = u_new;
    this.err_prev = err_t;
    return u_new;
  }
}
