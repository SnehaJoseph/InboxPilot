from __future__ import annotations

import base64
import json
import os
from email.message import EmailMessage
from typing import Any

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build


GMAIL_HTTP_TIMEOUT_SECONDS = 30


class GmailClient:
    """Minimal Gmail client wrapper for email ingestion."""

    def __init__(self, token_json: str | None = None, secret_json: str | None = None):
        self.token_json = token_json or os.getenv("GMAIL_TOKEN")
        self.secret_json = secret_json or os.getenv("GMAIL_SECRET")

    def _credentials(self) -> Credentials | None:
        token_data = None
        if self.token_json:
            try:
                token_data = json.loads(self.token_json)
            except json.JSONDecodeError:
                token_data = None

        if token_data is None:
            token_path = os.getenv("GMAIL_TOKEN_PATH")
            if token_path and os.path.exists(token_path):
                with open(token_path, "r", encoding="utf-8") as fh:
                    token_data = json.load(fh)

        if token_data is None:
            return None

        return Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes", ["https://www.googleapis.com/auth/gmail.modify"]),
        )

    def list_recent_messages(
        self,
        email_address: str,
        minutes_since: int = 120,
        include_read: bool = False,
        latest_only: bool = False,
        max_messages: int | None = None,
    ) -> list[dict[str, Any]]:
        credentials = self._credentials()
        if credentials is None:
            raise RuntimeError("Gmail credentials are not configured. Set GMAIL_TOKEN or GMAIL_TOKEN_PATH.")

        http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=GMAIL_HTTP_TIMEOUT_SECONDS))
        service = build("gmail", "v1", http=http, cache_discovery=False)
        query = f"(to:{email_address} OR from:{email_address}) category:primary"
        if minutes_since > 0:
            from datetime import datetime, timedelta

            cutoff = int((datetime.now() - timedelta(minutes=minutes_since)).timestamp())
            query += f" after:{cutoff}"
        if not include_read:
            query += " is:unread"

        message_ids: list[dict[str, str]] = []
        page_token = None
        while True:
            request_args: dict[str, Any] = {"userId": "me", "q": query, "pageToken": page_token}
            result_limit = 1 if latest_only else max_messages
            if result_limit is not None:
                request_args["maxResults"] = min(result_limit, 100)
            request = service.users().messages().list(**request_args)
            result = request.execute()
            message_ids.extend(result.get("messages", []))
            if latest_only or (max_messages is not None and len(message_ids) >= max_messages):
                break
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        messages: list[dict[str, Any]] = []
        for item in message_ids:
            msg = service.users().messages().get(userId="me", id=item["id"]).execute()
            messages.append(self._message_to_payload(msg))
            if max_messages is not None and len(messages) >= max_messages:
                break
        return messages

    @staticmethod
    def _message_to_payload(message: dict[str, Any]) -> dict[str, Any]:
        headers = message.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown Sender")
        recipient = next((h["value"] for h in headers if h["name"].lower() == "to"), "Unknown Recipient")

        body = GmailClient._extract_body(message.get("payload", {}))
        return {
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "from": sender,
            "to": recipient,
            "subject": subject,
            "body": body,
            "body_html": body,
        }

    def send_reply(self, email: dict[str, Any], body: str) -> dict[str, Any]:
        credentials = self._credentials()
        if credentials is None:
            raise RuntimeError("Gmail credentials are not configured. Set GMAIL_TOKEN or GMAIL_TOKEN_PATH.")

        message = EmailMessage()
        message["To"] = email["from"]
        message["Subject"] = email["subject"] if email["subject"].lower().startswith("re:") else f"Re: {email['subject']}"
        body_lines = body.strip().splitlines()
        if body_lines and body_lines[0].strip().lower().startswith("subject:"):
            body = "\n".join(body_lines[1:]).lstrip()
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=GMAIL_HTTP_TIMEOUT_SECONDS))
        service = build("gmail", "v1", http=http, cache_discovery=False)
        return service.users().messages().send(
            userId="me", body={"raw": raw, "threadId": email.get("thread_id")}
        ).execute()

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        if payload.get("parts"):
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
            for part in payload["parts"]:
                if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                    return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
        if payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        return ""
