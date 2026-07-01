"""Business hours calculation for SLA metrics.

All functions work with timezone-naive datetimes assumed to be in
the portal's local timezone.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Set


# Config weekday encoding: 0=Sunday, 1=Monday, ..., 6=Saturday.
# Python weekday(): 0=Monday, 1=Tuesday, ..., 6=Sunday.
_CONFIG_TO_PYTHON_WEEKDAY = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
_PYTHON_TO_CONFIG_WEEKDAY = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}


@dataclass
class WorkingHours:
    work_start: time
    work_end: time
    workdays: Set[int] = field(default_factory=lambda: {1, 2, 3, 4, 5})
    holidays: Set[date] = field(default_factory=set)

    @property
    def py_workdays(self) -> Set[int]:
        """Return workdays as Python weekday numbers (0=Mon, 6=Sun)."""
        return {_CONFIG_TO_PYTHON_WEEKDAY[d] for d in self.workdays}


def is_workday(d: date, wh: WorkingHours) -> bool:
    """Check if a date is a workday (in workdays set and not a holiday)."""
    return d.weekday() in wh.py_workdays and d not in wh.holidays


def business_seconds(start: datetime, end: datetime, wh: WorkingHours) -> int:
    """Return seconds of business time between start and end datetimes.

    Iterates each day in the range, clips to working hours, and sums.
    Weekends and holidays are excluded.
    If end <= start, returns 0.
    """
    if end <= start:
        return 0

    total = 0.0
    current_date = start.date()
    end_date = end.date()

    while current_date <= end_date:
        if is_workday(current_date, wh):
            day_start_dt = datetime.combine(current_date, wh.work_start)
            day_end_dt = datetime.combine(current_date, wh.work_end)

            segment_start = max(start, day_start_dt)
            segment_end = min(end, day_end_dt)

            if segment_end > segment_start:
                total += (segment_end - segment_start).total_seconds()

        current_date += timedelta(days=1)

    return int(total)


def business_minutes(start: datetime, end: datetime, wh: WorkingHours) -> int:
    """Return whole minutes of business time."""
    return business_seconds(start, end, wh) // 60


def format_duration(seconds: int) -> str:
    """Format seconds as Russian human-readable duration like '2ч 15м'."""
    if seconds <= 0:
        return "0м"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"
