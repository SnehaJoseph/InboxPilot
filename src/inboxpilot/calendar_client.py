from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build


CALENDAR_HTTP_TIMEOUT_SECONDS = 30


class CalendarClient:
    """Google Calendar API wrapper for availability and approved event actions."""

    def __init__(self, calendar_id: str | None = None):
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")

    def _service(self) -> Any:
        token_path = os.getenv("GMAIL_TOKEN_PATH")
        if not token_path or not os.path.exists(token_path):
            raise RuntimeError("Google OAuth token is not configured. Set GMAIL_TOKEN_PATH.")
        with open(token_path, "r", encoding="utf-8") as fh:
            token_data = json.load(fh)
        credentials = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/calendar.events"]),
        )
        http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=CALENDAR_HTTP_TIMEOUT_SECONDS))
        return build("calendar", "v3", http=http, cache_discovery=False)

    def list_calendars(self) -> list[dict[str, Any]]:
        result = self._service().calendarList().list().execute()
        return result.get("items", [])

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        result = self._service().events().list(
            calendarId=self.calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return result.get("items", [])

    def get_free_busy(self, time_min: datetime, time_max: datetime) -> dict[str, Any]:
        result = self._service().freebusy().query(
            body={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "items": [{"id": self.calendar_id}],
            }
        ).execute()
        return result.get("calendars", {}).get(self.calendar_id, {})

    def create_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._service().events().insert(calendarId=self.calendar_id, body=self._google_event(event)).execute()

    def update_event(self, event_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return self._service().events().update(calendarId=self.calendar_id, eventId=event_id, body=self._google_event(event)).execute()

    def delete_event(self, event_id: str) -> None:
        self._service().events().delete(calendarId=self.calendar_id, eventId=event_id).execute()

    @staticmethod
    def _google_event(event: dict[str, Any]) -> dict[str, Any]:
        result = {
            "summary": event["summary"],
            "start": {"dateTime": event["start"], "timeZone": event.get("timezone", "UTC")},
            "end": {"dateTime": event["end"], "timeZone": event.get("timezone", "UTC")},
        }
        if event.get("description"):
            result["description"] = event["description"]
        return result