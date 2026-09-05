from datetime import date

from app.business_days import business_days_from


def test_zero_business_days_returns_start_unchanged():
    # Wednesday, arbitrary day - no weekend involved.
    assert business_days_from(date(2024, 1, 3), 0) == date(2024, 1, 3)


def test_business_days_with_no_weekend_in_window():
    # Monday 2024-01-01 + 3 business days, all within the same working week.
    assert business_days_from(date(2024, 1, 1), 3) == date(2024, 1, 4)


def test_business_days_starting_on_friday_skips_weekend():
    # Friday 2024-01-05 + 1 business day -> Monday 2024-01-08.
    assert business_days_from(date(2024, 1, 5), 1) == date(2024, 1, 8)


def test_business_days_spans_one_weekend():
    # Monday 2024-01-01 + 6 business days -> Tuesday 2024-01-09
    # (Tue Wed Thu Fri, skip Sat/Sun, Mon Tue).
    assert business_days_from(date(2024, 1, 1), 6) == date(2024, 1, 9)


def test_business_days_spans_two_weekends():
    # Monday 2024-01-01 + 10 business days -> Monday 2024-01-15.
    assert business_days_from(date(2024, 1, 1), 10) == date(2024, 1, 15)
