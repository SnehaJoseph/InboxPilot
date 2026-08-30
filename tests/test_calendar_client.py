from unittest.mock import MagicMock, patch

from inboxpilot.calendar_client import CalendarClient


def test_calendar_event_is_converted_to_google_payload():
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {"id": "event-1"}

    with patch.object(CalendarClient, "_service", return_value=service):
        result = CalendarClient().create_event(
            {
                "summary": "Meeting",
                "start": "2026-08-31T14:00:00+05:30",
                "end": "2026-08-31T15:00:00+05:30",
                "timezone": "Asia/Kolkata",
                "description": "InboxPilot proposal",
            }
        )

    assert result == {"id": "event-1"}
    body = service.events.return_value.insert.call_args.kwargs["body"]
    assert body["start"] == {"dateTime": "2026-08-31T14:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert body["end"]["dateTime"] == "2026-08-31T15:00:00+05:30"
    assert body["description"] == "InboxPilot proposal"


def test_calendar_client_supports_list_free_busy_update_and_delete():
    service = MagicMock()
    service.calendarList.return_value.list.return_value.execute.return_value = {"items": [{"id": "primary"}]}
    service.events.return_value.list.return_value.execute.return_value = {"items": [{"id": "event-1"}]}
    service.freebusy.return_value.query.return_value.execute.return_value = {"calendars": {"primary": {"busy": []}}}
    service.events.return_value.update.return_value.execute.return_value = {"id": "event-1"}

    with patch.object(CalendarClient, "_service", return_value=service):
        client = CalendarClient()
        assert client.list_calendars() == [{"id": "primary"}]
        assert client.list_events(__import__("datetime").datetime(2026, 8, 31), __import__("datetime").datetime(2026, 9, 1)) == [{"id": "event-1"}]
        assert client.get_free_busy(__import__("datetime").datetime(2026, 8, 31), __import__("datetime").datetime(2026, 9, 1)) == {"busy": []}
        assert client.update_event("event-1", {"summary": "Updated", "start": "2026-08-31T14:00:00+00:00", "end": "2026-08-31T15:00:00+00:00"}) == {"id": "event-1"}
        client.delete_event("event-1")

    service.events.return_value.delete.assert_called_once_with(calendarId="primary", eventId="event-1")
