from datetime import date
from typing import Optional


class CreditLimitExceededError(Exception):
    pass


class CreditTracker:
    """Tracks discovery-provider usage (e.g. Hunter.io searches) within the current monthly period.

    This class only implements the counting rules, in memory, so they can
    be unit tested without a database. Callers (the discovery route) are
    responsible for loading/saving the used count and period_start.
    """

    def __init__(self, limit: int, used: int = 0, period_start: Optional[date] = None):
        self.limit = limit
        self.used = used
        self.period_start = period_start or date.today()

    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    def can_spend(self, amount: int) -> bool:
        return self.remaining() >= amount

    def spend(self, amount: int) -> None:
        if not self.can_spend(amount):
            raise CreditLimitExceededError(
                f"Requested {amount} credits but only {self.remaining()} remain "
                f"out of {self.limit} this period."
            )
        self.used += amount

    def reset_if_new_period(self, today: date, period_length_days: int = 30) -> None:
        if (today - self.period_start).days >= period_length_days:
            self.used = 0
            self.period_start = today
