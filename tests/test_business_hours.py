"""Tests for business hours calculation."""

from datetime import datetime, date, time

from sla.business_hours import WorkingHours, business_seconds, format_duration, is_workday


# Standard Mon-Fri 9:00-18:00 working hours
WH = WorkingHours(
    work_start=time(9, 0),
    work_end=time(18, 0),
    workdays={1, 2, 3, 4, 5},  # Mon-Fri (config: 0=Sun, 1=Mon)
    holidays=set(),
)

# Monday 2024-01-15
MON = datetime(2024, 1, 15, 10, 0)
MON_LATE = datetime(2024, 1, 15, 16, 0)

# Tuesday 2024-01-16
TUE_EARLY = datetime(2024, 1, 16, 10, 0)

# Saturday 2024-01-13 (weekend)
SAT = datetime(2024, 1, 13, 10, 0)

# Sunday 2024-01-14 (weekend)
SUN = datetime(2024, 1, 14, 10, 0)


def test_same_day_within_window():
    """Start and end on same workday within working hours."""
    result = business_seconds(MON, datetime(2024, 1, 15, 14, 0), WH)
    assert result == 4 * 3600  # 10:00 -> 14:00 = 4 hours


def test_weekend_no_time():
    """Start and end on Saturday — no business time."""
    result = business_seconds(SAT, datetime(2024, 1, 13, 14, 0), WH)
    assert result == 0


def test_multi_day_business():
    """Span Monday late afternoon to Tuesday morning."""
    # Monday 16:00-18:00 = 2h, Tuesday 9:00-10:00 = 1h => 3h
    result = business_seconds(
        MON_LATE,
        TUE_EARLY,
        WH,
    )
    assert result == 3 * 3600


def test_holiday_excluded():
    """A date in the holidays set should be skipped."""
    wh_with_holiday = WorkingHours(
        work_start=time(9, 0),
        work_end=time(18, 0),
        workdays={1, 2, 3, 4, 5},
        holidays={date(2024, 1, 15)},  # Monday is a holiday
    )
    result = business_seconds(MON, datetime(2024, 1, 15, 14, 0), wh_with_holiday)
    assert result == 0


def test_clip_before_work_start():
    """Start before working hours should clip to work_start."""
    start = datetime(2024, 1, 15, 6, 0)  # Monday 06:00
    end = datetime(2024, 1, 15, 11, 0)
    result = business_seconds(start, end, WH)
    assert result == 2 * 3600  # 09:00-11:00 = 2h


def test_clip_after_work_end():
    """End after working hours should clip to work_end."""
    start = datetime(2024, 1, 15, 16, 0)
    end = datetime(2024, 1, 15, 20, 0)
    result = business_seconds(start, end, WH)
    assert result == 2 * 3600  # 16:00-18:00 = 2h


def test_end_before_start_returns_zero():
    """When end <= start, result should be 0."""
    result = business_seconds(
        datetime(2024, 1, 15, 14, 0),
        datetime(2024, 1, 15, 10, 0),
        WH,
    )
    assert result == 0


def test_span_weekend():
    """Spanning a weekend should exclude Saturday and Sunday."""
    # Friday 2024-01-12 16:00 to Monday 2024-01-15 10:00
    fri = datetime(2024, 1, 12, 16, 0)
    mon = MON
    # Friday: 16:00-18:00 = 2h
    # Sat: 0
    # Sun: 0
    # Mon: 9:00-10:00 = 1h
    # Total: 3h
    result = business_seconds(fri, mon, WH)
    assert result == 3 * 3600


def test_exact_work_hours():
    """Start exactly at 9:00 and end exactly at 18:00 on same day."""
    start = datetime(2024, 1, 15, 9, 0)
    end = datetime(2024, 1, 15, 18, 0)
    result = business_seconds(start, end, WH)
    assert result == 9 * 3600


def test_format_duration():
    """Test format_duration helper."""
    assert format_duration(0) == "0м"
    assert format_duration(30) == "0м"
    assert format_duration(120) == "2м"
    assert format_duration(3600) == "1ч 0м"
    assert format_duration(3660) == "1ч 1м"
    assert format_duration(7500) == "2ч 5м"


def test_is_workday():
    """Test workday detection."""
    assert is_workday(date(2024, 1, 15), WH) is True   # Monday
    assert is_workday(date(2024, 1, 13), WH) is False  # Saturday
    assert is_workday(date(2024, 1, 14), WH) is False  # Sunday


def test_holiday_detection_via_is_workday():
    """Test that holidays are excluded by is_workday."""
    wh = WorkingHours(
        work_start=time(9, 0),
        work_end=time(18, 0),
        workdays={1, 2, 3, 4, 5},
        holidays={date(2024, 1, 15)},
    )
    assert is_workday(date(2024, 1, 15), wh) is False
