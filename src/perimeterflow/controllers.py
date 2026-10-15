from collections import deque
from .estimators import HysteresisAwarePCAKF


class ResidualCorrectedSmithPIController:
    """
    Smith-Predictor PI Perimeter Controller with dimensionless normalized error e_t.
    Reduces strictly to a tuned normalized PI controller when delay_steps == 0.
    """
    def __init__(
        self,
        n_crit: float,
        kp_norm: float = 0.85,
        ki_norm: float = 0.22,
        u_min: float = 0.15,
        delay_steps: int = 0,
    ):
        self.n_crit = max(1.0, n_crit)
        self.kp_norm = kp_norm
        self.ki_norm = ki_norm
        self.u_min = u_min
        self.delay_steps = max(0, int(delay_steps))
        self.u_prev = 1.0
        self.err_prev = 0.0
        self.actuation_history: deque[tuple[float, float]] = deque(maxlen=self.delay_steps)
        self.model_pred_history: deque[float] = deque(maxlen=self.delay_steps + 1)
        self.model_pred_history.append(n_crit)

    def compute_u(
        self,
        n_delayed_obs: float,
        q_in_current: float,
        kf_model: HysteresisAwarePCAKF,
        dt_s: float = 60.0,
    ) -> float:
        if self.delay_steps == 0 or len(self.actuation_history) == 0:
            n_effective = n_delayed_obs
        else:
            n_rollout = n_delayed_obs
            for past_q_in, past_u in self.actuation_history:
                outflow = kf_model.mfd_outflow(n_rollout)
                n_rollout = max(0.0, min(n_rollout + dt_s * (past_q_in * past_u - outflow), kf_model.n_jam))

            n_model_delayed = self.model_pred_history[0]
            residual = n_delayed_obs - n_model_delayed
            n_effective = max(0.0, min(n_rollout + 0.5 * residual, kf_model.n_jam))

        err_t = (n_effective - self.n_crit) / self.n_crit
        delta_u = -self.kp_norm * (err_t - self.err_prev) - self.ki_norm * err_t
        u_new = max(self.u_min, min(1.0, self.u_prev + delta_u))

        if self.delay_steps > 0:
            self.actuation_history.append((q_in_current, u_new))
            self.model_pred_history.append(n_effective)

        self.u_prev = u_new
        self.err_prev = err_t
        return u_new
