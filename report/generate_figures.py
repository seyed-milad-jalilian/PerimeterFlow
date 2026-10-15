"""Generate vector (PDF) figures for the IEEE report from results/ensemble.json.

All values are read from the artifact; nothing is hardcoded. When the artifact
is pre-run ("planned"/"running") no figures are produced - an honest report
has no results figures yet. Requires the optional matplotlib dependency:
    uv pip install matplotlib
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_ARTIFACT = Path("results/ensemble.json")
DEFAULT_OUT_DIR = Path("report/figures")
VARIANT_LABELS = {
    "unfiltered_pi": "Unfiltered + PI",
    "gated_akf_smith": "Gate + HT + AKF + Smith-PI",
}


def generate_figures(artifact_path: Path, out_dir: Path) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(
            "matplotlib is not installed; install it with "
            "`uv pip install matplotlib` to render report figures",
            file=sys.stderr,
        )
        return []

    data = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    meta = data["meta"]
    if meta["status"] in ("planned", "running"):
        print(
            f"artifact status is '{meta['status']}'; no result figures are "
            "produced before real sweep data exists"
        )
        return []

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []

    # Figure 1: NRMSE(N) medians with IQR whiskers across variants.
    rows = [r for r in data["summary_table"] if r["nrmse_median_pct"] is not None]
    if rows:
        labels = [VARIANT_LABELS.get(r["variant"], r["variant"]) for r in rows]
        medians = [r["nrmse_median_pct"] for r in rows]
        iqrs = [r["nrmse_iqr_pct"] for r in rows]
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        ax.bar(labels, medians, yerr=iqrs, capsize=4, color="#336699")
        ax.set_ylabel(r"$\mathrm{NRMSE}(N)$ [%]")
        ax.set_title(f"Estimation error over $n={meta['evaluation_seeds'][-1] - meta['evaluation_seeds'][0] + 1}$ held-out seeds")
        ax.grid(axis="y", linestyle=":", linewidth=0.5)
        fig.tight_layout()
        path = out_dir / "fig_nrmse.pdf"
        fig.savefig(path)
        plt.close(fig)
        produced.append(path)

    # Figure 2: Total Network Delay medians with IQR whiskers.
    rows = [r for r in data["summary_table"] if r["tnd_median_veh_h"] is not None]
    if rows:
        labels = [VARIANT_LABELS.get(r["variant"], r["variant"]) for r in rows]
        medians = [r["tnd_median_veh_h"] for r in rows]
        iqrs = [r["tnd_iqr_veh_h"] for r in rows]
        fig, ax = plt.subplots(figsize=(4.2, 2.8))
        ax.bar(labels, medians, yerr=iqrs, capsize=4, color="#996633")
        ax.set_ylabel(r"TND [veh$\cdot$h]")
        ax.set_title("Total Network Delay across pipeline variants")
        ax.grid(axis="y", linestyle=":", linewidth=0.5)
        fig.tight_layout()
        path = out_dir / "fig_tnd.pdf"
        fig.savefig(path)
        plt.close(fig)
        produced.append(path)

    return produced


if __name__ == "__main__":
    artifact = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ARTIFACT
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT_DIR
    figures = generate_figures(artifact, out_dir)
    for figure in figures:
        print(f"figure written: {figure}")
    if not figures:
        print("no figures produced")
