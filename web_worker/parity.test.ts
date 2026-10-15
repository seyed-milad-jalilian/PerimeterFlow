import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  computeStratifiedEdie,
  HysteresisAwarePCAKF,
  Mulberry32,
  ResidualCorrectedSmithPIController,
  runStatefulQualityGate,
} from "./mfd_worker";

describe("Python-to-TypeScript 1e-9 Golden Parity Suite", () => {
  const goldenPath = resolve(__dirname, "../data/golden/parity_vectors.json");
  const golden = JSON.parse(readFileSync(goldenPath, "utf-8"));

  it("matches Mulberry32 uniform float and Box-Muller Gaussian streams within 1e-9", () => {
    const rng = new Mulberry32(golden.seed);
    for (const expectedFloat of golden.prng_floats) {
      expect(Math.abs(rng.nextFloat() - expectedFloat)).toBeLessThanOrEqual(1e-9);
    }
    for (const expectedGauss of golden.prng_gaussians) {
      expect(Math.abs(rng.nextGaussian(2.5, 1.2) - expectedGauss)).toBeLessThanOrEqual(1e-9);
    }
  });

  it("matches Stateful Quality Gate segments and rejection rate within 1e-9", () => {
    const res = runStatefulQualityGate(golden.pings);
    expect(Math.abs(res.rejection_rate - golden.expected_gate.rejection_rate)).toBeLessThanOrEqual(1e-9);
    expect(res.segments.length).toBe(golden.expected_gate.segments.length);
    res.segments.forEach((seg, idx) => {
      const exp = golden.expected_gate.segments[idx];
      expect(seg.veh_id).toBe(exp.veh_id);
      expect(Math.abs(seg.tau_s - exp.tau_s)).toBeLessThanOrEqual(1e-9);
      expect(Math.abs(seg.d_m - exp.d_m)).toBeLessThanOrEqual(1e-9);
    });
  });

  it("matches Stratified Edie, Hysteresis PC-AKF, and Smith-PI outputs within 1e-9", () => {
    const gateRes = runStatefulQualityGate(golden.pings);
    const specs = {
      arterial: { length_km: 10.0, estimated_penetration: 0.04 },
      local: { length_km: 20.0, estimated_penetration: 0.01 },
    };
    const edie = computeStratifiedEdie(gateRes.segments, specs, 60.0);
    expect(Math.abs(edie.k_hat - golden.expected_edie.k_hat)).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(edie.q_hat - golden.expected_edie.q_hat)).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(edie.n_hat - golden.expected_edie.n_hat)).toBeLessThanOrEqual(1e-9);

    const kf = new HysteresisAwarePCAKF(200.0, 400.0, 1000.0, 0.9);
    const s1 = kf.step(0.8, 1.0, edie.n_hat, 0.02, gateRes.rejection_rate, 60.0);
    const s2 = kf.step(0.9, 0.85, edie.n_hat * 1.1, 0.02, gateRes.rejection_rate, 60.0);
    expect(Math.abs(s1 - golden.expected_kf_steps[0])).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(s2 - golden.expected_kf_steps[1])).toBeLessThanOrEqual(1e-9);

    const ctrl = new ResidualCorrectedSmithPIController(400.0, 0.85, 0.22, 0.15, 1.0, 1);
    const u1 = ctrl.computeU(220.0, 0.8, kf, 60.0);
    const u2 = ctrl.computeU(310.0, 0.9, kf, 60.0);
    const u3 = ctrl.computeU(430.0, 0.95, kf, 60.0);
    expect(Math.abs(u1 - golden.expected_u_steps[0])).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(u2 - golden.expected_u_steps[1])).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(u3 - golden.expected_u_steps[2])).toBeLessThanOrEqual(1e-9);
  });
});
