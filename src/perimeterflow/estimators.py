from dataclasses import dataclass
import math
from .quality_gate import AcceptedSegment


@dataclass(frozen=True)
class NetworkClassSpec:
    length_km: float
    estimated_penetration: float
    observed_length_km: float | None = None


def compute_stratified_edie(
    segments: list[AcceptedSegment],
    class_specs: dict[str, NetworkClassSpec],
    dt_window_s: float = 60.0,
    p_min: float = 0.005,
) -> tuple[float, float, float]:
    """
    Stratified Link-Class Horvitz-Thompson Edie Estimator.
    Implements exact class length scaling (L_c / L_c^obs) and inverse penetration weighting.
    Returns: (k_hat_veh_km, q_hat_veh_h, N_hat_veh)
    """
    total_length_km = sum(spec.length_km for spec in class_specs.values())
    if total_length_km <= 0.0:
        raise ValueError("Total network length must be strictly positive")
    if dt_window_s <= 0.0:
        raise ValueError("Time window dt_window_s must be strictly positive")

    tau_by_class: dict[str, float] = {c: 0.0 for c in class_specs}
    d_by_class: dict[str, float] = {c: 0.0 for c in class_specs}

    for seg in segments:
        if seg.link_class in tau_by_class:
            tau_by_class[seg.link_class] += seg.tau_s
            d_by_class[seg.link_class] += seg.d_m / 1000.0

    n_hat_total = 0.0
    weighted_flow_sum = 0.0
    dt_hours = dt_window_s / 3600.0

    for c, spec in class_specs.items():
        p_c = max(spec.estimated_penetration, p_min)
        l_obs = spec.observed_length_km if (spec.observed_length_km is not None and spec.observed_length_km > 0.0) else spec.length_km
        spatial_scale = spec.length_km / l_obs

        total_veh_hours_c = spatial_scale * (tau_by_class[c] / 3600.0) / p_c
        total_veh_km_c = spatial_scale * d_by_class[c] / p_c

        n_hat_total += total_veh_hours_c / dt_hours
        weighted_flow_sum += total_veh_km_c / dt_hours

    k_hat = n_hat_total / total_length_km
    q_hat = weighted_flow_sum / total_length_km
    return k_hat, q_hat, n_hat_total


class HysteresisAwarePCAKF:
    """
    Physics-Constrained Adaptive Kalman Filter supporting two MFD capacity branches
    (Loading vs Unloading recovery) and gate-scaled observation covariance R_t.
    """
    def __init__(
        self,
        n_init: float,
        n_crit: float,
        n_jam: float,
        m_max_load: float,
        hysteresis_drop_ratio: float = 0.82,
        q_var: float = 20.0,
        r_base: float = 120.0,
        alpha_gate: float = 2.5,
        p_ref: float = 0.05,
    ):
        self.n_est = float(n_init)
        self.n_prev = float(n_init)
        self.p_cov = 80.0
        self.n_crit = float(n_crit)
        self.n_jam = float(n_jam)
        self.m_max_load = float(m_max_load)
        self.m_max_unload = float(m_max_load) * float(hysteresis_drop_ratio)
        self.q_var = float(q_var)
        self.r_base = float(r_base)
        self.alpha_gate = float(alpha_gate)
        self.p_ref = float(p_ref)

    def mfd_outflow(self, n_val: float, is_unloading: bool = False) -> float:
        n_c = max(0.0, min(n_val, self.n_jam))
        m_peak = self.m_max_unload if (is_unloading and n_c > 0.7 * self.n_crit) else self.m_max_load
        if n_c <= self.n_crit:
            return m_peak * (n_c / self.n_crit) * (2.0 - (n_c / self.n_crit))
        ratio = (n_c - self.n_crit) / max(1.0, (self.n_jam - self.n_crit))
        return m_peak * max(0.0, 1.0 - ratio ** 2)

    def step(
        self,
        q_in_veh_s: float,
        u_gate: float,
        z_obs_n: float | None,
        p_eff: float,
        rejection_rate: float,
        dt_s: float = 60.0,
    ) -> float:
        is_unloading = (self.n_est < self.n_prev) and (self.n_est > 0.8 * self.n_crit)
        outflow = self.mfd_outflow(self.n_est, is_unloading=is_unloading)
        n_pred = max(0.0, min(self.n_est + dt_s * (q_in_veh_s * u_gate - outflow), self.n_jam))

        eps = 1.0
        d_phi = (self.mfd_outflow(self.n_est + eps, is_unloading) - outflow) / eps
        f_jac = 1.0 - dt_s * d_phi
        p_pred = (f_jac ** 2) * self.p_cov + self.q_var

        self.n_prev = self.n_est
        if z_obs_n is None or math.isnan(z_obs_n) or p_eff <= 0.001 or rejection_rate >= 0.95:
            self.n_est = n_pred
            self.p_cov = max(1e-6, p_pred)
            return self.n_est

        r_t = self.r_base * (self.p_ref / max(p_eff, 0.005)) * math.exp(self.alpha_gate * rejection_rate)
        k_gain = p_pred / (p_pred + r_t)
        self.n_est = max(0.0, min(n_pred + k_gain * (z_obs_n - n_pred), self.n_jam))
        self.p_cov = max(1e-6, (1.0 - k_gain) * p_pred)
        return self.n_est
