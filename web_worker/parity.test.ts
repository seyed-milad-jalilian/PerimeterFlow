import { describe, expect, it } from "vitest";
import golden from "../data/golden/parity_vectors.json";
import {
  Mulberry32,
  runStatefulQualityGate,
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
