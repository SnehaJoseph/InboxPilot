from __future__ import annotations

from typing import Any


class ReviewCenter:
    """CLI human-review adapter for paused LangGraph actions."""

    @staticmethod
    def prompt(review: dict[str, Any]) -> dict[str, str]:
        email = review.get("email", {})
        print(f"\n[{review['review_center']}]")
        print(f"From: {email.get('from', 'Unknown')}")
        print(f"Subject: {email.get('subject', 'No Subject')}")
        print(f"Agent intent: {review.get('intent', 'unknown')}")
        print(f"Agent reasoning: {review.get('reasoning', 'Not provided')}")
        print(f"Question: {review['question']}")
        if review.get("draft_reply"):
            print("Draft reply:")
            print(review["draft_reply"])
        if review.get("proposed_action"):
            print(f"Proposed action: {review['proposed_action']}")

        while True:
            choice = input("Enter approve or reject: ").strip().lower()
            if choice in {"approve", "reject"}:
                return {"decision": choice}
            print("Please enter approve or reject.")