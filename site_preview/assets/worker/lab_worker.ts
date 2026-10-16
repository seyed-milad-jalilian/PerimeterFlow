// Interactive Estimator Lab worker.
// Bundles the parity-verified components from web_worker/mfd_worker.ts (<= 1e-9 vs Python)
// and runs an "Interactive Mechanics Dry-Run on Reference Sample": a deterministic
// aggregate two-reservoir-style reference plant whose accumulation is known by
// construction, probed through the same defensive pipeline (gate -> stratified Edie
// -> hysteresis PC-AKF -> residual-corrected Smith-PI). This is a mechanics
// demonstration, not a research result: no empirical NRMSE, p-value, or paper
// claim is produced here.
import {
  DEFAULT_GATE_CONFIG,
  HysteresisAwarePCAKF,
  Mulberry32,
  ResidualCorrectedSmithPIController,
  computeStratifiedEdie,
  runStatefulQualityGate,
  type NetworkClassSpec,
  type ProbePing,
} from "../../../web_worker/mfd_worker";

export interface LabParams {
  readonly seed: number;
  readonly penetration: number;
  readonly arterialBias: number;
  readonly spikeProb: number;
  readonly dropoutProb: number;
  readonly delaySteps: number;
  readonly penetrationErrorPct: number;
}

export interface LabSeriesPoint {
  readonly t_min: number;
  readonly truth_controlled: number;
  readonly truth_uncontrolled: number;
  readonly estimate: number;
  readonly n_crit: number;
}

export interface LabMetrics {
  readonly gate_rejection_rate: number;
  readonly nrmse_estimate: number;
  readonly overshoot_controlled: number;
  readonly overshoot_uncontrolled: number;
  readonly u_final: number;
  readonly delay_steps: number;
  readonly steps: number;
}

export interface LabResult {
  readonly series: LabSeriesPoint[];
  readonly metrics: LabMetrics;
  readonly params: LabParams;
  readonly disclaimer: string;
}

const DT_S = 60.0;
const N_STEPS = 30;
const N_CRIT = 400.0;
const N_JAM = 1000.0;
const M_MAX_LOAD = 0.9;
const Q_PROFILE: number[] = [
  2.0, 3.5, 5.0, 6.5, 8.0, 9.0, 10.0, 10.0, 10.0, 9.5,
  9.0, 8.5, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.5, 2.0,
  1.5, 1.0, 1.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.0, 3.0,
];

const CLASS_SPECS: Record<string, NetworkClassSpec> = {
  arterial: { length_km: 10.0, estimated_penetration: 0.05 },
  local: { length_km: 20.0, estimated_penetration: 0.0125 },
};

function mfdOutflowRef(nVal: number, isUnloading: boolean): number {
  const mMax = isUnloading && nVal > 0.7 * N_CRIT ? 0.82 * M_MAX_LOAD : M_MAX_LOAD;
  const nC = Math.max(0.0, Math.min(nVal, N_JAM));
  if (nC <= N_CRIT) {
    return mMax * (nC / N_CRIT) * (2.0 - nC / N_CRIT);
  }
  const ratio = (nC - N_CRIT) / (N_JAM - N_CRIT);
  return mMax * Math.max(0.0, 1.0 - ratio * ratio);
}

function synthesizePings(
  truthAtStep: number,
  step: number,
  pEst: number,
  params: LabParams,
  rng: Mulberry32,
  prevDropState: { dropped: boolean }
): ProbePing[] {
  const pings: ProbePing[] = [];
  const meanSpeed = truthAtStep > 1.0 ? mfdOutflowRef(truthAtStep, false) / (truthAtStep / 30.0) : 8.0;
  const vNet = Math.max(1.0, Math.min(meanSpeed, 15.0));
  for (let j = 0; j < 80; j++) {
    const isArterial = j % 5 !== 4;
    const linkClass: "arterial" | "local" = isArterial ? "arterial" : "local";
    const pClass = isArterial ? params.penetration * params.arterialBias : params.penetration;
    if (rng.nextFloat() > pClass) continue;
    if (prevDropState.dropped) {
      if (rng.nextFloat() < params.dropoutProb) continue;
      prevDropState.dropped = false;
    } else if (rng.nextFloat() < params.dropoutProb) {
      prevDropState.dropped = true;
      continue;
    }
    const vehOffset = (j / 80.0) * 2000.0;
    const xTrue = ((step * DT_S) / 5.0) * vNet + vehOffset;
    const yTrue = isArterial ? 100.0 : 100.0 + (j % 3) * 40.0;
    let xObs = xTrue + rng.nextGaussian(0.0, 3.0);
    const yObs = yTrue + rng.nextGaussian(0.0, 3.0);
    let snapDist = rng.nextFloat() * 2.0;
    if (rng.nextFloat() < params.spikeProb) {
      xObs += 150.0;
      snapDist = 150.0;
    }
    pings.push({
      veh_id: `ref-v${j}`,
      link_class: linkClass,
      timestamp_s: step * DT_S + (rng.nextFloat() * 10.0),
      x_obs_m: xObs,
      y_obs_m: yObs,
      speed_obs_ms: vNet + rng.nextGaussian(0.0, 0.4),
      snap_dist_m: snapDist,
    });
  }
  return pings;
}

export function runLab(params: LabParams): LabResult {
  const rng = Mulberry32 ? new Mulberry32(params.seed >>> 0) : null;
  if (rng === null) throw new Error("unreachable");
  const pErr = params.penetrationErrorPct / 100.0;
  const classSpecs: Record<string, NetworkClassSpec> = {
    arterial: {
      length_km: CLASS_SPECS.arterial.length_km,
      estimated_penetration: Math.max(0.005, CLASS_SPECS.arterial.estimated_penetration * (1.0 + pErr)),
    },
    local: {
      length_km: CLASS_SPECS.local.length_km,
      estimated_penetration: Math.max(0.005, CLASS_SPECS.local.estimated_penetration * (1.0 + pErr)),
    },
  };

  let truth = 150.0;
  let truthUncontrolled = 150.0;
  const akf = new HysteresisAwarePCAKF(150.0, N_CRIT, N_JAM, M_MAX_LOAD);
  const controller = new ResidualCorrectedSmithPIController(N_CRIT, 0.85, 0.22, 0.15, 1.0, params.delaySteps);
  const dropState = { dropped: false };

  const series: LabSeriesPoint[] = [];
  const estimates: number[] = [];
  const truths: number[] = [];
  let lastGateRejection = 1.0;
  let uFinal = 1.0;

  for (let step = 0; step < N_STEPS; step++) {
    const qIn = Q_PROFILE[step];

    const pings = synthesizePings(truth, step, params.penetration, params, rng, dropState);
    const gate = runStatefulQualityGate(pings, DEFAULT_GATE_CONFIG);
    lastGateRejection = gate.rejection_rate;
    const edie = computeStratifiedEdie(gate.segments, classSpecs, DT_S);
    const u = akf.n_est > 1.0 ? controller.computeU(akf.n_est, qIn, akf, DT_S) : 1.0;
    uFinal = u;

    const outflow = mfdOutflowRef(truth, truth < truth ? false : false);
    const prevTruth = truth;
    truth = Math.max(0.0, Math.min(truth + DT_S * (qIn * u - outflow), N_JAM));
    const isUnloading = prevTruth > truth && prevTruth > 0.8 * N_CRIT;
    void isUnloading;

    const outflowUnc = mfdOutflowRef(truthUncontrolled, false);
    truthUncontrolled = Math.max(0.0, Math.min(truthUncontrolled + DT_S * (qIn * 1.0 - outflowUnc), N_JAM));

    const nEst = akf.step(qIn * u, u, edie.n_hat, params.penetration, gate.rejection_rate, DT_S);
    estimates.push(nEst);
    truths.push(truth);
    series.push({
      t_min: (step + 1),
      truth_controlled: truth,
      truth_uncontrolled: truthUncontrolled,
      estimate: nEst,
      n_crit: N_CRIT,
    });
  }

  const meanTruth = truths.reduce((a, b) => a + b, 0.0) / truths.length;
  const mse = estimates.reduce((acc, e, i) => acc + (e - truths[i]) ** 2, 0.0) / truths.length;
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
      steps: N_STEPS,
    },
    params,
    disclaimer:
      "Interactive Mechanics Dry-Run on Reference Sample. Deterministic aggregate plant with known accumulation; computed live in-browser. Not a research result and not derived from the pre-registered SUMO sweep.",
  };
}

export interface LabRequest {
  readonly type: "run";
  readonly params: LabParams;
}

self.onmessage = (event: MessageEvent<LabRequest>) => {
  if (event.data.type !== "run") return;
  try {
    const result = runLab(event.data.params);
    (self as unknown as Worker).postMessage({ type: "result", result });
  } catch (err) {
    (self as unknown as Worker).postMessage({ type: "error", message: String(err) });
  }
};
