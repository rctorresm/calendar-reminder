from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CalendarInfo:
    calendar_id: str
    name: str
    access_role: str  # freeBusyReader | reader | writer | owner
    primary: bool

    @property
    def full_details_available(self) -> bool:
        return self.access_role != "freeBusyReader"


@dataclass(frozen=True)
class EventOccurrence:
    event_id: str
    calendar_id: str
    title: str
    start: datetime  # timezone-aware, UTC
    end: datetime | None
    location: str | None
    is_all_day: bool
    status: str
    html_link: str | None
    updated_at: datetime

    def to_row(self) -> dict:
        return {
            "event_id": self.event_id,
            "calendar_id": self.calendar_id,
            "title": self.title,
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat() if self.end else None,
            "location": self.location,
            "is_all_day": int(self.is_all_day),
            "status": self.status,
            "html_link": self.html_link,
            "updated_at": self.updated_at.isoformat(),
        }
