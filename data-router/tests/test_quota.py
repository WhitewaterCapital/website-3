"""Quota manager: token-bucket math with an injectable clock, and priority-
queue ordering — the spec's own named case: a chaos request must never queue
behind a bulk fundamentals backfill even if the backfill was queued first."""

import pytest

from router.quota import (
    Priority,
    PriorityRequestQueue,
    QuotaExceededError,
    QuotaManager,
    TokenBucket,
)


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# --- TokenBucket ----------------------------------------------------------


def test_token_bucket_starts_full():
    clock = FakeClock()
    bucket = TokenBucket(capacity=10, refill_rate_per_sec=1.0, clock=clock)
    assert bucket.available() == 10


def test_token_bucket_consumes_and_depletes():
    clock = FakeClock()
    bucket = TokenBucket(capacity=3, refill_rate_per_sec=0.0, clock=clock)
    assert bucket.try_consume(1) is True
    assert bucket.try_consume(1) is True
    assert bucket.try_consume(1) is True
    assert bucket.try_consume(1) is False  # exhausted, no refill rate
    assert bucket.available() == 0


def test_token_bucket_refills_over_injected_time():
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, refill_rate_per_sec=1.0, clock=clock)
    for _ in range(5):
        assert bucket.try_consume(1) is True
    assert bucket.try_consume(1) is False

    clock.advance(3.0)  # 3 tokens/sec * 1 refill_rate = 3 tokens back
    assert bucket.available() == pytest.approx(3.0)
    assert bucket.try_consume(1) is True
    assert bucket.available() == pytest.approx(2.0)


def test_token_bucket_never_refills_past_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, refill_rate_per_sec=1.0, clock=clock)
    clock.advance(1000.0)
    assert bucket.available() == 5


def test_token_bucket_rejects_bad_config():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, refill_rate_per_sec=1.0)
    with pytest.raises(ValueError):
        TokenBucket(capacity=1, refill_rate_per_sec=-1.0)


# --- QuotaManager (per-minute AND per-day) ---------------------------------


def test_quota_manager_requires_both_minute_and_day_budget():
    clock = FakeClock()
    qm = QuotaManager(clock=clock)
    # 1/minute, 2/day: the minute bucket alone would allow a 2nd call after
    # 60s, but the day bucket caps total calls at 2 regardless.
    qm.configure("vendor-x", per_minute=1, per_day=2, burst_per_minute=1, burst_per_day=2)

    assert qm.try_consume("vendor-x") is True   # call 1: minute=0, day=1
    assert qm.try_consume("vendor-x") is False  # minute bucket empty
    clock.advance(60.0)                          # minute bucket refills to 1
    assert qm.try_consume("vendor-x") is True   # call 2: minute=0, day=0
    clock.advance(60.0)
    assert qm.try_consume("vendor-x") is False  # day bucket exhausted for good


def test_quota_manager_try_consume_is_atomic_across_both_buckets():
    clock = FakeClock()
    qm = QuotaManager(clock=clock)
    qm.configure("vendor-y", per_minute=5, per_day=1, burst_per_minute=5, burst_per_day=1)
    assert qm.try_consume("vendor-y") is True
    # Day bucket is now empty even though the minute bucket has plenty left;
    # a failed consume must not have partially drained the minute bucket.
    minute_before = qm.remaining("vendor-y")["per_minute"]
    assert qm.try_consume("vendor-y") is False
    assert qm.remaining("vendor-y")["per_minute"] == minute_before


def test_quota_manager_consume_or_raise():
    qm = QuotaManager()
    qm.configure("vendor-z", per_minute=1, per_day=1, burst_per_minute=1, burst_per_day=1)
    qm.consume_or_raise("vendor-z")
    with pytest.raises(QuotaExceededError):
        qm.consume_or_raise("vendor-z")


def test_quota_manager_unknown_vendor_raises_key_error():
    qm = QuotaManager()
    with pytest.raises(KeyError):
        qm.try_consume("never-configured")


# --- PriorityRequestQueue ---------------------------------------------------


def test_priority_queue_chaos_never_queues_behind_bulk_backfill():
    q = PriorityRequestQueue()
    # Bulk backfill queued FIRST, chaos request queued SECOND.
    q.push(Priority.BULK_BACKFILL, "bulk-backfill-request")
    q.push(Priority.CHAOS, "chaos-request")

    # Chaos must come out first despite arriving after the backfill.
    assert q.pop() == "chaos-request"
    assert q.pop() == "bulk-backfill-request"


def test_priority_queue_is_fifo_within_a_priority_class():
    q = PriorityRequestQueue()
    q.push(Priority.INTERACTIVE, "first")
    q.push(Priority.INTERACTIVE, "second")
    q.push(Priority.INTERACTIVE, "third")
    assert [q.pop(), q.pop(), q.pop()] == ["first", "second", "third"]


def test_priority_queue_mixed_priorities_full_ordering():
    q = PriorityRequestQueue()
    q.push(Priority.BULK_BACKFILL, "backfill-1")
    q.push(Priority.INTERACTIVE, "interactive-1")
    q.push(Priority.BULK_BACKFILL, "backfill-2")
    q.push(Priority.CHAOS, "chaos-1")
    q.push(Priority.INTERACTIVE, "interactive-2")

    order = [q.pop() for _ in range(5)]
    assert order == ["chaos-1", "interactive-1", "interactive-2", "backfill-1", "backfill-2"]


def test_priority_queue_len_and_bool():
    q = PriorityRequestQueue()
    assert len(q) == 0
    assert bool(q) is False
    q.push(Priority.CHAOS, "x")
    assert len(q) == 1
    assert bool(q) is True


def test_priority_queue_pop_from_empty_raises():
    q = PriorityRequestQueue()
    with pytest.raises(IndexError):
        q.pop()
    with pytest.raises(IndexError):
        q.peek()
