from __future__ import annotations

import argparse

from inboxpilot.config import load_settings
from inboxpilot.agent import InboxPilotAgent


def _print_result(index: int, result: dict) -> None:
    email = result.get("email", {})
    print(f"\n--- Email {index} ---")
    print(f"From: {email.get('from', 'Unknown')}")
    print(f"To: {email.get('to', 'Unknown')}")
    print(f"Subject: {email.get('subject', 'No Subject')}")
    print(f"Intent: {result.get('intent', 'unknown').upper()}")
    print(f"Reasoning: {result.get('reasoning', 'Not provided')}")
    if result.get("review_question"):
        print(f"Human review needed: {result['review_question']}")
    if result.get("draft_reply"):
        print("Draft reply:")
        print(result["draft_reply"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InboxPilot email processing")
    parser.add_argument("--email", type=str, help="Override the Gmail address from GMAIL_EMAIL")
    parser.add_argument("--minutes-since", type=int, default=2_880, help="Time window in minutes (default: 2 days)")
    parser.add_argument("--include-read", action="store_true", default=True, help="Include already-read messages (default: all emails)")
    parser.add_argument("--latest-only", action="store_true", help="Process only the newest matching email")
    args = parser.parse_args()

    settings = load_settings()
    email_address = args.email or settings.gmail_email
    if not email_address:
        parser.error("Set GMAIL_EMAIL in .env or provide --email")
    agent = InboxPilotAgent(settings)
    results = agent.process_inbox(
        email_address,
        minutes_since=args.minutes_since,
        include_read=args.include_read,
        latest_only=args.latest_only,
        interactive=True,
    )

    print(f"Processed {len(results)} email(s).")
    for index, result in enumerate(results, start=1):
        _print_result(index, result)


if __name__ == "__main__":
    main()
