from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from inboxpilot.config import Settings
from inboxpilot.gmail_client import GmailClient
from inboxpilot.llm import ModelFactory
from inboxpilot.memory import MemoryStore
from inboxpilot.review_center import ReviewCenter


class TriageDecision(BaseModel):
    intent: Literal["ignore", "respond", "block_calendar", "respond_and_block_calendar"] = Field(...)
    reasoning: str = Field(...)
    requires_review: bool = Field(...)
    question: str | None = Field(default=None)
    calendar_event: dict[str, Any] | None = Field(default=None)


class MemoryPreference(BaseModel):
    memory: str = Field(min_length=1)
    category: Literal["response", "calendar", "triage"]


class FeedbackClassification(BaseModel):
    preferences: list[MemoryPreference] = Field(default_factory=list)


class EmailState(dict):
    pass


class InboxPilotAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.memory = MemoryStore(settings)
        self.model = ModelFactory.create(settings)
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(dict)

        def triage_email(state: dict[str, Any]) -> dict[str, Any]:
            email = state["email"]
            user_id = state.get("user_id", "default")
            memories = self.memory.get_relevant_memory(user_id, email["subject"] + " " + email["body"])

            message = [
                {
                    "role": "system",
                    "content": (
                        "You are an inbox triage assistant for both personal and professional email. "
                        "Choose exactly one intent: ignore, respond, block_calendar, or respond_and_block_calendar. "
                        "Use respond for genuine conversational messages from another person, including personal messages, because they should be offered a reply. "
                        "A message sent by the user to their own address may be ignored unless it requests an action. "
                        "Use block_calendar when the email clearly asks to reserve time or schedule a meeting. "
                        "Use respond_and_block_calendar when the email needs both a reply and a calendar reservation. "
                        "Use ignore only when no response or calendar action is needed; do not treat personal email as automatically ignorable. "
                        "All respond, block_calendar, and respond_and_block_calendar intents require human review before anything is sent or changed. "
                        "Use the following user memory when relevant: "
                        + ("\n".join(memories) if memories else "No specific memory yet.")
                        + " Return only valid JSON with exactly these string fields: "
                        + '{"intent":"ignore|respond|block_calendar|respond_and_block_calendar","reasoning":"...","requires_review":true|false,"question":"...","calendar_event":{"summary":"...","start":"ISO-8601","end":"ISO-8601","timezone":"...","description":"..."}}. '
                        + "Set requires_review to true for respond, block_calendar, or respond_and_block_calendar and include a useful question. "
                        + "Set question to null for ignore. No markdown or extra text."
                        + f" The current local date and time is {datetime.now().astimezone().isoformat()}; use it to resolve relative dates such as Saturday."
                    ),
                },
                {
                    "role": "user",
                    "content": f"From: {email['from']}\nTo: {email['to']}\nSubject: {email['subject']}\nBody: {email['body']}",
                },
            ]

            decision = self.model.invoke(message)
            result = self._parse_triage_decision(decision.content)
            return {
                "intent": result.intent,
                "reasoning": result.reasoning,
                "requires_review": result.requires_review,
                "question": result.question,
                "calendar_event": result.calendar_event,
                "email": email,
                "user_id": user_id,
            }

        def draft_response(state: dict[str, Any]) -> dict[str, Any]:
            email = state["email"]
            user_id = state.get("user_id", "default")
            memories = self.memory.get_relevant_memory(user_id, email["subject"] + " " + email["body"])
            prompt = [
                {"role": "system", "content": "Draft a concise, appropriate email reply. " + ("Use these memory preferences:\n" + "\n".join(memories) if memories else "")},
                {"role": "user", "content": f"Compose a response to this email:\nFrom: {email['from']}\nSubject: {email['subject']}\nBody: {email['body']}"},
            ]
            reply = self.model.invoke(prompt)
            return {
                "draft_reply": reply.content,
                "intent": state["intent"],
                "email": email,
                "user_id": user_id,
                "reasoning": state["reasoning"],
                "calendar_event": state.get("calendar_event"),
                "review_question": state.get("question") or "Approve this draft reply?",
            }

        def prepare_calendar_action(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "proposed_action": self._calendar_proposal_text(state.get("calendar_event")),
                "calendar_event": state.get("calendar_event"),
                "review_question": state.get("question") or "Approve blocking this time on your calendar?",
                "intent": "block_calendar",
                "email": state["email"],
                "user_id": state.get("user_id", "default"),
                "reasoning": state["reasoning"],
            }

        def prepare_combined_action(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "draft_reply": state["draft_reply"],
                "proposed_action": self._calendar_proposal_text(state.get("calendar_event")),
                "calendar_event": state.get("calendar_event"),
                "review_question": state.get("question") or "Approve the reply and calendar proposal?",
                "intent": "respond_and_block_calendar",
                "email": state["email"],
                "user_id": state.get("user_id", "default"),
                "reasoning": state["reasoning"],
            }

        def review_response(state: dict[str, Any]) -> dict[str, Any]:
            draft_reply = state["draft_reply"]
            while True:
                decision = interrupt(
                    {
                        "review_center": "Review Center",
                        "kind": "response",
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "question": state["review_question"],
                        "draft_reply": draft_reply,
                    }
                )
                feedback = decision.get("feedback", "").strip()
                if feedback:
                    self._store_review_feedback(
                        state.get("user_id", "default"), feedback, state["intent"]
                    )
                if decision.get("decision") != "revise":
                    return {
                        "review_status": decision,
                        "final_reply": decision.get("edited_reply") or draft_reply,
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "awaiting_human_review": False,
                    }
                draft_reply = self._revise_reply(state["email"], draft_reply, feedback)

        def review_calendar_action(state: dict[str, Any]) -> dict[str, Any]:
            calendar_event = state.get("calendar_event")
            proposed_action = state["proposed_action"]
            while True:
                decision = interrupt(
                    {
                        "review_center": "Review Center",
                        "kind": "calendar_action",
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "question": state["review_question"],
                        "proposed_action": proposed_action,
                        "calendar_event": calendar_event,
                    }
                )
                feedback = decision.get("feedback", "").strip()
                if feedback:
                    self._store_review_feedback(
                        state.get("user_id", "default"), feedback, state["intent"]
                    )
                if decision.get("decision") != "revise":
                    return {
                        "review_status": decision,
                        "awaiting_human_review": False,
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "calendar_event": calendar_event,
                    }
                calendar_event = self._revise_calendar_event(
                    state["email"], calendar_event, feedback
                )
                proposed_action = self._calendar_proposal_text(calendar_event)

        def review_combined_action(state: dict[str, Any]) -> dict[str, Any]:
            draft_reply = state["draft_reply"]
            calendar_event = state.get("calendar_event")
            proposed_action = state["proposed_action"]
            while True:
                decision = interrupt(
                    {
                        "review_center": "Review Center",
                        "kind": "response_and_calendar_action",
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "question": state["review_question"],
                        "draft_reply": draft_reply,
                        "proposed_action": proposed_action,
                        "calendar_event": calendar_event,
                    }
                )
                feedback = decision.get("feedback", "").strip()
                if feedback:
                    self._store_review_feedback(
                        state.get("user_id", "default"), feedback, state["intent"]
                    )
                if decision.get("decision") != "revise":
                    return {
                        "review_status": decision,
                        "final_reply": decision.get("edited_reply") or draft_reply,
                        "email": state["email"],
                        "intent": state["intent"],
                        "reasoning": state["reasoning"],
                        "calendar_event": calendar_event,
                        "awaiting_human_review": False,
                    }
                draft_reply, calendar_event = self._revise_combined_action(
                    state["email"], draft_reply, calendar_event, feedback
                )
                proposed_action = self._calendar_proposal_text(calendar_event)

        def route(state: dict[str, Any]) -> str:
            intent = state.get("intent")
            if intent in {"respond", "respond_and_block_calendar"}:
                return "draft_response"
            if intent == "block_calendar":
                return "prepare_calendar_action"
            return END

        def route_after_draft(state: dict[str, Any]) -> str:
            if state.get("intent") == "respond_and_block_calendar":
                return "prepare_combined_action"
            return "review_response"

        builder.add_node("triage_email", triage_email)
        builder.add_node("draft_response", draft_response)
        builder.add_node("prepare_calendar_action", prepare_calendar_action)
        builder.add_node("prepare_combined_action", prepare_combined_action)
        builder.add_node("review_response", review_response)
        builder.add_node("review_calendar_action", review_calendar_action)
        builder.add_node("review_combined_action", review_combined_action)
        builder.add_edge(START, "triage_email")
        builder.add_conditional_edges(
            "triage_email",
            route,
            {"draft_response": "draft_response", "prepare_calendar_action": "prepare_calendar_action", END: END},
        )
        builder.add_conditional_edges(
            "draft_response",
            route_after_draft,
            {"review_response": "review_response", "prepare_combined_action": "prepare_combined_action"},
        )
        builder.add_edge("prepare_calendar_action", "review_calendar_action")
        builder.add_edge("prepare_combined_action", "review_combined_action")
        builder.add_edge("review_response", END)
        builder.add_edge("review_calendar_action", END)
        builder.add_edge("review_combined_action", END)
        return builder.compile(checkpointer=self.checkpointer)

    @staticmethod
    def _parse_triage_decision(content: str) -> TriageDecision:
        decoder = json.JSONDecoder()
        for index, character in enumerate(content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            return TriageDecision.model_validate(value)
        raise ValueError("The LLM response did not contain a valid triage JSON object.")

    @staticmethod
    def _calendar_proposal_text(event: dict[str, Any] | None) -> str:
        if not event:
            return "Block the requested time on your calendar."
        return f"Block '{event.get('summary', 'InboxPilot meeting')}' from {event.get('start')} to {event.get('end')} ({event.get('timezone', 'UTC')})."

    def _revise_reply(self, email: dict[str, Any], draft_reply: str, feedback: str) -> str:
        response = self.model.invoke(
            [
                {"role": "system", "content": "Revise the email reply using the user's feedback. Return only the revised reply text."},
                {
                    "role": "user",
                    "content": f"Original email:\n{email['body']}\n\nCurrent draft:\n{draft_reply}\n\nUser feedback:\n{feedback}",
                },
            ]
        )
        return response.content

    def _store_review_feedback(self, user_id: str, feedback: str, intent: str) -> None:
        classification = self._classify_feedback(feedback, intent)
        for preference in classification.preferences:
            self.memory.store_feedback(
                user_id,
                preference.memory,
                intent=intent,
                category=preference.category,
            )

    def _classify_feedback(self, feedback: str, intent: str) -> FeedbackClassification:
        response = self.model.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a memory preference classifier. Extract every distinct, durable "
                        "user preference from Review Center feedback and classify each independently. "
                        "Use category response for email wording, tone, content, signatures, contact "
                        "details, and reply style. Use calendar for availability, meeting times, "
                        "scheduling, duration, and calendar behavior. Use triage for priority, ignoring, "
                        "urgency, and email classification rules. Do not assign all preferences to the "
                        "current review intent. Do not store one-time instructions that only apply to "
                        "the current recipient, draft, or event. Preserve the user's meaning in a concise "
                        "standalone memory. Example: 'Never include my phone number. I prefer Saturday "
                        "evenings for meetings.' produces one response memory and one calendar memory. "
                        "Return only valid JSON in this exact shape: "
                        '{"preferences":[{"memory":"...","category":"response|calendar|triage"}]}. '
                        "Return an empty preferences list if there is nothing durable to remember."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Current review intent: {intent}\nFeedback:\n{feedback}",
                },
            ]
        )
        decoder = json.JSONDecoder()
        for index, character in enumerate(response.content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(response.content[index:])
            except json.JSONDecodeError:
                continue
            return FeedbackClassification.model_validate(value)
        raise ValueError(
            "The preference classifier did not return valid JSON; no action was executed."
        )

    def _revise_calendar_event(
        self,
        email: dict[str, Any],
        calendar_event: dict[str, Any] | None,
        feedback: str,
    ) -> dict[str, Any]:
        response = self.model.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "Revise the proposed calendar event using the user's feedback. "
                        "Return only a valid JSON object with summary, start, end, timezone, "
                        "and description fields. Preserve correct existing details unless the "
                        "feedback asks to change them."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original email:\n{email['body']}\n\n"
                        f"Current calendar event:\n{json.dumps(calendar_event or {})}\n\n"
                        f"User feedback:\n{feedback}"
                    ),
                },
            ]
        )
        decoder = json.JSONDecoder()
        for index, character in enumerate(response.content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(response.content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise ValueError("The LLM response did not contain a valid revised calendar event.")

    def _revise_combined_action(
        self,
        email: dict[str, Any],
        draft_reply: str,
        calendar_event: dict[str, Any] | None,
        feedback: str,
    ) -> tuple[str, dict[str, Any]]:
        response = self.model.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "Revise both the reply and calendar hold using the user's feedback. "
                        "When the user wants the sender's availability, make the reply clearly ask "
                        "the sender for their preferred time while stating the user's own availability. "
                        "Use the user's preferred slot for the proposed calendar hold. Return only "
                        "valid JSON in this form: "
                        '{"draft_reply":"...","calendar_event":{"summary":"...",'
                        '"start":"ISO-8601","end":"ISO-8601","timezone":"...",'
                        '"description":"..."}}. '
                        f"The current local date and time is {datetime.now().astimezone().isoformat()}."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original email:\n{email['body']}\n\n"
                        f"Current reply:\n{draft_reply}\n\n"
                        f"Current calendar event:\n{json.dumps(calendar_event or {})}\n\n"
                        f"User feedback:\n{feedback}"
                    ),
                },
            ]
        )
        decoder = json.JSONDecoder()
        for index, character in enumerate(response.content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(response.content[index:])
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and isinstance(value.get("draft_reply"), str)
                and isinstance(value.get("calendar_event"), dict)
            ):
                return value["draft_reply"], value["calendar_event"]
        raise ValueError("The LLM response did not contain a valid revised combined action.")

    def process_email(
        self,
        email: dict[str, Any],
        user_id: str = "default",
        interactive: bool = False,
    ) -> dict[str, Any]:
        state = {"email": email, "user_id": user_id}
        config = {"configurable": {"thread_id": email.get("id", "inboxpilot-review")}}
        result = self.graph.invoke(state, config)
        while interactive and result.get("__interrupt__"):
            review = result["__interrupt__"][0].value
            decision = ReviewCenter.prompt(review)
            result = self.graph.invoke(Command(resume=decision), config)
        return result

    def resume_email(
        self,
        email_id: str,
        decision: str,
        edited_reply: str | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": email_id}}
        return self.graph.invoke(
            Command(
                resume={
                    "decision": decision,
                    "edited_reply": edited_reply,
                    "feedback": feedback,
                }
            ),
            config,
        )

    def process_inbox(
        self,
        email_address: str,
        minutes_since: int = 120,
        include_read: bool = False,
        latest_only: bool = False,
        interactive: bool = False,
        max_messages: int | None = None,
    ) -> list[dict[str, Any]]:
        gmail = GmailClient()
        messages = gmail.list_recent_messages(
            email_address,
            minutes_since=minutes_since,
            include_read=include_read,
            latest_only=latest_only,
            max_messages=max_messages,
        )
        outputs: list[dict[str, Any]] = []
        for msg in messages:
            outputs.append(self.process_email(msg, user_id=email_address, interactive=interactive))
        return outputs
