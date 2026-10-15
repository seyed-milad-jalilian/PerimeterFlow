import copy
import json
from pathlib import Path
import jsonschema
import pytest
from perimeterflow.stats_eval import validate_artifact_dict, write_planned_skeleton_artifact


def test_planned_skeleton_passes_schema(tmp_path: Path) -> None:
    out_file = tmp_path / "ensemble.json"
    cfg_file = Path("configs/evaluate_seeds.yaml")
    write_planned_skeleton_artifact(out_file, cfg_file)
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["meta"]["status"] == "planned"
    assert data["summary_table"][0]["nrmse_median_pct"] is None
    validate_artifact_dict(data)


def test_schema_rejects_missing_provenance_hashes(tmp_path: Path) -> None:
    out_file = tmp_path / "ensemble.json"
    write_planned_skeleton_artifact(out_file, Path("configs/evaluate_seeds.yaml"))
    data = json.loads(out_file.read_text(encoding="utf-8"))

    corrupted = copy.deepcopy(data)
    corrupted["meta"]["config_sha256"] = "not-a-valid-sha256"
    with pytest.raises(jsonschema.ValidationError):
        validate_artifact_dict(corrupted)
