from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import jsonschema
import numpy as np
from scipy.stats import wilcoxon
from .prng import Mulberry32


def get_git_sha() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        return sha if len(sha) >= 7 else "0000000"
    except Exception:
        return "0000000"


def hodges_lehmann_paired(
    x: np.ndarray,
    y: np.ndarray,
    seed: int = 42,
    n_boot: int = 2000,
) -> tuple[float, float, float]:
    """
    Computes the Hodges-Lehmann estimator of paired differences d = y - x
    (median of Walsh averages (d_i + d_j)/2 for i <= j) and 95% bootstrap CI.
    """
    d = np.asarray(y, dtype=np.float64) - np.asarray(x, dtype=np.float64)
    n = len(d)
    walsh = [(d[i] + d[j]) / 2.0 for i in range(n) for j in range(i, n)]
    hl_est = float(np.median(walsh))

    rng = Mulberry32(seed)
    boot_vals = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = [int(rng.next_float() * n) for _ in range(n)]
        d_b = d[idx]
        w_b = [(d_b[i] + d_b[j]) / 2.0 for i in range(n) for j in range(i, n)]
        boot_vals[b] = np.median(w_b)

    return hl_est, float(np.percentile(boot_vals, 2.5)), float(np.percentile(boot_vals, 97.5))


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    """Non-parametric effect size Cliff's delta in [-1, 1]."""
    x_arr = np.asarray(x, dtype=np.float64)
    y_arr = np.asarray(y, dtype=np.float64)
    dominance = 0
    for xi, yj in itertools.product(x_arr, y_arr):
        if yj > xi:
            dominance += 1
        elif yj < xi:
            dominance -= 1
    return float(dominance) / float(len(x_arr) * len(y_arr))


def holm_bonferroni_correction(p_values: list[float]) -> list[float]:
    """Step-down Holm-Bonferroni family-wise error rate correction."""
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    corrected = [0.0] * m
    running_max = 0.0
    for rank, (orig_idx, p_val) in enumerate(indexed):
        adj = min(1.0, p_val * (m - rank))
        running_max = max(running_max, adj)
        corrected[orig_idx] = running_max
    return corrected


def paired_wilcoxon_pvalue(x: np.ndarray, y: np.ndarray) -> float:
    d = np.asarray(y, dtype=np.float64) - np.asarray(x, dtype=np.float64)
    if np.allclose(d, 0.0):
        return 1.0
    res = wilcoxon(d, alternative="two-sided", zero_method="wilcox")
    return float(res.pvalue)


def validate_artifact_dict(payload: dict, schema_path: Path = Path("data/schemas/mfd_artifact.schema.json")) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(instance=payload, schema=schema)


def write_planned_skeleton_artifact(out_path: Path, config_path: Path) -> None:
    """
    Writes an honest 'planned' state artifact prior to full execution.
    All numeric result fields are strictly null until simulations complete.
    """
    git_sha = get_git_sha()
    cfg_bytes = config_path.read_bytes() if config_path.exists() else b"planned"
    cfg_hash = hashlib.sha256(cfg_bytes).hexdigest()

    payload = {
        "meta": {
            "artifact_id": "perimeterflow-mfd-ensemble",
            "run_id": "pending-execution",
            "git_sha": git_sha,
            "config_sha256": cfg_hash,
            "data_sha256": "0" * 64,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "planned",
            "mode": "simulation",
            "calibration_seeds": list(range(1, 11)),
            "evaluation_seeds": list(range(11, 41)),
            "license": "MIT",
        },
        "summary_table": [
            {
                "condition_id": "p02_corridor_delay60_baseline",
                "penetration_rate": 0.02,
                "bias_mode": "corridor_biased",
                "delay_s": 60,
                "variant": "G0_F0_C0",
                "n_seeds": 0,
                "nrmse_median_pct": None,
                "nrmse_iqr_pct": None,
                "tnd_median_veh_h": None,
                "tnd_iqr_veh_h": None,
            },
            {
                "condition_id": "p02_corridor_delay60_smith_pi",
                "penetration_rate": 0.02,
                "bias_mode": "corridor_biased",
                "delay_s": 60,
                "variant": "G1_F1_C1",
                "n_seeds": 0,
                "nrmse_median_pct": None,
                "nrmse_iqr_pct": None,
                "tnd_median_veh_h": None,
                "tnd_iqr_veh_h": None,
            },
        ],
        "ablation_comparisons": [
            {
                "comparison_id": "G0_F0_C0_vs_G1_F1_C1_nrmse",
                "baseline_variant": "G0_F0_C0",
                "proposed_variant": "G1_F1_C1",
                "metric_unit": "pct",
                "hl_median_diff": None,
                "ci95_low": None,
                "ci95_high": None,
                "cliffs_delta": None,
                "p_value_raw": None,
                "p_value_holm": None,
            }
        ],
    }
    validate_artifact_dict(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
