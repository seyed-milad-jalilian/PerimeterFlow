// Strict TypeScript Port of Mulberry32, Stateful Kinematic Gate, Stratified Edie,
// Hysteresis PC-AKF, and Residual-Corrected Smith-PI Controller.
// Guarantees <= 1e-9 numerical parity with Python reference (src/perimeterflow/).

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
  readonly observed_length_km?: number;
}

export function computeStratifiedEdie(
  segments: readonly AcceptedSegment[],
  classSpecs: Record<string, NetworkClassSpec>,
  dtWindowS = 60.0,
  pMin = 0.005
): { k_hat: number; q_hat: number; n_hat: number } {
  const keys = Object.keys(classSpecs);
  const totalLengthKm = keys.reduce((acc, k) => acc + classSpecs[k].length_km, 0.0);
  if (totalLengthKm <= 0.0) {
    throw new Error("Total network length must be strictly positive");
  }

  const tauByClass: Record<string, number> = {};
  const dByClass: Record<string, number> = {};
  for (const k of keys) {
    tauByClass[k] = 0.0;
    dByClass[k] = 0.0;
  }

  for (const seg of segments) {
    if (seg.link_class in tauByClass) {
      tauByClass[seg.link_class] += seg.tau_s;
      dByClass[seg.link_class] += seg.d_m / 1000.0;
    }
  }

  let nHatTotal = 0.0;
  let weightedFlowSum = 0.0;
  const dtHours = dtWindowS / 3600.0;

  for (const k of keys) {
    const spec = classSpecs[k];
    const pC = Math.max(spec.estimated_penetration, pMin);
    const lObs = spec.observed_length_km !== undefined && spec.observed_length_km > 0.0 ? spec.observed_length_km : spec.length_km;
    const spatialScale = spec.length_km / lObs;

    const totalVehHoursC = (spatialScale * (tauByClass[k] / 3600.0)) / pC;
    const totalVehKmC = (spatialScale * dByClass[k]) / pC;

    nHatTotal += totalVehHoursC / dtHours;
    weightedFlowSum += totalVehKmC / dtHours;
  }

  return {
    k_hat: nHatTotal / totalLengthKm,
    q_hat: weightedFlowSum / totalLengthKm,
    n_hat: nHatTotal,
  };
}

export class HysteresisAwarePCAKF {
  public n_est: number;
  public n_prev: number;
  public p_cov: number;
  public readonly n_crit: number;
  public readonly n_jam: number;
  public readonly m_max_load: number;
  public readonly m_max_unload: number;
  public readonly q_var: number;
  public readonly r_base: number;
  public readonly alpha_gate: number;
  public readonly p_ref: number;

  constructor(
    nInit: number,
    nCrit: number,
    nJam: number,
    mMaxLoad: number,
    hysteresisDropRatio = 0.82,
    qVar = 20.0,
    rBase = 120.0,
    alphaGate = 2.5,
    pRef = 0.05
  ) {
    this.n_est = nInit;
    this.n_prev = nInit;
    this.p_cov = 80.0;
    this.n_crit = nCrit;
    this.n_jam = nJam;
    this.m_max_load = mMaxLoad;
    this.m_max_unload = mMaxLoad * hysteresisDropRatio;
    this.q_var = qVar;
    this.r_base = rBase;
    this.alpha_gate = alphaGate;
    this.p_ref = pRef;
  }

  public mfdOutflow(nVal: number, isUnloading = false): number {
    const nC = Math.max(0.0, Math.min(nVal, this.n_jam));
    const mPeak = isUnloading && nC > 0.7 * this.n_crit ? this.m_max_unload : this.m_max_load;
    if (nC <= this.n_crit) {
      return mPeak * (nC / this.n_crit) * (2.0 - nC / this.n_crit);
    }
    const ratio = (nC - this.n_crit) / Math.max(1.0, this.n_jam - this.n_crit);
    return mPeak * Math.max(0.0, 1.0 - ratio * ratio);
  }

  public step(
    qInVehS: number,
    uGate: number,
    zObsN: number | null,
    pEff: number,
    rejectionRate: number,
    dtS = 60.0
  ): number {
    const isUnloading = this.n_est < this.n_prev && this.n_est > 0.8 * this.n_crit;
    const outflow = this.mfdOutflow(this.n_est, isUnloading);
    const nPred = Math.max(0.0, Math.min(this.n_est + dtS * (qInVehS * uGate - outflow), this.n_jam));

    const eps = 1.0;
    const dPhi = (this.mfdOutflow(this.n_est + eps, isUnloading) - outflow) / eps;
    const fJac = 1.0 - dtS * dPhi;
    const pPred = fJac * fJac * this.p_cov + this.q_var;

    this.n_prev = this.n_est;
    if (zObsN === null || Number.isNaN(zObsN) || pEff <= 0.001 || rejectionRate >= 0.95) {
      this.n_est = nPred;
      this.p_cov = Math.max(1e-6, pPred);
      return this.n_est;
    }

    const rT = this.r_base * (this.p_ref / Math.max(pEff, 0.005)) * Math.exp(this.alpha_gate * rejectionRate);
    const kGain = pPred / (pPred + rT);
    this.n_est = Math.max(0.0, Math.min(nPred + kGain * (zObsN - nPred), this.n_jam));
    this.p_cov = Math.max(1e-6, (1.0 - kGain) * pPred);
    return this.n_est;
  }
}

export class FractionalObservationDelayBuffer {
  public readonly delay_steps: number;
  public readonly delay_frac: number;
  private readonly history: number[] = [];

  constructor(delaySteps: number, delayFrac: number, nInit: number) {
    this.delay_steps = Math.max(0, Math.trunc(delaySteps));
    this.delay_frac = delayFrac;
    this.history.push(nInit);
  }

  public pushAndRead(zT: number): number {
    this.history.push(zT);
    const tNow = this.history.length - 2;
    const sRecent = tNow - this.delay_steps;
    const iRecent = sRecent >= 0 ? sRecent + 1 : 0;
    const iPrev = sRecent >= 1 ? sRecent : 0;
    return (1.0 - this.delay_frac) * this.history[iRecent] + this.delay_frac * this.history[iPrev];
  }
}

export class ResidualCorrectedSmithPIController {
  public readonly n_crit: number;
  public readonly kp_norm: number;
  public readonly ki_norm: number;
  public readonly u_min: number;
  public readonly u_max: number;
  public readonly delay_steps: number;
  public readonly residual_gain: number;
  public readonly delay_frac: number;
  private u_prev = 1.0;
  private err_prev = 0.0;
  private actuation_history: Array<[number, number]> = [];
  private model_pred_history: number[] = [];
  private last_actuation: [number, number] | null = null;

  constructor(
    nCrit: number,
    kpNorm = 0.85,
    kiNorm = 0.22,
    uMin = 0.15,
    uMax = 1.0,
    delaySteps = 0,
    residualGain = 0.5,
    delayFrac = 0.0
  ) {
    this.n_crit = Math.max(1.0, nCrit);
    this.kp_norm = kpNorm;
    this.ki_norm = kiNorm;
    this.u_min = uMin;
    this.u_max = uMax;
    this.delay_steps = Math.max(0, Math.trunc(delaySteps));
    this.residual_gain = residualGain;
    if (!(0.0 <= delayFrac && delayFrac < 1.0)) {
      throw new Error("delayFrac must satisfy 0.0 <= delayFrac < 1.0");
    }
    this.delay_frac = delayFrac;
    this.model_pred_history.push(this.n_crit);
  }

  public computeU(
    nDelayedObs: number,
    qInCurrent: number,
    kfModel: HysteresisAwarePCAKF,
    dtS = 60.0
  ): number {
    const hasFullRollout = this.delay_steps > 0 && this.actuation_history.length > 0;
    const hasFracRollout = this.delay_frac > 0.0 && this.last_actuation !== null;

    let nRollout = nDelayedObs;
    let nEffective = nDelayedObs;

    if (hasFullRollout || hasFracRollout) {
      if (hasFullRollout) {
        for (const [pastQIn, pastU] of this.actuation_history) {
          const outflow = kfModel.mfdOutflow(nRollout, false);
          nRollout = Math.max(0.0, Math.min(nRollout + dtS * (pastQIn * pastU - outflow), kfModel.n_jam));
        }
      }
      if (hasFracRollout) {
        const qPrev = this.last_actuation![0];
        const uPrev = this.last_actuation![1];
        const outflow = kfModel.mfdOutflow(nRollout, false);
        nRollout = Math.max(
          0.0,
          Math.min(nRollout + this.delay_frac * dtS * (qPrev * uPrev - outflow), kfModel.n_jam)
        );
      }
      let nModelDelayed: number;
      if (this.delay_frac > 0.0 && this.model_pred_history.length >= 2) {
        nModelDelayed =
          (1.0 - this.delay_frac) * this.model_pred_history[1] + this.delay_frac * this.model_pred_history[0];
      } else {
        nModelDelayed = this.model_pred_history[0];
      }
      const residual = nDelayedObs - nModelDelayed;
      nEffective = Math.max(0.0, Math.min(nRollout + this.residual_gain * residual, kfModel.n_jam));
    }

    const errT = (nEffective - this.n_crit) / this.n_crit;
    const deltaU = -this.kp_norm * (errT - this.err_prev) - this.ki_norm * errT;
    const uNew = Math.max(this.u_min, Math.min(this.u_max, this.u_prev + deltaU));

    if (this.delay_steps > 0 || this.delay_frac > 0.0) {
      if (this.delay_steps > 0) {
        if (this.actuation_history.length >= this.delay_steps) {
          this.actuation_history.shift();
        }
        this.actuation_history.push([qInCurrent, uNew]);
      }
      this.last_actuation = [qInCurrent, uNew];
      const predCap = this.delay_steps + (this.delay_frac > 0.0 ? 2 : 1);
      if (this.model_pred_history.length >= predCap) {
        this.model_pred_history.shift();
      }
      this.model_pred_history.push(nRollout);
    }

    this.u_prev = uNew;
    this.err_prev = errT;
    return uNew;
  }
}
