"""Calendar dates at public API boundaries."""

from datetime import date, datetime


def as_date(value: date | str) -> date:
    """Accept dates and ISO dates, rejecting times and timezone conversions."""
    if isinstance(value, datetime):
        raise ValueError("Use a calendar date, not a timestamp.")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if value != parsed.isoformat():
                raise ValueError
            return parsed
        except ValueError as exc:
            raise ValueError(f"Expected an ISO calendar date: {value!r}") from exc
    raise ValueError(f"Expected a calendar date: {value!r}")
