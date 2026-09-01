"""Fetch and normalize events for a single calendar.

Parsing is split from the network call (`parse_event` vs `fetch_events`) so
the tricky bits — timezones, all-day events, cancellations, recurrence
expansion — can be unit tested without hitting the real API.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

from calendar_app.models import EventOccurrence

logger = logging.getLogger(__name__)


def _parse_rfc3339(value: str) -> datetime:
    """Parse an RFC3339 timestamp (Google always includes an offset or 'Z')
    into a timezone-aware UTC datetime. Never returns a naive datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        # Should not happen for Google API responses, but never fall back
        # to a naive/ambiguous local-time interpretation.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_event(item: dict[str, Any], calendar_id: str) -> EventOccurrence | None:
    status = item.get("status", "confirmed")
    if status == "cancelled":
        return None

    start_field = item.get("start", {})
    end_field = item.get("end", {})

    is_all_day = "date" in start_field and "dateTime" not in start_field
    if is_all_day:
        start_date = date.fromisoformat(start_field["date"])
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end = None
        if "date" in end_field:
            end_date = date.fromisoformat(end_field["date"])
            end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
    else:
        if "dateTime" not in start_field:
            logger.warning("Event %s has neither date nor dateTime; skipping.", item.get("id"))
            return None
        start = _parse_rfc3339(start_field["dateTime"])
        end = _parse_rfc3339(end_field["dateTime"]) if "dateTime" in end_field else None

    updated_raw = item.get("updated")
    updated_at = _parse_rfc3339(updated_raw) if updated_raw else datetime.now(timezone.utc)

    return EventOccurrence(
        event_id=item["id"],
        calendar_id=calendar_id,
        title=item.get("summary") or "(No title)",
        start=start,
        end=end,
        location=item.get("location"),
        is_all_day=is_all_day,
        status=status,
        html_link=item.get("htmlLink"),
        updated_at=updated_at,
    )


def fetch_events(
    service: Resource,
    calendar_id: str,
    time_min: datetime,
    time_max: datetime,
) -> list[EventOccurrence]:
    """Fetch events in [time_min, time_max) for one calendar.

    Uses singleEvents=True so recurring entries are expanded into
    individual occurrences, each with its own start time.
    """
    occurrences: list[EventOccurrence] = []
    page_token = None
    try:
        while True:
            response = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min.astimezone(timezone.utc).isoformat(),
                    timeMax=time_max.astimezone(timezone.utc).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute()
            )
            for item in response.get("items", []):
                occurrence = parse_event(item, calendar_id)
                if occurrence is not None:
                    occurrences.append(occurrence)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        if exc.resp.status in (403, 404):
            logger.warning(
                "No longer able to read events for calendar %s (status %s). "
                "Access may have been revoked.",
                calendar_id,
                exc.resp.status,
            )
            return []
        raise
    return occurrences
