from smda_scheduler.daemon import DaemonResult, TickResult, run_daemon


def test_tickresult_has_aggregate_counts():
    result = TickResult(status="dispatched", dispatched=2, blocked=1, failed=0, skipped=3)
    assert (result.dispatched, result.blocked, result.failed, result.skipped) == (2, 1, 0, 3)


def test_run_daemon_ticks_until_max_ticks():
    ticks = []
    sleeps = []

    def tick() -> TickResult:
        ticks.append("tick")
        return TickResult(status="idle")

    result = run_daemon(
        tick,
        max_ticks=3,
        interval_seconds=0.5,
        sleep=sleeps.append,
    )

    assert result == DaemonResult(
        status="stopped",
        ticks=3,
        last_tick=TickResult(status="idle"),
    )
    assert ticks == ["tick", "tick", "tick"]
    assert sleeps == [0.5, 0.5]


def test_run_daemon_stops_on_tick_failure():
    def tick() -> TickResult:
        raise RuntimeError("boom")

    result = run_daemon(
        tick,
        max_ticks=3,
        interval_seconds=0.5,
        sleep=lambda seconds: None,
    )

    assert result.status == "failed"
    assert result.ticks == 0
    assert result.error_message == "boom"
