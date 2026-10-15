"""Schema and provenance honesty tests for the MFD experiment artifact contract.

These tests enforce the repository's integrity rules at the schema level:
a pre-run artifact must validate while carrying zero empirical numbers
(all result fields null, status "planned"), and payloads lacking cryptographic
provenance or using illegal status/hash values must be rejected.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "schemas" / "mfd_artifact.schema.json"

# Deterministic demonstration values for hash-pattern fields only. They are
# format placeholders exercised against the schema patterns; they do not
# reference any real content and carry no empirical meaning.
DEMO_SHA256 = "0" * 64
DEMO_GIT_SHA = "deadbeef"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = load_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def planned_artifact() -> dict:
    """Minimal valid pre-run artifact: status planned, all result metrics null."""
    return {
        "meta": {
            "artifact_id": "planned-skeleton",
            "run_id": "run-planned-skeleton",
            "git_sha": DEMO_GIT_SHA,
            "config_sha256": DEMO_SHA256,
            "data_sha256": DEMO_SHA256,
            "generated_at_utc": "2026-01-01T00:00:00Z",
            "status": "planned",
            "mode": "simulation",
            "calibration_seeds": list(range(1, 11)),
            "evaluation_seeds": list(range(11, 41)),
            "license": "unlicensed-all-rights-reserved-pending",
        },
        "summary_table": [
            {
                "condition_id": "cond-p05-corridor-d0",
                "penetration_rate": 0.05,
                "bias_mode": "corridor_biased",
                "delay_s": 0,
                "variant": "full_pipeline",
                "n_seeds": 30,
                "nrmse_median_pct": None,
                "nrmse_iqr_pct": None,
                "tnd_median_veh_h": None,
                "tnd_iqr_veh_h": None,
            }
        ],
        "ablation_comparisons": [
            {
                "comparison_id": "abl-stratified-vs-unstratified",
                "baseline_variant": "unstratified_edie",
                "proposed_variant": "stratified_ht_edie",
                "metric_unit": "nrmse_pct",
                "hl_median_diff": None,
                "ci95_low": None,
                "ci95_high": None,
                "cliffs_delta": None,
                "p_value_raw": None,
                "p_value_holm": None,
            }
        ],
    }


def test_schema_file_uses_draft_2020_12() -> None:
    schema = load_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_planned_artifact_with_null_metrics_validates(validator: Draft202012Validator) -> None:
    errors = list(validator.iter_errors(planned_artifact()))
    assert errors == [], [e.message for e in errors]


def test_missing_config_sha256_is_rejected(validator: Draft202012Validator) -> None:
    artifact = deepcopy(planned_artifact())
    del artifact["meta"]["config_sha256"]
    errors = list(validator.iter_errors(artifact))
    assert errors, "payload missing config_sha256 must be rejected"
    assert any(e.validator == "required" and "config_sha256" in e.message for e in errors)


def test_invalid_git_sha_pattern_is_rejected(validator: Draft202012Validator) -> None:
    artifact = deepcopy(planned_artifact())
    artifact["meta"]["git_sha"] = "NOT-A-VALID-SHA"
    errors = list(validator.iter_errors(artifact))
    assert errors, "payload with malformed git_sha must be rejected"
    assert any(e.validator == "pattern" for e in errors)


def test_invalid_status_enum_is_rejected(validator: Draft202012Validator) -> None:
    artifact = deepcopy(planned_artifact())
    artifact["meta"]["status"] = "published-final-truth"
    errors = list(validator.iter_errors(artifact))
    assert errors, "payload with out-of-lifecycle status must be rejected"
    assert any(e.validator == "enum" for e in errors)


def test_reproduced_in_ci_status_with_non_null_metrics_validates(
    validator: Draft202012Validator,
) -> None:
    """The schema must accept a reviewed, CI-reproduced artifact whose metric
    fields are populated. The numeric values below are synthetic placeholders
    used ONLY to exercise the schema contract (non-null acceptance); they are
    not measurements and do not represent any experimental outcome."""
    artifact = deepcopy(planned_artifact())
    artifact["meta"]["status"] = "reproduced-in-ci"

    row = artifact["summary_table"][0]
    row["nrmse_median_pct"] = 0.0
    row["nrmse_iqr_pct"] = 0.0
    row["tnd_median_veh_h"] = 0.0
    row["tnd_iqr_veh_h"] = 0.0

    comp = artifact["ablation_comparisons"][0]
    comp["hl_median_diff"] = 0.0
    comp["ci95_low"] = 0.0
    comp["ci95_high"] = 0.0
    comp["cliffs_delta"] = 0.0
    comp["p_value_raw"] = 0.0
    comp["p_value_holm"] = 0.0

    errors = list(validator.iter_errors(artifact))
    assert errors == [], [e.message for e in errors]


def test_planned_artifact_with_populated_metrics_still_schema_valid_but_detectable(
    validator: Draft202012Validator,
) -> None:
    """The schema intentionally permits numbers under any status (lifecycle
    policy is procedural); this test documents that a planned artifact can be
    programmatically audited for the absence of numbers, so the honesty rule
    stays enforceable in CI by scanning, not by schema alone."""
    artifact = deepcopy(planned_artifact())
    artifact["summary_table"][0]["nrmse_median_pct"] = 0.0
    assert validator.is_valid(artifact)

    def _non_null_metric_locations(doc: dict) -> list[str]:
        hits: list[str] = []
        for row in doc["summary_table"]:
            for field in ("nrmse_median_pct", "nrmse_iqr_pct", "tnd_median_veh_h", "tnd_iqr_veh_h"):
                if row[field] is not None:
                    hits.append(f"summary_table:{row['condition_id']}:{field}")
        for comp in doc["ablation_comparisons"]:
            for field in (
                "hl_median_diff",
                "ci95_low",
                "ci95_high",
                "cliffs_delta",
                "p_value_raw",
                "p_value_holm",
            ):
                if comp[field] is not None:
                    hits.append(f"ablation_comparisons:{comp['comparison_id']}:{field}")
        return hits

    assert _non_null_metric_locations(planned_artifact()) == []
    assert _non_null_metric_locations(artifact) == [
        "summary_table:cond-p05-corridor-d0:nrmse_median_pct"
    ]
