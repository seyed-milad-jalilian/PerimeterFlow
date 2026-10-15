import json
import math
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from perimeterflow.parity import generate_parity_vectors
from perimeterflow.quality_gate import ProbePing, run_stateful_quality_gate

LINK_CLASSES = ("arterial", "local")
VEH_IDS = ("veh_a", "veh_b", "veh_c")


@st.composite
def _ping_streams(draw):
    count = draw(st.integers(min_value=1, max_value=12))
    pings = []
    clocks: dict[str, float] = {}
    for _ in range(count):
        veh_id = draw(st.sampled_from(VEH_IDS))
        gap = draw(st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False))
        timestamp = clocks.get(veh_id, 0.0) + gap
        clocks[veh_id] = timestamp
        pings.append(
            ProbePing(
                veh_id=veh_id,
                link_class=draw(st.sampled_from(LINK_CLASSES)),
                timestamp_s=timestamp,
                x_obs_m=draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)),
                y_obs_m=draw(st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)),
                speed_obs_ms=draw(st.floats(min_value=0.0, max_value=25.0, allow_nan=False, allow_infinity=False)),
                snap_dist_m=draw(st.floats(min_value=0.0, max_value=12.0, allow_nan=False, allow_infinity=False)),
            )
        )
    return pings


@st.composite
def _noisy_ping_streams(draw):
    count = draw(st.integers(min_value=1, max_value=12))
    pings = []
    clocks: dict[str, float] = {}
    for _ in range(count):
        veh_id = draw(st.sampled_from(VEH_IDS))
        gap = draw(st.floats(min_value=0.5, max_value=30.0, allow_nan=False, allow_infinity=False))
        timestamp = clocks.get(veh_id, 0.0) + gap
        clocks[veh_id] = timestamp
        x_obs = draw(
            st.one_of(
                st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
                st.just(float("nan")),
            )
        )
        y_obs = draw(
            st.one_of(
                st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
                st.just(float("nan")),
            )
        )
        pings.append(
            ProbePing(
                veh_id=veh_id,
                link_class=draw(st.sampled_from(LINK_CLASSES)),
                timestamp_s=timestamp,
                x_obs_m=x_obs,
                y_obs_m=y_obs,
                speed_obs_ms=draw(st.floats(min_value=-5.0, max_value=120.0, allow_nan=False, allow_infinity=False)),
                snap_dist_m=draw(st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False)),
            )
        )
    return pings


def test_isolated_spike_rejects_only_outlier_and_preserves_anchor():
    pings = [
        ProbePing("veh_a", "arterial", 0.0, 0.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "arterial", 5.0, 50.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "arterial", 6.0, 100.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "arterial", 11.0, 100.0, 0.0, 10.0, 0.0),
    ]
    summary = run_stateful_quality_gate(pings)
    assert summary.total_pings == 4
    assert summary.rejected_spatial == 0
    assert summary.rejected_kinematic == 1
    assert len(summary.segments) == 3
    assert [seg.timestamp_s for seg in summary.segments] == [0.0, 5.0, 11.0]
    next_valid = summary.segments[-1]
    assert next_valid.tau_s == 6.0
    assert next_valid.d_m == 50.0
    assert math.isclose(summary.rejection_rate, 1.0 / 4.0)


@settings(max_examples=200, deadline=None)
@given(pings=_ping_streams())
def test_accepted_segment_increments_are_non_negative(pings):
    summary = run_stateful_quality_gate(pings)
    for seg in summary.segments:
        assert seg.tau_s >= 0.0
        assert seg.d_m >= 0.0
        assert math.isfinite(seg.tau_s)
        assert math.isfinite(seg.d_m)


@settings(max_examples=200, deadline=None)
@given(pings=_noisy_ping_streams())
def test_rejection_accounting_and_rate_bounds(pings):
    summary = run_stateful_quality_gate(pings)
    assert summary.total_pings == len(pings)
    assert summary.rejected_spatial >= 0
    assert summary.rejected_kinematic >= 0
    assert summary.rejected_spatial + summary.rejected_kinematic + len(summary.segments) == summary.total_pings
    assert 0.0 <= summary.rejection_rate <= 1.0
    expected_rate = (summary.rejected_spatial + summary.rejected_kinematic) / summary.total_pings
    assert math.isclose(summary.rejection_rate, expected_rate, rel_tol=1e-12, abs_tol=1e-12)


def test_gap_over_15s_resets_anchor_to_zero_increment_segment():
    pings = [
        ProbePing("veh_a", "local", 0.0, 0.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "local", 10.0, 100.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "local", 26.0, 200.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "local", 40.0, 300.0, 0.0, 10.0, 0.0),
    ]
    summary = run_stateful_quality_gate(pings)
    assert summary.total_pings == 4
    assert summary.rejected_spatial == 0
    assert summary.rejected_kinematic == 0
    assert [(seg.timestamp_s, seg.tau_s, seg.d_m) for seg in summary.segments] == [
        (0.0, 0.0, 0.0),
        (10.0, 10.0, 100.0),
        (26.0, 0.0, 0.0),
        (40.0, 14.0, 100.0),
    ]
    assert summary.rejection_rate == 0.0


def test_nan_coordinates_are_spatially_rejected():
    pings = [
        ProbePing("veh_a", "arterial", 0.0, 0.0, 0.0, 10.0, 0.0),
        ProbePing("veh_a", "arterial", 5.0, float("nan"), 0.0, 10.0, 0.0),
        ProbePing("veh_a", "arterial", 6.0, 0.0, float("nan"), 10.0, 0.0),
        ProbePing("veh_a", "arterial", 7.0, 50.0, 0.0, 10.0, 13.0),
        ProbePing("veh_a", "arterial", 10.0, 100.0, 0.0, 10.0, 0.0),
    ]
    summary = run_stateful_quality_gate(pings)
    assert summary.total_pings == 5
    assert summary.rejected_spatial == 3
    assert summary.rejected_kinematic == 0
    assert [seg.timestamp_s for seg in summary.segments] == [0.0, 10.0]
    last = summary.segments[-1]
    assert last.tau_s == 10.0
    assert last.d_m == 100.0
    assert math.isclose(summary.rejection_rate, 3.0 / 5.0)


def test_golden_parity_vectors_file_matches_generator():
    golden_path = Path(__file__).resolve().parents[1] / "data" / "golden" / "parity_vectors.json"
    assert golden_path.exists()
    on_disk = json.loads(golden_path.read_text(encoding="utf-8"))
    assert on_disk == generate_parity_vectors()
