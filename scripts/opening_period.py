"""Year/month a Personal Expenses dashboard would open on.

The reference instant is yesterday's calendar date in America/El_Salvador
(UTC-6, no daylight-saving time). That is the same rule as: on the 1st,
the previous month (January 1 rolls to December of the previous year); from
the 2nd onward, the current month.

This module does not touch a dashboard. Visible Year/Month controls and a
SQL WHERE are separate and are both left unset. See
``patch_opening_period.py`` for the Lakeview documentation limit.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SV = ZoneInfo("America/El_Salvador")
UTC = timezone.utc


def opening_period(now):
    """Return ``(year, month)`` for an aware datetime.

    ``now`` is converted to America/El_Salvador before the calendar day is
    read. Subtracting a day from the UTC date is not the same thing near
    local midnight.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    yesterday = now.astimezone(SV).date() - timedelta(days=1)
    return yesterday.year, yesterday.month


def visible_filter_default(now):
    """Value the Year and Month dropdowns can show on open.

    Lakeview single-value field filters only store a literal default chosen
    from the dropdown. That is not a dynamic expression, so the supported
    visible default is no selection (All). Callers must not treat the period
    tuple as this value.
    """
    del now
    return None


def sql_effective_default(now):
    """Year/month a dataset WHERE would apply on open.

    No such predicate is added. History stays queryable. This is deliberately
    not ``opening_period``: a SQL default would hide rows even when the
    visible controls still say All.
    """
    del now
    return None
