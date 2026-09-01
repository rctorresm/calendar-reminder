"""Thin wrapper around the read-only Google Calendar API surface this app
uses. Never call any write/insert/update/delete endpoint from this module —
the OAuth scope wouldn't allow it anyway, but keep it enforced in code too."""

from __future__ import annotations

import logging

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from calendar_app.models import CalendarInfo

logger = logging.getLogger(__name__)

READABLE_ROLES = {"freeBusyReader", "reader", "writer", "owner"}


def build_service(credentials: Credentials) -> Resource:
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def list_calendars(service: Resource) -> list[CalendarInfo]:
    calendars: list[CalendarInfo] = []
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        for item in response.get("items", []):
            role = item.get("accessRole", "")
            if role not in READABLE_ROLES:
                continue
            calendars.append(
                CalendarInfo(
                    calendar_id=item["id"],
                    name=item.get("summaryOverride") or item.get("summary", item["id"]),
                    access_role=role,
                    primary=item.get("primary", False),
                )
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return calendars


def find_account_email(calendars: list[CalendarInfo]) -> str | None:
    """The signed-in account's own primary calendar ID IS its email
    address — a reliable way to know which Google account this data
    belongs to without requesting any extra scope (e.g. userinfo.email)
    just to find out."""
    for cal in calendars:
        if cal.primary:
            return cal.calendar_id
    return None
