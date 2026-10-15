from hypothesis import given, strategies as st
from perimeterflow.quality_gate import GateConfig, ProbePing, run_stateful_quality_gate


def test_isolated_multipath_spike_preserves_anchor_for_next_valid_ping() -> None:
    pings = [
        ProbePing("veh_1", "arterial", 0.0, 0.0, 0.0, 10.0, 1.0),
        ProbePing("veh_1", "arterial", 5.0, 50.0, 0.0, 10.0, 1.0),
        # Corrupted 150m jump at t=10s -> v = 30 m/s > 22.22 m/s ceiling
        ProbePing("veh_1", "arterial", 10.0, 200.0, 0.0, 30.0, 1.0),
        # True ping at t=15s is at x=150m (100m over 10s from t=5s anchor => v = 10 m/s, a = 0 m/s^2)
        ProbePing("veh_1", "arterial", 15.0, 150.0, 0.0, 10.0, 1.0),
    ]
    summary = run_stateful_quality_gate(pings, GateConfig())
    assert summary.total_pings == 4
    assert summary.rejected_kinematic == 1
    assert len(summary.segments) == 3
    assert summary.segments[-1].timestamp_s == 15.0
    assert summary.segments[-1].tau_s == 10.0
    assert summary.segments[-1].d_m == 100.0


@given(
    st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=25,
    )
)
def test_property_emitted_segments_strictly_non_negative(raw_tuples: list[tuple[float, float, float]]) -> None:
    pings = [
        ProbePing("v_prop", "arterial", t, x, 0.0, v, 1.0)
        for t, x, v in raw_tuples
    ]
    res = run_stateful_quality_gate(pings)
    for seg in res.segments:
        assert seg.tau_s >= 0.0
        assert seg.d_m >= 0.0
