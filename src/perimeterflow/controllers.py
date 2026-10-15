from collections import deque
from .estimators import HysteresisAwarePCAKF


class ResidualCorrectedSmithPIController:
    """
    Smith-Predictor PI Perimeter Controller with dimensionless normalized error e_t.
    - Reduces strictly to a tuned normalized PI controller when delay_steps == 0.
    - Preserves pure open-loop rollout predictions in model_pred_history to avoid
      double-counting residuals under MFD parameter misspecification.
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
    ):
        self.n_crit = max(1.0, float(n_crit))
        self.kp_norm = float(kp_norm)
        self.ki_norm = float(ki_norm)
        self.u_min = float(u_min)
        self.u_max = float(u_max)
        self.delay_steps = max(0, int(delay_steps))
        self.residual_gain = float(residual_gain)

        self.u_prev = 1.0
        self.err_prev = 0.0
        self.actuation_history: deque[tuple[float, float]] = deque(maxlen=self.delay_steps)
        self.model_pred_history: deque[float] = deque(maxlen=self.delay_steps + 1)
        self.model_pred_history.append(self.n_crit)

    def compute_u(
        self,
        n_delayed_obs: float,
        q_in_current: float,
        kf_model: HysteresisAwarePCAKF,
        dt_s: float = 60.0,
    ) -> float:
        if self.delay_steps == 0 or len(self.actuation_history) == 0:
            n_rollout = n_delayed_obs
            n_effective = n_delayed_obs
        else:
            n_rollout = n_delayed_obs
            for past_q_in, past_u in self.actuation_history:
                outflow = kf_model.mfd_outflow(n_rollout, is_unloading=False)
                n_rollout = max(0.0, min(n_rollout + dt_s * (past_q_in * past_u - outflow), kf_model.n_jam))

            n_model_delayed = self.model_pred_history[0]
            residual = n_delayed_obs - n_model_delayed
            n_effective = max(0.0, min(n_rollout + self.residual_gain * residual, kf_model.n_jam))

        err_t = (n_effective - self.n_crit) / self.n_crit
        delta_u = -self.kp_norm * (err_t - self.err_prev) - self.ki_norm * err_t
        u_new = max(self.u_min, min(self.u_max, self.u_prev + delta_u))

        if self.delay_steps > 0:
            self.actuation_history.append((q_in_current, u_new))
            self.model_pred_history.append(n_rollout)

        self.u_prev = u_new
        self.err_prev = err_t
        return u_new
