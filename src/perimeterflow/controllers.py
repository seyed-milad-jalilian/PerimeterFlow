from collections import deque
from .estimators import HysteresisAwarePCAKF


class ResidualCorrectedSmithPIController:
    """
    Smith-Predictor PI Perimeter Controller with dimensionless normalized error e_t.

    Delay model: a telemetry delay of tau_d = (d_int + theta) * dt_s is decomposed into
    `delay_steps = d_int` full control windows plus a fractional sub-window remainder
    `delay_frac = theta` in [0, 1). The caller is responsible for blending the raw
    observations into the fractionally delayed observation
    z_del(t) = (1 - theta) z(t - d_int) + theta z(t - d_int - 1) before passing it as
    `n_delayed_obs`.

    - Reduces strictly (bit-for-bit) to a tuned normalized PI controller when
      delay_steps == 0 and delay_frac == 0.0, and reproduces the legacy integer-step
      rollout exactly whenever delay_frac == 0.0.
    - When theta > 0, after rolling forward over the d_int buffered actuations, a
      fractional theta * dt_s forward MFD Euler step is applied using the most recent
      actuation (q_{t-1}, u_{t-1}), and the residual correction is blended against the
      fractionally interpolated model prediction
      N_model,del(t) = (1 - theta) P(t - d_int - 1) + theta P(t - d_int - 2),
      where P(k) denotes the stored pure open-loop rollout prediction of N(k). At
      theta -> 0 this converges exactly to the legacy residual P(t - d_int - 1) stored
      at the head of `model_pred_history`.
    - The rollout/residual machinery activates only once at least one past actuation
      exists, which preserves the exact legacy activation behavior for integer delays.
    """
    def __init__(
        self,
        n_crit: float,
        kp_norm: float = 0.85,
        ki_norm: float = 0.22,
        u_min: float = 0.15,
        u_max: float = 1.0,
        delay_steps: int = 0,
        residual_gain: float = 0.5,
        delay_frac: float = 0.0,
    ):
        self.n_crit = max(1.0, float(n_crit))
        self.kp_norm = float(kp_norm)
        self.ki_norm = float(ki_norm)
        self.u_min = float(u_min)
        self.u_max = float(u_max)
        self.delay_steps = max(0, int(delay_steps))
        self.residual_gain = float(residual_gain)
        delay_frac_f = float(delay_frac)
        if not (0.0 <= delay_frac_f < 1.0):
            raise ValueError("delay_frac must satisfy 0.0 <= delay_frac < 1.0")
        self.delay_frac = delay_frac_f

        self.u_prev = 1.0
        self.err_prev = 0.0
        self.actuation_history: deque[tuple[float, float]] = deque(maxlen=self.delay_steps)
        pred_capacity = self.delay_steps + (2 if self.delay_frac > 0.0 else 1)
        self.model_pred_history: deque[float] = deque(maxlen=pred_capacity)
        self.model_pred_history.append(self.n_crit)
        self._last_actuation: tuple[float, float] | None = None

    def compute_u(
        self,
        n_delayed_obs: float,
        q_in_current: float,
        kf_model: HysteresisAwarePCAKF,
        dt_s: float = 60.0,
    ) -> float:
        has_full_rollout = self.delay_steps > 0 and len(self.actuation_history) > 0
        has_frac_rollout = self.delay_frac > 0.0 and self._last_actuation is not None

        if not (has_full_rollout or has_frac_rollout):
            n_rollout = n_delayed_obs
            n_effective = n_delayed_obs
        else:
            n_rollout = n_delayed_obs
            if has_full_rollout:
                for past_q_in, past_u in self.actuation_history:
                    outflow = kf_model.mfd_outflow(n_rollout, is_unloading=False)
                    n_rollout = max(0.0, min(n_rollout + dt_s * (past_q_in * past_u - outflow), kf_model.n_jam))
            if has_frac_rollout:
                q_prev, u_prev = self._last_actuation
                outflow = kf_model.mfd_outflow(n_rollout, is_unloading=False)
                n_rollout = max(
                    0.0,
                    min(n_rollout + self.delay_frac * dt_s * (q_prev * u_prev - outflow), kf_model.n_jam),
                )
            if self.delay_frac > 0.0 and len(self.model_pred_history) >= 2:
                n_model_delayed = (
                    (1.0 - self.delay_frac) * self.model_pred_history[1]
                    + self.delay_frac * self.model_pred_history[0]
                )
            else:
                n_model_delayed = self.model_pred_history[0]
            residual = n_delayed_obs - n_model_delayed
            n_effective = max(0.0, min(n_rollout + self.residual_gain * residual, kf_model.n_jam))

        err_t = (n_effective - self.n_crit) / self.n_crit
        delta_u = -self.kp_norm * (err_t - self.err_prev) - self.ki_norm * err_t
        u_new = max(self.u_min, min(self.u_max, self.u_prev + delta_u))

        if self.delay_steps > 0 or self.delay_frac > 0.0:
            self.actuation_history.append((q_in_current, u_new))
            self._last_actuation = (q_in_current, u_new)
            self.model_pred_history.append(n_rollout)

        self.u_prev = u_new
        self.err_prev = err_t
        return u_new
