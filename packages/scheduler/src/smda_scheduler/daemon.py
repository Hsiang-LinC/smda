from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TickResult:
    status: str
    detail: str | None = None
    dispatched: int = 0
    blocked: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class DaemonResult:
    status: str
    ticks: int
    last_tick: TickResult | None = None
    error_message: str | None = None


Tick = Callable[[], TickResult]
Sleep = Callable[[float], None]


def run_daemon(
    tick: Tick,
    *,
    max_ticks: int,
    interval_seconds: float,
    sleep: Sleep = time.sleep,
) -> DaemonResult:
    last_tick: TickResult | None = None
    for index in range(max_ticks):
        try:
            last_tick = tick()
        except Exception as error:
            return DaemonResult(
                status="failed",
                ticks=index,
                error_message=str(error),
            )

        if index < max_ticks - 1:
            sleep(interval_seconds)

    return DaemonResult(
        status="stopped",
        ticks=max_ticks,
        last_tick=last_tick,
    )
