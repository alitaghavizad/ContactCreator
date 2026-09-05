from datetime import date, timedelta


def business_days_from(start: date, business_days: int) -> date:
    """Return the date `business_days` weekdays (Mon-Fri) after `start`.

    Weekends are skipped when counting forward. `start` itself is never
    counted toward the total, and `business_days=0` returns `start`
    unchanged.
    """
    current = start
    counted = 0
    while counted < business_days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 ... Sunday=6
            counted += 1
    return current
