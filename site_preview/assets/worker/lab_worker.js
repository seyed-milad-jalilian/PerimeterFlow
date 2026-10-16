// ../web_worker/mfd_worker.ts
var Mulberry32 = class {
  state;
  constructor(seed) {
    this.state = seed >>> 0;
  }
  nextFloat() {
    this.state = this.state + 1831565813 >>> 0;
    let t = this.state;
    t = Math.imul(t ^ t >>> 15, t | 1) >>> 0;
    t = t + Math.imul(t ^ t >>> 7, t | 61) ^ t;
    t = (t ^ t >>> 14) >>> 0;
    return t / 4294967296;
  }
  nextGaussian(mean = 0, std = 1) {
    const u1 = Math.max(1e-12, this.nextFloat());
    const u2 = this.nextFloat();
    const z0 = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    return mean + z0 * std;
  }
};
var DEFAULT_GATE_CONFIG = {
  v_max_ms: 22.22,
  a_max_ms2: 4.5,
  a_min_ms2: -6.5,
  max_dt_gap_s: 15,
  max_map_snap_dist_m: 12
};
function runStatefulQualityGate(pings, cfg = DEFAULT_GATE_CONFIG) {
  const sorted = [...pings].sort(
    (a, b) => a.veh_id === b.veh_id ? a.timestamp_s - b.timestamp_s : a.veh_id.localeCompare(b.veh_id)
  );
  const anchors = /* @__PURE__ */ new Map();
  const segments = [];
  let rejected = 0;
  for (const p of sorted) {
    if (p.snap_dist_m > cfg.max_map_snap_dist_m || Number.isNaN(p.x_obs_m) || Number.isNaN(p.y_obs_m)) {
      rejected += 1;
      continue;
    }
    const state = anchors.get(p.veh_id);
    if (state === void 0 || p.timestamp_s - state.t > cfg.max_dt_gap_s) {
      if (p.speed_obs_ms >= 0 && p.speed_obs_ms <= cfg.v_max_ms) {
        anchors.set(p.veh_id, { t: p.timestamp_s, x: p.x_obs_m, y: p.y_obs_m, v: p.speed_obs_ms });
        segments.push({ veh_id: p.veh_id, link_class: p.link_class, timestamp_s: p.timestamp_s, tau_s: 0, d_m: 0 });
      } else {
        rejected += 1;
      }
      continue;
    }
    const dt = p.timestamp_s - state.t;
    if (dt <= 0) {
      rejected += 1;
      continue;
    }
    const dist = Math.hypot(p.x_obs_m - state.x, p.y_obs_m - state.y);
    const vCalc = dist / dt;
    const aCalc = (vCalc - state.v) / dt;
    if (vCalc < 0 || vCalc > cfg.v_max_ms || aCalc > cfg.a_max_ms2 || aCalc < cfg.a_min_ms2) {
      rejected += 1;
      continue;
    }
    anchors.set(p.veh_id, { t: p.timestamp_s, x: p.x_obs_m, y: p.y_obs_m, v: vCalc });
    segments.push({ veh_id: p.veh_id, link_class: p.link_class, timestamp_s: p.timestamp_s, tau_s: dt, d_m: dist });
  }
  const rejectionRate = sorted.length > 0 ? rejected / sorted.length : 1;
  return { segments, rejection_rate: rejectionRate };
}
function computeStratifiedEdie(segments, classSpecs, dtWindowS = 60, pMin = 5e-3) {
  const keys = Object.keys(classSpecs);
  const totalLengthKm = keys.reduce((acc, k) => acc + classSpecs[k].length_km, 0);
  if (totalLengthKm <= 0) {
    throw new Error("Total network length must be strictly positive");
  }
  const tauByClass = {};
  const dByClass = {};
  for (const k of keys) {
    tauByClass[k] = 0;
    dByClass[k] = 0;
  }
  for (const seg of segments) {
    if (seg.link_class in tauByClass) {
      tauByClass[seg.link_class] += seg.tau_s;
      dByClass[seg.link_class] += seg.d_m / 1e3;
    }
  }
  let nHatTotal = 0;
  let weightedFlowSum = 0;
  const dtHours = dtWindowS / 3600;
  for (const k of keys) {
    const spec = classSpecs[k];
    const pC = Math.max(spec.estimated_penetration, pMin);
    const lObs = spec.observed_length_km !== void 0 && spec.observed_length_km > 0 ? spec.observed_length_km : spec.length_km;
    const spatialScale = spec.length_km / lObs;
    const totalVehHoursC = spatialScale * (tauByClass[k] / 3600) / pC;
    const totalVehKmC = spatialScale * dByClass[k] / pC;
    nHatTotal += totalVehHoursC / dtHours;
    weightedFlowSum += totalVehKmC / dtHours;
  }
  return {
    k_hat: nHatTotal / totalLengthKm,
    q_hat: weightedFlowSum / totalLengthKm,
    n_hat: nHatTotal
  };
}
var HysteresisAwarePCAKF = class {
  n_est;
  n_prev;
  p_cov;
  n_crit;
  n_jam;
  m_max_load;
  m_max_unload;
  q_var;
  r_base;
  alpha_gate;
  p_ref;
  constructor(nInit, nCrit, nJam, mMaxLoad, hysteresisDropRatio = 0.82, qVar = 20, rBase = 120, alphaGate = 2.5, pRef = 0.05) {
    this.n_est = nInit;
    this.n_prev = nInit;
    this.p_cov = 80;
    this.n_crit = nCrit;
    this.n_jam = nJam;
    this.m_max_load = mMaxLoad;
    this.m_max_unload = mMaxLoad * hysteresisDropRatio;
    this.q_var = qVar;
    this.r_base = rBase;
    this.alpha_gate = alphaGate;
    this.p_ref = pRef;
  }
  mfdOutflow(nVal, isUnloading = false) {
    const nC = Math.max(0, Math.min(nVal, this.n_jam));
    const mPeak = isUnloading && nC > 0.7 * this.n_crit ? this.m_max_unload : this.m_max_load;
    if (nC <= this.n_crit) {
      return mPeak * (nC / this.n_crit) * (2 - nC / this.n_crit);
    }
    const ratio = (nC - this.n_crit) / Math.max(1, this.n_jam - this.n_crit);
    return mPeak * Math.max(0, 1 - ratio * ratio);
  }
  step(qInVehS, uGate, zObsN, pEff, rejectionRate, dtS = 60) {
    const isUnloading = this.n_est < this.n_prev && this.n_est > 0.8 * this.n_crit;
    const outflow = this.mfdOutflow(this.n_est, isUnloading);
    const nPred = Math.max(0, Math.min(this.n_est + dtS * (qInVehS * uGate - outflow), this.n_jam));
    const eps = 1;
    const dPhi = (this.mfdOutflow(this.n_est + eps, isUnloading) - outflow) / eps;
    const fJac = 1 - dtS * dPhi;
    const pPred = fJac * fJac * this.p_cov + this.q_var;
    this.n_prev = this.n_est;
    if (zObsN === null || Number.isNaN(zObsN) || pEff <= 1e-3 || rejectionRate >= 0.95) {
      this.n_est = nPred;
      this.p_cov = Math.max(1e-6, pPred);
      return this.n_est;
    }
    const rT = this.r_base * (this.p_ref / Math.max(pEff, 5e-3)) * Math.exp(this.alpha_gate * rejectionRate);
    const kGain = pPred / (pPred + rT);
    this.n_est = Math.max(0, Math.min(nPred + kGain * (zObsN - nPred), this.n_jam));
    this.p_cov = Math.max(1e-6, (1 - kGain) * pPred);
    return this.n_est;
  }
};
var ResidualCorrectedSmithPIController = class {
  n_crit;
  kp_norm;
  ki_norm;
  u_min;
  u_max;
  delay_steps;
  residual_gain;
  u_prev = 1;
  err_prev = 0;
  actuation_history = [];
  model_pred_history = [];
  constructor(nCrit, kpNorm = 0.85, kiNorm = 0.22, uMin = 0.15, uMax = 1, delaySteps = 0, residualGain = 0.5) {
    this.n_crit = Math.max(1, nCrit);
    this.kp_norm = kpNorm;
    this.ki_norm = kiNorm;
    this.u_min = uMin;
    this.u_max = uMax;
    this.delay_steps = Math.max(0, Math.trunc(delaySteps));
    this.residual_gain = residualGain;
    this.model_pred_history.push(this.n_crit);
  }
  computeU(nDelayedObs, qInCurrent, kfModel, dtS = 60) {
    let nRollout = nDelayedObs;
    let nEffective = nDelayedObs;
    if (this.delay_steps > 0 && this.actuation_history.length > 0) {
      for (const [pastQIn, pastU] of this.actuation_history) {
        const outflow = kfModel.mfdOutflow(nRollout, false);
        nRollout = Math.max(0, Math.min(nRollout + dtS * (pastQIn * pastU - outflow), kfModel.n_jam));
      }
      const nModelDelayed = this.model_pred_history[0];
      const residual = nDelayedObs - nModelDelayed;
      nEffective = Math.max(0, Math.min(nRollout + this.residual_gain * residual, kfModel.n_jam));
    }
    const errT = (nEffective - this.n_crit) / this.n_crit;
    const deltaU = -this.kp_norm * (errT - this.err_prev) - this.ki_norm * errT;
    const uNew = Math.max(this.u_min, Math.min(this.u_max, this.u_prev + deltaU));
    if (this.delay_steps > 0) {
      if (this.actuation_history.length >= this.delay_steps) {
        this.actuation_history.shift();
      }
      this.actuation_history.push([qInCurrent, uNew]);
      if (this.model_pred_history.length >= this.delay_steps + 1) {
        this.model_pred_history.shift();
      }
      this.model_pred_history.push(nRollout);
    }
    this.u_prev = uNew;
    this.err_prev = errT;
    return uNew;
  }
};

// assets/worker/lab_worker.ts
var DT_S = 60;
var N_STEPS = 30;
var N_CRIT = 400;
var N_JAM = 1e3;
var M_MAX_LOAD = 0.9;
var Q_PROFILE = [
  2,
  3.5,
  5,
  6.5,
  8,
  9,
  10,
  10,
  10,
  9.5,
  9,
  8.5,
  8,
  7,
  6,
  5,
  4,
  3,
  2.5,
  2,
  1.5,
  1,
  1,
  1,
  1.5,
  2,
  2.5,
  3,
  3,
  3
];
var CLASS_SPECS = {
  arterial: { length_km: 10, estimated_penetration: 0.05 },
  local: { length_km: 20, estimated_penetration: 0.0125 }
};
function mfdOutflowRef(nVal, isUnloading) {
  const mMax = isUnloading && nVal > 0.7 * N_CRIT ? 0.82 * M_MAX_LOAD : M_MAX_LOAD;
  const nC = Math.max(0, Math.min(nVal, N_JAM));
  if (nC <= N_CRIT) {
    return mMax * (nC / N_CRIT) * (2 - nC / N_CRIT);
  }
  const ratio = (nC - N_CRIT) / (N_JAM - N_CRIT);
  return mMax * Math.max(0, 1 - ratio * ratio);
}
function synthesizePings(truthAtStep, step, pEst, params, rng, prevDropState) {
  const pings = [];
  const meanSpeed = truthAtStep > 1 ? mfdOutflowRef(truthAtStep, false) / (truthAtStep / 30) : 8;
  const vNet = Math.max(1, Math.min(meanSpeed, 15));
  for (let j = 0; j < 80; j++) {
    const isArterial = j % 5 !== 4;
    const linkClass = isArterial ? "arterial" : "local";
    const pClass = isArterial ? params.penetration * params.arterialBias : params.penetration;
    if (rng.nextFloat() > pClass) continue;
    if (prevDropState.dropped) {
      if (rng.nextFloat() < params.dropoutProb) continue;
      prevDropState.dropped = false;
    } else if (rng.nextFloat() < params.dropoutProb) {
      prevDropState.dropped = true;
      continue;
    }
    const vehOffset = j / 80 * 2e3;
    const xTrue = step * DT_S / 5 * vNet + vehOffset;
    const yTrue = isArterial ? 100 : 100 + j % 3 * 40;
    let xObs = xTrue + rng.nextGaussian(0, 3);
    const yObs = yTrue + rng.nextGaussian(0, 3);
    let snapDist = rng.nextFloat() * 2;
    if (rng.nextFloat() < params.spikeProb) {
      xObs += 150;
      snapDist = 150;
    }
    pings.push({
      veh_id: `ref-v${j}`,
      link_class: linkClass,
      timestamp_s: step * DT_S + rng.nextFloat() * 10,
      x_obs_m: xObs,
      y_obs_m: yObs,
      speed_obs_ms: vNet + rng.nextGaussian(0, 0.4),
      snap_dist_m: snapDist
    });
  }
  return pings;
}
function runLab(params) {
  const rng = Mulberry32 ? new Mulberry32(params.seed >>> 0) : null;
  if (rng === null) throw new Error("unreachable");
  const pErr = params.penetrationErrorPct / 100;
  const classSpecs = {
    arterial: {
      length_km: CLASS_SPECS.arterial.length_km,
      estimated_penetration: Math.max(5e-3, CLASS_SPECS.arterial.estimated_penetration * (1 + pErr))
    },
    local: {
      length_km: CLASS_SPECS.local.length_km,
      estimated_penetration: Math.max(5e-3, CLASS_SPECS.local.estimated_penetration * (1 + pErr))
    }
  };
  let truth = 150;
  let truthUncontrolled = 150;
  const akf = new HysteresisAwarePCAKF(150, N_CRIT, N_JAM, M_MAX_LOAD);
  const controller = new ResidualCorrectedSmithPIController(N_CRIT, 0.85, 0.22, 0.15, 1, params.delaySteps);
  const dropState = { dropped: false };
  const series = [];
  const estimates = [];
  const truths = [];
  let lastGateRejection = 1;
  let uFinal = 1;
  for (let step = 0; step < N_STEPS; step++) {
    const qIn = Q_PROFILE[step];
    const pings = synthesizePings(truth, step, params.penetration, params, rng, dropState);
    const gate = runStatefulQualityGate(pings, DEFAULT_GATE_CONFIG);
    lastGateRejection = gate.rejection_rate;
    const edie = computeStratifiedEdie(gate.segments, classSpecs, DT_S);
    const u = akf.n_est > 1 ? controller.computeU(akf.n_est, qIn, akf, DT_S) : 1;
    uFinal = u;
    const outflow = mfdOutflowRef(truth, truth < truth ? false : false);
    const prevTruth = truth;
    truth = Math.max(0, Math.min(truth + DT_S * (qIn * u - outflow), N_JAM));
    const isUnloading = prevTruth > truth && prevTruth > 0.8 * N_CRIT;
    const outflowUnc = mfdOutflowRef(truthUncontrolled, false);
    truthUncontrolled = Math.max(0, Math.min(truthUncontrolled + DT_S * (qIn * 1 - outflowUnc), N_JAM));
    const nEst = akf.step(qIn * u, u, edie.n_hat, params.penetration, gate.rejection_rate, DT_S);
    estimates.push(nEst);
    truths.push(truth);
    series.push({
      t_min: step + 1,
      truth_controlled: truth,
      truth_uncontrolled: truthUncontrolled,
      estimate: nEst,
      n_crit: N_CRIT
    });
  }
  const meanTruth = truths.reduce((a, b) => a + b, 0) / truths.length;
  const mse = estimates.reduce((acc, e, i) => acc + (e - truths[i]) ** 2, 0) / truths.length;
  const nrmse = Math.sqrt(mse) / meanTruth;
  const overshootControlled = truths.filter((n) => n > N_CRIT).length / truths.length;
  const overshootUncontrolled = series.filter((p) => p.truth_uncontrolled > N_CRIT).length / series.length;
  return {
    series,
    metrics: {
      gate_rejection_rate: lastGateRejection,
      nrmse_estimate: nrmse,
      overshoot_controlled: overshootControlled,
      overshoot_uncontrolled: overshootUncontrolled,
      u_final: uFinal,
      delay_steps: params.delaySteps,
      steps: N_STEPS
    },
    params,
    disclaimer: "Interactive Mechanics Dry-Run on Reference Sample. Deterministic aggregate plant with known accumulation; computed live in-browser. Not a research result and not derived from the pre-registered SUMO sweep."
  };
}
self.onmessage = (event) => {
  if (event.data.type !== "run") return;
  try {
    const result = runLab(event.data.params);
    self.postMessage({ type: "result", result });
  } catch (err) {
    self.postMessage({ type: "error", message: String(err) });
  }
};
export {
  runLab
};
