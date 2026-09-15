# Copyright (c) Microsoft. All rights reserved.
"""Example tools exposed to the agent.

Tools are plain Python functions annotated with the Microsoft Agent Framework
``@tool`` decorator. Type hints and docstrings are used to generate the JSON
schema advertised to the model, so keep them accurate.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Annotated

from agent_framework import tool

_WEEKEND = {5, 6}


@tool
def get_current_time(
    time_zone: Annotated[str, "IANA time zone name, for example 'UTC' or 'America/New_York'."] = "UTC",
) -> str:
    """Return the current date and time in ISO 8601 format for the given time zone."""
    try:
        tz = zoneinfo.ZoneInfo(time_zone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown time zone '{time_zone}'. Use an IANA time zone name such as 'UTC'.") from exc
    return datetime.now(tz).isoformat()


@tool
def count_business_days(
    start_date: Annotated[str, "Inclusive start date in YYYY-MM-DD format."],
    end_date: Annotated[str, "Inclusive end date in YYYY-MM-DD format."],
) -> int:
    """Count the number of business days (Monday to Friday) between two dates, inclusive."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Dates must be provided in YYYY-MM-DD format.") from exc

    if end < start:
        raise ValueError("end_date must be on or after start_date.")

    days = 0
    current = start
    while current <= end:
        if current.weekday() not in _WEEKEND:
            days += 1
        current += timedelta(days=1)
    return days


#: Tools registered with the agent. Add new tools here to extend the agent.
AGENT_TOOLS = [get_current_time, count_business_days]
