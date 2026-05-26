from services import runtime_state


def test_runtime_state_records_recent_error_as_degraded() -> None:
    runtime_state.reset_runtime_state()

    runtime_state.record_runtime_error(
        "worker",
        RuntimeError("temporary failure"),
        now=100.0,
    )

    health = runtime_state.get_runtime_health(now=110.0, warning_window_seconds=60)

    assert health["status"] == "degraded"
    assert health["components"][0]["component"] == "worker"
    assert health["components"][0]["error_count"] == 1
    assert health["components"][0]["seconds_since_last_error"] == 10.0

    runtime_state.reset_runtime_state()


def test_runtime_state_old_error_is_not_degraded() -> None:
    runtime_state.reset_runtime_state()

    runtime_state.record_runtime_error(
        "worker",
        RuntimeError("old failure"),
        now=100.0,
    )

    health = runtime_state.get_runtime_health(now=500.0, warning_window_seconds=60)

    assert health["status"] == "ok"
    assert health["components"][0]["error_count"] == 1

    runtime_state.reset_runtime_state()
