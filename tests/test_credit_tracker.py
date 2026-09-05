from datetime import date, timedelta

import pytest

from app.credit_tracker import CreditLimitExceededError, CreditTracker


def test_remaining_starts_at_full_limit():
    tracker = CreditTracker(limit=60)
    assert tracker.remaining() == 60


def test_spend_reduces_remaining():
    tracker = CreditTracker(limit=60)
    tracker.spend(25)
    assert tracker.remaining() == 35
    assert tracker.used == 25


def test_spend_raises_when_exceeding_limit():
    tracker = CreditTracker(limit=10, used=8)
    with pytest.raises(CreditLimitExceededError):
        tracker.spend(5)
    assert tracker.used == 8


def test_can_spend_returns_false_when_insufficient():
    tracker = CreditTracker(limit=10, used=10)
    assert tracker.can_spend(1) is False


def test_reset_if_new_period_resets_after_30_days():
    start = date(2026, 1, 1)
    tracker = CreditTracker(limit=60, used=60, period_start=start)

    tracker.reset_if_new_period(today=start + timedelta(days=30))

    assert tracker.used == 0
    assert tracker.period_start == start + timedelta(days=30)


def test_reset_if_new_period_keeps_usage_within_period():
    start = date(2026, 1, 1)
    tracker = CreditTracker(limit=60, used=20, period_start=start)

    tracker.reset_if_new_period(today=start + timedelta(days=10))

    assert tracker.used == 20
    assert tracker.period_start == start
