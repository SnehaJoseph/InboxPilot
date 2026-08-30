from __future__ import annotations

import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
]

CLIENT_SECRET_PATH = Path(os.getenv("GMAIL_SECRET_PATH", r"D:\Secrets\InboxPilot\client_secret.json"))
TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", r"D:\Secrets\InboxPilot\token.json"))


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"Google client secret not found at {CLIENT_SECRET_PATH}. "
            "Download it from Google Cloud Console and save it outside the repo."
        )

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CLIENT_SECRET_PATH.open("r", encoding="utf-8") as fh:
        client_config = json.load(fh)

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    with TOKEN_PATH.open("w", encoding="utf-8") as fh:
        fh.write(creds.to_json())

    print(f"Saved Gmail token to: {TOKEN_PATH}")


if __name__ == "__main__":
    main()
