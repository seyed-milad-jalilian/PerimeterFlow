import csv
import math
from pathlib import Path

import pytest

from perimeterflow import AmsterdamValidationResult, evaluate_amsterdam_trajectory_slice

SITES = [
    ("AMS-ART-01", "arterial", 120.0, 200.0, 42.0),
    ("AMS-ART-02", "arterial", 340.0, 210.0, 38.0),
    ("AMS-ART-03", "arterial", 560.0, 195.0, 45.0),
    ("AMS-LOC-01", "local", 130.0, 410.0, 28.0),
    ("AMS-LOC-02", "local", 350.0, 405.0, 31.0),
    ("AMS-LOC-03", "local", 570.0, 415.0, 26.0),
]


def _write_synthetic_amsterdam_slice(csv_path: Path, n_windows: int = 5) -> Path:
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp_s",
                "site_id",
                "link_class",
                "x_m",
                "y_m",
                "speed_kmh",
                "true_accumulation_veh",
            ]
        )
        for w in range(n_windows):
            true_n = 150.0 + 30.0 * w
            for site_id, link_class, x_m, y_m, speed_kmh in SITES:
                for offset_s in (0.0, 10.0, 20.0):
                    t_s = w * 60.0 + offset_s
                    writer.writerow(
                        [
                            f"{t_s:.1f}",
                            site_id,
                            link_class,
                            f"{x_m:.1f}",
                            f"{y_m:.1f}",
                            f"{speed_kmh + 2.0 * w:.1f}",
                            f"{true_n:.1f}",
                        ]
                    )
    return csv_path


def test_evaluate_amsterdam_trajectory_slice_runs_and_returns_valid_result(tmp_path: Path):
    csv_path = _write_synthetic_amsterdam_slice(tmp_path / "ams_arterial_slice.csv")

    result = evaluate_amsterdam_trajectory_slice(csv_path, penetration_rate=0.03)

    assert isinstance(result, AmsterdamValidationResult)

    assert result.slice_id == "ams_arterial_slice"
    assert result.penetration_rate == pytest.approx(0.03)
    for value in (
        result.slice_id,
        result.penetration_rate,
        result.nrmse_unstratified_pct,
        result.nrmse_stratified_pcakf_pct,
    ):
        assert value is not None

    for value in (result.nrmse_unstratified_pct, result.nrmse_stratified_pcakf_pct):
        assert math.isfinite(value)
        assert value >= 0.0

    assert result.closed_loop_actuation_supported is False


def test_evaluate_amsterdam_trajectory_slice_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        evaluate_amsterdam_trajectory_slice(tmp_path / "nonexistent_slice.csv")
