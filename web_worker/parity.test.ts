import { describe, expect, it } from "vitest";
import golden from "../data/golden/parity_vectors.json";
import {
  HysteresisAwarePCAKF,
  Mulberry32,
  ResidualCorrectedSmithPIController,
  computeStratifiedEdie,
  runStatefulQualityGate,
  type AcceptedSegment,
  type NetworkClassSpec,
  type ProbePing,
} from "./mfd_worker";

interface PrngVector {
  readonly seed: number;
  readonly next_float: readonly number[];
  readonly next_gaussian: readonly number[];
}

interface GoldenPing {
  readonly veh_id: string;
  readonly link_class: string;
  readonly timestamp_s: number;
  readonly x_obs_m: number;
  readonly y_obs_m: number;
  readonly speed_obs_ms: number;
  readonly snap_dist_m: number;
}

interface GoldenSegment {
  readonly veh_id: string;
  readonly link_class: string;
  readonly timestamp_s: number;
  readonly tau_s: number;
  readonly d_m: number;
}

interface GoldenGateConfig {
  readonly v_max_ms: number;
  readonly a_max_ms2: number;
  readonly a_min_ms2: number;
  readonly max_dt_gap_s: number;
  readonly max_map_snap_dist_m: number;
}

interface GateVector {
  readonly name: string;
  readonly config: GoldenGateConfig;
  readonly pings: readonly GoldenPing[];
  readonly segments: readonly GoldenSegment[];
  readonly rejection_rate: number;
  readonly total_pings: number;
  readonly rejected_spatial: number;
  readonly rejected_kinematic: number;
}

interface GoldenFile {
  readonly tolerance: number;
  readonly prng_vectors: readonly PrngVector[];
  readonly gate_vectors: readonly GateVector[];
  readonly estimator_vectors: readonly EstimatorVector[];
  readonly akf_vectors: readonly AkfVector[];
  readonly controller_vectors: readonly ControllerVector[];
}

interface AkfParams {
  readonly n_init: number;
  readonly n_crit: number;
  readonly n_jam: number;
  readonly m_max_load: number;
  readonly hysteresis_drop_ratio: number;
  readonly q_var: number;
  readonly r_base: number;
  readonly alpha_gate: number;
}

interface AkfStep {
  readonly q_in_veh_s: number;
  readonly u_gate: number;
  readonly z_obs_n: number | null;
  readonly p_eff: number;
  readonly rejection_rate: number;
  readonly dt_s: number;
}

interface AkfVector {
  readonly name: string;
  readonly seed: number;
  readonly params: AkfParams;
  readonly steps: readonly AkfStep[];
  readonly n_est: readonly number[];
  readonly p_cov: readonly number[];
}

interface ControllerVector {
  readonly name: string;
  readonly delay_steps: number;
  readonly n_crit: number;
  readonly kp_norm: number;
  readonly ki_norm: number;
  readonly u_min: number;
  readonly dt_s: number;
  readonly kf_params: AkfParams;
  readonly q_in_stream: readonly number[];
  readonly n_delayed_obs_stream: readonly number[];
  readonly u: readonly number[];
}

interface EstimatorVector {
  readonly name: string;
  readonly dt_window_s: number;
  readonly p_min: number;
  readonly class_specs: Readonly<Record<string, NetworkClassSpec>>;
  readonly segments: readonly GoldenSegment[];
  readonly k_hat_veh_km: number;
  readonly q_hat_veh_h: number;
  readonly n_hat_veh: number;
}

const goldenFile: GoldenFile = golden;

function toLinkClass(value: string): ProbePing["link_class"] {
  if (value === "arterial" || value === "local") {
    return value;
  }
  throw new Error(`unexpected link_class in golden vectors: ${value}`);
}

function toProbePing(raw: GoldenPing): ProbePing {
  return {
    veh_id: raw.veh_id,
    link_class: toLinkClass(raw.link_class),
    timestamp_s: raw.timestamp_s,
    x_obs_m: raw.x_obs_m,
    y_obs_m: raw.y_obs_m,
    speed_obs_ms: raw.speed_obs_ms,
    snap_dist_m: raw.snap_dist_m,
  };
}

function assertClose(actual: number, expected: number, label: string): void {
  const scale = Math.max(Math.abs(actual), Math.abs(expected));
  if (scale === 0.0) {
    expect(actual, label).toBe(0.0);
    return;
  }
  const relative = Math.abs(actual - expected) / scale;
  expect(relative, label).toBeLessThanOrEqual(goldenFile.tolerance);
}

describe("Mulberry32 parity against Python golden vectors", () => {
  for (const vec of goldenFile.prng_vectors) {
    it(`reproduces seed ${vec.seed} next_float and next_gaussian streams`, () => {
      const floatGen = new Mulberry32(vec.seed);
      vec.next_float.forEach((expected, index) => {
        assertClose(floatGen.nextFloat(), expected, `seed ${vec.seed} next_float[${index}]`);
      });
      const gaussianGen = new Mulberry32(vec.seed);
      vec.next_gaussian.forEach((expected, index) => {
        assertClose(gaussianGen.nextGaussian(), expected, `seed ${vec.seed} next_gaussian[${index}]`);
      });
    });
  }
});

describe("Stateful quality gate parity against Python golden vectors", () => {
  for (const vec of goldenFile.gate_vectors) {
    it(`reproduces gate stream "${vec.name}"`, () => {
      const result = runStatefulQualityGate(
        vec.pings.map(toProbePing),
        vec.config
      );
      expect(result.segments.length, `segment count for ${vec.name}`).toBe(
        vec.segments.length
      );
      result.segments.forEach((seg, index) => {
        const expected = vec.segments[index];
        expect(seg.veh_id, `segments[${index}].veh_id`).toBe(expected.veh_id);
        expect(seg.link_class, `segments[${index}].link_class`).toBe(
          expected.link_class
        );
        assertClose(seg.timestamp_s, expected.timestamp_s, `segments[${index}].timestamp_s`);
        assertClose(seg.tau_s, expected.tau_s, `segments[${index}].tau_s`);
        assertClose(seg.d_m, expected.d_m, `segments[${index}].d_m`);
      });
      assertClose(result.rejection_rate, vec.rejection_rate, `${vec.name} rejection_rate`);
    });
  }
});

describe("Stratified Edie estimator parity against Python golden vectors", () => {
  for (const vec of goldenFile.estimator_vectors) {
    it(`reproduces estimator stream "${vec.name}"`, () => {
      const segments: AcceptedSegment[] = vec.segments.map((raw) => ({
        veh_id: raw.veh_id,
        link_class: toLinkClass(raw.link_class),
        timestamp_s: raw.timestamp_s,
        tau_s: raw.tau_s,
        d_m: raw.d_m,
      }));
      const result = computeStratifiedEdie(segments, vec.class_specs, vec.dt_window_s, vec.p_min);
      assertClose(result.k_hat_veh_km, vec.k_hat_veh_km, `${vec.name} k_hat_veh_km`);
      assertClose(result.q_hat_veh_h, vec.q_hat_veh_h, `${vec.name} q_hat_veh_h`);
      assertClose(result.n_hat_veh, vec.n_hat_veh, `${vec.name} n_hat_veh`);
    });
  }
});

describe("HysteresisAwarePCAKF parity against Python golden vectors", () => {
  for (const vec of goldenFile.akf_vectors) {
    it(`reproduces AKF stream "${vec.name}" (seed ${vec.seed})`, () => {
      const kf = new HysteresisAwarePCAKF(vec.params);
      expect(kf.p_cov, "initial p_cov").toBe(80.0);
      vec.steps.forEach((step, index) => {
        const n = kf.step(
          step.q_in_veh_s,
          step.u_gate,
          step.z_obs_n,
          step.p_eff,
          step.rejection_rate,
          step.dt_s
        );
        assertClose(n, vec.n_est[index], `${vec.name} n_est[${index}]`);
        assertClose(kf.p_cov, vec.p_cov[index], `${vec.name} p_cov[${index}]`);
      });
    });
  }
});

describe("ResidualCorrectedSmithPIController parity against Python golden vectors", () => {
  for (const vec of goldenFile.controller_vectors) {
    it(`reproduces controller stream "${vec.name}" (delay_steps=${vec.delay_steps})`, () => {
      const kf = new HysteresisAwarePCAKF(vec.kf_params);
      const ctrl = new ResidualCorrectedSmithPIController({
        n_crit: vec.n_crit,
        kp_norm: vec.kp_norm,
        ki_norm: vec.ki_norm,
        u_min: vec.u_min,
        delay_steps: vec.delay_steps,
      });
      vec.q_in_stream.forEach((q_in, index) => {
        const u = ctrl.computeU(vec.n_delayed_obs_stream[index], q_in, kf, vec.dt_s);
        assertClose(u, vec.u[index], `${vec.name} u[${index}]`);
      });
    });
  }
});
