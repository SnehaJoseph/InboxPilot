from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from inboxpilot.agent import InboxPilotAgent
from inboxpilot.config import load_settings
from inboxpilot.gmail_client import GmailClient
from inboxpilot.calendar_client import CalendarClient


app = FastAPI(title="InboxPilot Review Center")
STATIC_DIR = Path(__file__).with_name("static")
_agent: InboxPilotAgent | None = None


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject", "revise"]
    edited_reply: str | None = None
    feedback: str | None = None


class CalendarEventRequest(BaseModel):
    summary: str
    start: datetime
    end: datetime
    timezone: str = "UTC"
    description: str | None = None


def get_agent() -> InboxPilotAgent:
    global _agent
    if _agent is None:
        _agent = InboxPilotAgent(load_settings())
    return _agent


def serialize_result(result: dict[str, Any]) -> dict[str, Any]:
    interruptions = result.get("__interrupt__")
    email = result.get("email", {})
    if interruptions:
        review = interruptions[0].value
        return {
            "status": "pending",
            "review_id": email.get("id"),
            "email": review.get("email", email),
            "intent": review.get("intent", result.get("intent")),
            "reasoning": review.get("reasoning", result.get("reasoning")),
            "question": review.get("question"),
            "draft_reply": review.get("draft_reply"),
            "proposed_action": review.get("proposed_action"),
            "calendar_event": review.get("calendar_event"),
        }

    return {
        "status": "complete",
        "review_id": email.get("id"),
        "email": email,
        "intent": result.get("intent"),
        "reasoning": result.get("reasoning"),
        "final_reply": result.get("final_reply"),
        "review_status": result.get("review_status"),
        "calendar_event": result.get("calendar_event"),
    }


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/config")
def config() -> dict[str, str | None]:
    return {"email": load_settings().gmail_email}


@app.get("/api/calendar/events")
def calendar_events(time_min: datetime, time_max: datetime) -> dict[str, Any]:
    return {"events": CalendarClient(load_settings().google_calendar_id).list_events(time_min, time_max)}


@app.get("/api/calendar/free-busy")
def calendar_free_busy(time_min: datetime, time_max: datetime) -> dict[str, Any]:
    return CalendarClient(load_settings().google_calendar_id).get_free_busy(time_min, time_max)


@app.post("/api/calendar/events")
def create_calendar_event(event: CalendarEventRequest) -> dict[str, Any]:
    return CalendarClient(load_settings().google_calendar_id).create_event(event.model_dump(mode="json"))


@app.patch("/api/calendar/events/{event_id}")
def update_calendar_event(event_id: str, event: CalendarEventRequest) -> dict[str, Any]:
    return CalendarClient(load_settings().google_calendar_id).update_event(event_id, event.model_dump(mode="json"))


@app.delete("/api/calendar/events/{event_id}")
def delete_calendar_event(event_id: str) -> dict[str, str]:
    CalendarClient(load_settings().google_calendar_id).delete_event(event_id)
    return {"status": "deleted", "event_id": event_id}


@app.get("/api/memories")
def memories() -> dict[str, Any]:
    settings = load_settings()
    if not settings.gmail_email:
        raise HTTPException(status_code=400, detail="GMAIL_EMAIL is not configured.")
    return {"memories": get_agent().memory.get_user_memories(settings.gmail_email)}


@app.get("/api/review")
def load_latest_review(
    email: str | None = Query(None, min_length=3),
    minutes_since: int = Query(2_880, ge=0),
) -> dict[str, Any]:
    scan_email = email or load_settings().gmail_email
    if not scan_email:
        raise HTTPException(status_code=400, detail="Set GMAIL_EMAIL in .env or provide an email address.")
    try:
        results = get_agent().process_inbox(
            scan_email,
            minutes_since=minutes_since,
            include_read=True,
            max_messages=5,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    reviews = [serialize_result(result) for result in results]
    reviews = [
        review
        for review in reviews
        if not (
            review["status"] == "complete"
            and (review.get("review_status") or {}).get("decision") in {"approve", "reject"}
        )
    ]
    if not reviews:
        return {"status": "empty", "message": "No matching Primary email was found."}
    return {"status": "batch", "count": len(reviews), "reviews": reviews}


@app.post("/api/review/{review_id}/decision")
def submit_decision(review_id: str, decision: ReviewDecision) -> dict[str, Any]:
    try:
        result = get_agent().resume_email(
            review_id,
            decision.decision,
            edited_reply=decision.edited_reply,
            feedback=decision.feedback,
        )
        if decision.decision == "approve":
            if result.get("intent") in {"respond", "respond_and_block_calendar"}:
                GmailClient().send_reply(result["email"], result["final_reply"])
            if result.get("intent") in {"block_calendar", "respond_and_block_calendar"}:
                calendar_event = result.get("calendar_event")
                if not calendar_event:
                    raise ValueError("Calendar event details were not provided by the triage model.")
                CalendarClient(load_settings().google_calendar_id).create_event(calendar_event)
    except Exception as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return serialize_result(result)


if __name__ == "__main__":
    uvicorn.run("inboxpilot.web:app", host="127.0.0.1", port=8000, reload=False)
