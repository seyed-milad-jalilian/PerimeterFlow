import json
from pathlib import Path
import matplotlib.pyplot as plt


def generate_ablation_figure(artifact_path: Path, out_pdf_path: Path) -> None:
    """Generates a vector PDF bar chart of NRMSE(N) across ablation variants from ensemble.json."""
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    status = data["meta"]["status"]

    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    if status in ("planned", "running") or data["summary_table"][0]["nrmse_median_pct"] is None:
        ax.text(0.5, 0.5, "PENDING SIMULATION SWEEP", ha="center", va="center", fontsize=12)
        ax.set_axis_off()
    else:
        variants = [row["variant"] for row in data["summary_table"]]
        medians = [row["nrmse_median_pct"] for row in data["summary_table"]]
        iqrs = [row["nrmse_iqr_pct"] * 0.5 for row in data["summary_table"]]

        ax.bar(variants, medians, yerr=iqrs, capsize=4, edgecolor="black", linewidth=0.8)
        ax.set_ylabel("Accumulation NRMSE(N) [%]")
        ax.set_xlabel("Ablation Pipeline Variant")
        ax.set_title("MFD State Estimation Error Across 30 Evaluation Seeds")
        ax.grid(axis="y", linestyle="--", alpha=0.5)

    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_pdf_path, format="pdf")
    plt.close(fig)


if __name__ == "__main__":
    generate_ablation_figure(Path("results/ensemble.json"), Path("report/figures/ablation_nrmse.pdf"))
