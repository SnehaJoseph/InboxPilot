from unittest.mock import MagicMock, patch
from email import policy
from email.parser import BytesParser
import base64

from inboxpilot.gmail_client import GmailClient


def test_list_recent_messages_uses_primary_query_and_pagination():
    credentials = MagicMock()
    first_page = {"messages": [{"id": "one"}], "nextPageToken": "next"}
    second_page = {"messages": [{"id": "two"}]}

    service = MagicMock()
    list_request = service.users.return_value.messages.return_value.list
    list_request.side_effect = [
        MagicMock(execute=MagicMock(return_value=first_page)),
        MagicMock(execute=MagicMock(return_value=second_page)),
    ]
    service.users.return_value.messages.return_value.get.side_effect = [
        MagicMock(execute=MagicMock(return_value={"id": "one", "payload": {}})),
        MagicMock(execute=MagicMock(return_value={"id": "two", "payload": {}})),
    ]

    with patch("inboxpilot.gmail_client.GmailClient._credentials", return_value=credentials):
        with patch("inboxpilot.gmail_client.build", return_value=service):
            messages = GmailClient().list_recent_messages(
                "user@example.com", minutes_since=1_440, include_read=True, max_messages=2
            )

    assert len(messages) == 2
    first_call = list_request.call_args_list[0]
    assert "category:primary" in first_call.kwargs["q"]
    assert "after:" in first_call.kwargs["q"]
    assert "is:unread" not in first_call.kwargs["q"]
    assert first_call.kwargs["maxResults"] == 2
    assert first_call.kwargs["pageToken"] is None
    assert list_request.call_args_list[1].kwargs["pageToken"] == "next"


def test_send_reply_builds_gmail_message():
    credentials = MagicMock()
    service = MagicMock()
    send_request = service.users.return_value.messages.return_value.send
    send_request.return_value.execute.return_value = {"id": "sent"}

    with patch("inboxpilot.gmail_client.GmailClient._credentials", return_value=credentials):
        with patch("inboxpilot.gmail_client.build", return_value=service):
            result = GmailClient().send_reply(
                {"from": "friend@example.com", "subject": "Hello", "thread_id": "thread-1"},
                "Thanks for writing.",
            )

    assert result == {"id": "sent"}
    body = send_request.call_args.kwargs["body"]
    assert body["threadId"] == "thread-1"
    sent_message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(body["raw"]))
    assert sent_message["Subject"] == "Re: Hello"
    assert sent_message.get_content() == "Thanks for writing.\n"