"""Circuit breaker full lifecycle, with an injectable clock so nothing here
ever sleeps: healthy -> tripped -> cooldown -> half-open probe -> recovered,
plus the "probe fails -> back to OPEN" branch."""

import pytest

from router.circuit import CircuitBreaker, CircuitState


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _breaker(clock, on_event=None) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=3,
        window_seconds=60.0,
        cooldown_seconds=30.0,
        clock=clock,
        on_event=on_event,
    )


def test_starts_closed_and_allows_requests():
    clock = FakeClock()
    cb = _breaker(clock)
    assert cb.state is CircuitState.CLOSED
    assert cb.allow_request() is True


def test_trips_open_after_threshold_failures_within_window():
    clock = FakeClock()
    cb = _breaker(clock)
    cb.record_failure()
    cb.record_failure()
    assert cb.state is CircuitState.CLOSED  # only 2 of 3
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False


def test_failures_outside_the_window_do_not_count():
    clock = FakeClock()
    cb = _breaker(clock)
    cb.record_failure()
    clock.advance(61.0)  # outside the 60s window
    cb.record_failure()
    cb.record_failure()
    # only 2 failures within the trailing window -> still closed
    assert cb.state is CircuitState.CLOSED


def test_cooldown_then_half_open_probe_allowed():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert cb.allow_request() is False

    clock.advance(29.9)
    assert cb.state is CircuitState.OPEN  # cooldown not elapsed yet
    assert cb.allow_request() is False

    clock.advance(0.2)  # now >= 30s cooldown total
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow_request() is True  # the single probe is allowed


def test_successful_probe_recovers_to_closed():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        cb.record_failure()
    clock.advance(30.0)
    assert cb.state is CircuitState.HALF_OPEN

    cb.record_success()
    assert cb.state is CircuitState.CLOSED
    assert cb.allow_request() is True

    # Recovery clears the failure history: a single new failure should not
    # immediately re-trip a freshly-recovered breaker.
    cb.record_failure()
    assert cb.state is CircuitState.CLOSED


def test_failed_probe_reopens_and_restarts_cooldown():
    clock = FakeClock()
    cb = _breaker(clock)
    for _ in range(3):
        cb.record_failure()
    clock.advance(30.0)
    assert cb.state is CircuitState.HALF_OPEN

    cb.record_failure(rate_limited=True)  # the probe itself fails
    assert cb.state is CircuitState.OPEN

    clock.advance(29.0)
    assert cb.state is CircuitState.OPEN  # fresh cooldown, not yet elapsed
    clock.advance(1.0)
    assert cb.state is CircuitState.HALF_OPEN  # new cooldown window elapsed


def test_events_are_recorded_in_order_and_callback_invoked():
    events_seen = []
    clock = FakeClock()
    cb = _breaker(clock, on_event=lambda e: events_seen.append(e.name))

    for _ in range(3):
        cb.record_failure()
    clock.advance(30.0)
    cb.state  # trigger the settle() that emits half_open
    cb.record_success()

    names = [e.name for e in cb.events]
    assert names == ["tripped", "half_open", "recovered"]
    assert events_seen == names  # callback fired for every event


def test_failure_threshold_must_be_at_least_one():
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0, window_seconds=1, cooldown_seconds=1)


def test_rate_limited_failure_still_counts_toward_threshold():
    clock = FakeClock()
    cb = _breaker(clock)
    cb.record_failure(rate_limited=True)
    cb.record_failure(rate_limited=True)
    cb.record_failure(rate_limited=True)
    assert cb.state is CircuitState.OPEN
    assert cb.events[-1].detail.get("rate_limited") is True
