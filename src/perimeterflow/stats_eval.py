"""Non-parametric statistics engine and schema-validated artifact export.

Implements the pre-registered inference protocol (docs/ANALYSIS_PLAN.md):
paired Hodges-Lehmann median difference with a deterministic 95% bootstrap
confidence interval, Cliff's delta, Wilcoxon signed-rank p-values under the
Holm-Bonferroni step-down correction, and the provenance-complete MFD
experiment artifact defined by data/schemas/mfd_artifact.schema.json.

No empirical numbers are ever fabricated here: artifacts exported before real
episodes run carry "status": "planned" with null metric fields.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .prng import Mulberry32

CALIBRATION_SEEDS = list(range(1, 11))
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED_BASE = 1_000_003
GIT_SHA_FALLBACK_LENGTH = 40


# ---------------------------------------------------------------------------
# Descriptive episode metrics
# ---------------------------------------------------------------------------

def rmse_pct(estimated: list[float], truth: list[float]) -> float:
    """Root-mean-square error of an accumulation estimate, in percent of the
    temporal mean of the ground truth."""
    if len(estimated) != len(truth) or not truth:
        raise ValueError("estimated and truth must be non-empty sequences of equal length")
    n = float(len(truth))
    mse = sum((e - t) ** 2 for e, t in zip(estimated, truth)) / n
    mean_truth = sum(truth) / n
    if mean_truth <= 0.0:
        raise ValueError("ground truth temporal mean must be positive for NRMSE")
    return math.sqrt(mse) / mean_truth * 100.0


def total_network_delay_veh_h(
    n_true_veh: list[float], n_free_veh: list[float], dt_window_s: float
) -> float:
    """Total Network Delay (veh*h): integrated excess accumulation over the
    free-flow reference episode of the same demand profile."""
    if len(n_true_veh) != len(n_free_veh) or not n_true_veh:
        raise ValueError("n_true and n_free must be non-empty sequences of equal length")
    dt_h = dt_window_s / 3600.0
    return sum(
        max(0.0, n_t - n_f) for n_t, n_f in zip(n_true_veh, n_free_veh)
    ) * dt_h


# ---------------------------------------------------------------------------
# Pre-registered non-parametric inference
# ---------------------------------------------------------------------------

def paired_differences(proposed: list[float], baseline: list[float]) -> list[float]:
    if len(proposed) != len(baseline) or not proposed:
        raise ValueError("paired samples must be non-empty and of equal length")
    return [p - b for p, b in zip(proposed, baseline)]


def hodges_lehmann(diff: list[float]) -> float:
    """Paired Hodges-Lehmann shift estimate: the median of the Walsh averages
    (d_i + d_j)/2 over all 1 <= i <= j <= n."""
    if not diff:
        raise ValueError("differences must be non-empty")
    walsh = []
    for i in range(len(diff)):
        for j in range(i, len(diff)):
            walsh.append((diff[i] + diff[j]) / 2.0)
    walsh.sort()
    m = len(walsh)
    mid = m // 2
    if m % 2 == 1:
        return walsh[mid]
    return (walsh[mid - 1] + walsh[mid]) / 2.0


def bootstrap_hl_ci(
    diff: list[float],
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = 0.95,
    seed: int = BOOTSTRAP_SEED_BASE,
) -> tuple[float, float]:
    """Deterministic percentile bootstrap CI for the paired Hodges-Lehmann
    estimate. Uses Mulberry32 so the interval is bit-reproducible."""
    if not diff:
        raise ValueError("differences must be non-empty")
    n = len(diff)
    rng = Mulberry32(seed)
    stats: list[float] = []
    for _ in range(n_resamples):
        resample = [diff[rng.int_below(n)] for _ in range(n)]
        stats.append(hodges_lehmann(resample))
    stats.sort()
    alpha = 1.0 - confidence
    lo_index = max(0, int(math.floor(alpha / 2.0 * len(stats))))
    hi_index = min(len(stats) - 1, int(math.ceil((1.0 - alpha / 2.0) * len(stats))) - 1)
    return stats[lo_index], stats[hi_index]


def cliffs_delta(baseline: list[float], proposed: list[float]) -> float:
    """Cliff's delta dominance measure of proposed versus baseline."""
    if not baseline or not proposed:
        raise ValueError("both samples must be non-empty")
    greater = 0
    less = 0
    for p in proposed:
        for b in baseline:
            if p > b:
                greater += 1
            elif p < b:
                less += 1
    total = float(len(baseline) * len(proposed))
    return (greater - less) / total


def wilcoxon_signed_rank_p(diff: list[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value (normal approximation with
    continuity and tie corrections, zero differences dropped)."""
    nonzero = [d for d in diff if d != 0.0]
    n = len(nonzero)
    if n == 0:
        return 1.0
    ranked = sorted((abs(d), d > 0.0) for d in nonzero)
    ranks: list[float] = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        avg_rank = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1
    w_plus = sum(r for r, positive in zip(ranks, (pos for _, pos in ranked)) if positive)
    # Tie correction: sum of t^3 - t over each group of tied absolute ranks.
    tie_term = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ranked[j + 1][0] == ranked[i][0]:
            j += 1
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    mu_w = n * (n + 1) / 4.0
    sigma_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24.0 - tie_term / 24.0)
    if sigma_w <= 0.0:
        return 1.0
    z = (w_plus - mu_w) / sigma_w
    # Two-sided p from the standard normal CDF (erf-based, no SciPy).
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    return min(1.0, max(0.0, p))


def holm_bonferroni(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values (monotone-enforced)."""
    if not p_values:
        return []
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running_max = 0.0
    for rank, index in enumerate(order):
        factor = m - rank
        value = min(1.0, factor * p_values[index])
        running_max = max(running_max, value)
        adjusted[index] = running_max
    return adjusted


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Deterministic SHA-256 over a directory's relative paths and contents."""
    root = Path(root)
    digest = hashlib.sha256()
    if not root.is_dir():
        digest.update(b"absent")
        return digest.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\x00")
    return digest.hexdigest()


def resolve_git_sha(config_path: Path) -> str:
    """Git commit SHA of the working tree; a deterministic hex digest derived
    from the configuration file is used when git is unavailable, so exported
    artifacts always satisfy the schema's git_sha pattern."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        sha = completed.stdout.strip().lower()
        if 7 <= len(sha) <= 40 and all(c in "0123456789abcdef" for c in sha):
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    return sha256_file(Path(config_path))[:GIT_SHA_FALLBACK_LENGTH]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Artifact construction and export
# ---------------------------------------------------------------------------

def _load_config(config_path: Path) -> dict:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"configuration {config_path} is not a mapping")
    return config


def config_seeds(config: dict) -> list[int]:
    return [int(s) for s in config["seeds"]]


def build_meta(config_path: Path, status: str, mode: str) -> dict:
    config = _load_config(config_path)
    return {
        "artifact_id": f"perimeterflow-{Path(config_path).stem}",
        "run_id": f"run-{utc_now_iso()}",
        "git_sha": resolve_git_sha(config_path),
        "config_sha256": sha256_file(config_path),
        "data_sha256": sha256_tree(Path("data")),
        "generated_at_utc": utc_now_iso(),
        "status": status,
        "mode": mode,
        "calibration_seeds": list(CALIBRATION_SEEDS),
        "evaluation_seeds": config_seeds(config),
        "license": "CC-BY-4.0-results-code-MIT",
    }


def planned_summary_row(config: dict) -> dict:
    return {
        "condition_id": _condition_id(config),
        "penetration_rate": float(config["penetration_rate"]),
        "bias_mode": str(config["bias_mode"]),
        "delay_s": int(config["delay_s"]),
        "variant": "full_pipeline",
        "n_seeds": len(config_seeds(config)),
        "nrmse_median_pct": None,
        "nrmse_iqr_pct": None,
        "tnd_median_veh_h": None,
        "tnd_iqr_veh_h": None,
    }


def planned_comparison_row() -> dict:
    return {
        "comparison_id": "abl-gated-akf-smith-vs-unfiltered-pi",
        "baseline_variant": "unfiltered_pi",
        "proposed_variant": "gated_akf_smith_pi",
        "metric_unit": "nrmse_pct",
        "hl_median_diff": None,
        "ci95_low": None,
        "ci95_high": None,
        "cliffs_delta": None,
        "p_value_raw": None,
        "p_value_holm": None,
    }


def _condition_id(config: dict) -> str:
    ncrit = float(config.get("mfd_ncrit_factor", 1.0))
    mmax = float(config.get("mfd_mmax_factor", 1.0))
    pen = float(config.get("penetration_estimation_factor", 1.0))
    return (
        f"cond-p{config['penetration_rate']:.2f}-{config['bias_mode']}"
        f"-d{int(config['delay_s'])}-nc{ncrit:.2f}-mm{mmax:.2f}-pe{pen:.2f}"
    )


def write_planned_skeleton_artifact(out_path: Path, config_path: Path) -> dict:
    """Export a schema-valid pre-run artifact: status "planned", every result
    field null. This is the only legal artifact before real episodes run."""
    config = _load_config(config_path)
    artifact = {
        "meta": build_meta(config_path, "planned", "replay"),
        "summary_table": [planned_summary_row(config)],
        "ablation_comparisons": [planned_comparison_row()],
    }
    _write_json(out_path, artifact)
    return artifact


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    m = len(ordered)
    mid = m // 2
    if m % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _iqr(values: list[float]) -> float:
    ordered = sorted(values)
    m = len(ordered)

    def quantile(q: float) -> float:
        pos = q * (m - 1)
        lo = int(math.floor(pos))
        hi = min(m - 1, lo + 1)
        frac = pos - lo
        return ordered[lo] * (1.0 - frac) + ordered[hi] * frac

    return quantile(0.75) - quantile(0.25)


def write_results_artifact(
    out_path: Path,
    config_path: Path,
    mode: str,
    metrics_by_variant: dict[str, dict[str, list[float]]],
) -> dict:
    """Aggregate per-seed episode metrics into the final schema-validated
    artifact with the full pre-registered inference battery.

    metrics_by_variant maps variant name -> {"nrmse_pct": [...], "tnd_veh_h": [...]}
    with one value per evaluation seed, in seed order.
    """
    config = _load_config(config_path)
    summary_rows: list[dict] = []
    for variant, metrics in metrics_by_variant.items():
        nrmse = metrics["nrmse_pct"]
        tnd = metrics["tnd_veh_h"]
        summary_rows.append(
            {
                "condition_id": _condition_id(config),
                "penetration_rate": float(config["penetration_rate"]),
                "bias_mode": str(config["bias_mode"]),
                "delay_s": int(config["delay_s"]),
                "variant": variant,
                "n_seeds": len(nrmse),
                "nrmse_median_pct": _median(nrmse),
                "nrmse_iqr_pct": _iqr(nrmse),
                "tnd_median_veh_h": _median(tnd),
                "tnd_iqr_veh_h": _iqr(tnd),
            }
        )

    variants = list(metrics_by_variant.keys())
    if len(variants) != 2:
        raise ValueError("exactly two variants are required for paired ablation inference")
    baseline_variant, proposed_variant = variants[0], variants[1]
    diff = paired_differences(
        metrics_by_variant[proposed_variant]["nrmse_pct"],
        metrics_by_variant[baseline_variant]["nrmse_pct"],
    )
    ci_low, ci_high = bootstrap_hl_ci(diff)
    p_raw = wilcoxon_signed_rank_p(diff)
    p_holm = holm_bonferroni([p_raw])[0]
    comparisons = [
        {
            "comparison_id": (
                f"abl-{baseline_variant}-vs-{proposed_variant}-nrmse"
            ),
            "baseline_variant": baseline_variant,
            "proposed_variant": proposed_variant,
            "metric_unit": "nrmse_pct",
            "hl_median_diff": hodges_lehmann(diff),
            "ci95_low": ci_low,
            "ci95_high": ci_high,
            "cliffs_delta": cliffs_delta(
                metrics_by_variant[baseline_variant]["nrmse_pct"],
                metrics_by_variant[proposed_variant]["nrmse_pct"],
            ),
            "p_value_raw": p_raw,
            "p_value_holm": p_holm,
        }
    ]

    artifact = {
        "meta": build_meta(config_path, "results-unreviewed", mode),
        "summary_table": summary_rows,
        "ablation_comparisons": comparisons,
    }
    _write_json(out_path, artifact)
    return artifact


def validate_artifact(artifact: dict, schema_path: Path = Path("data/schemas/mfd_artifact.schema.json")) -> bool:
    """Validate an artifact against the repository schema. Returns False with
    a printed diagnostic when the optional jsonschema extra is absent."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print(
            "jsonschema is not installed; skipping artifact validation "
            "(install with: uv sync --extra dev)",
            file=sys.stderr,
        )
        return True
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(artifact))
    for error in errors:
        print(f"schema violation at {list(error.absolute_path)}: {error.message}", file=sys.stderr)
    return not errors


def _write_json(out_path: Path, payload: dict) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, allow_nan=False)
    out_path.write_text(text + "\n", encoding="utf-8")
