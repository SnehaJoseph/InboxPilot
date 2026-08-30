from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.types import Command

from inboxpilot.agent import InboxPilotAgent, TriageDecision
from inboxpilot.config import Settings


def test_parse_triage_decision_accepts_json_embedded_in_markdown():
    decision = InboxPilotAgent._parse_triage_decision(
        '```json\n{"intent":"respond","reasoning":"May need a reply.","requires_review":true,"question":"Draft a response?"}\n```'
    )

    assert decision == TriageDecision(
        intent="respond",
        reasoning="May need a reply.",
        requires_review=True,
        question="Draft a response?",
    )


def test_review_decision_reaches_review_node():
    class ReviewModel:
        def invoke(self, messages):
            return AIMessage(
                content='{"intent":"respond","reasoning":"Personal message may need a reply.","requires_review":true,"question":"Reply to this message?"}'
            )

    with patch("inboxpilot.agent.ModelFactory.create", return_value=ReviewModel()):
        agent = InboxPilotAgent(Settings())
        result = agent.process_email(
            {
                "from": "friend@example.com",
                "to": "user@example.com",
                "subject": "Catching up",
                "body": "Would love to hear from you.",
            }
        )

    assert result["intent"] == "respond"
    assert result["__interrupt__"][0].value["kind"] == "response"
    assert result["__interrupt__"][0].value["intent"] == "respond"
    assert result["__interrupt__"][0].value["reasoning"] == "Personal message may need a reply."
    assert result["__interrupt__"][0].value["email"]["subject"] == "Catching up"
    assert result["__interrupt__"][0].value["question"] == "Reply to this message?"
    assert result["__interrupt__"][0].value["draft_reply"]

    resumed = agent.graph.invoke(
        Command(resume={"decision": "approve"}),
        {"configurable": {"thread_id": "inboxpilot-review"}},
    )
    assert resumed["review_status"] == {"decision": "approve"}
    assert resumed["awaiting_human_review"] is False


def test_block_calendar_intent_prepares_action_for_review():
    class CalendarModel:
        def invoke(self, messages):
            return AIMessage(
                content='{"intent":"block_calendar","reasoning":"The email requests time to be reserved.","requires_review":true,"question":"Block Thursday at 2 PM?"}'
            )

    with patch("inboxpilot.agent.ModelFactory.create", return_value=CalendarModel()):
        agent = InboxPilotAgent(Settings())
        result = agent.process_email(
            {
                "from": "colleague@example.com",
                "to": "user@example.com",
                "subject": "Meeting Thursday",
                "body": "Can we meet Thursday at 2 PM?",
            }
        )

    assert result["intent"] == "block_calendar"
    assert result["__interrupt__"][0].value["kind"] == "calendar_action"
    assert result["__interrupt__"][0].value["intent"] == "block_calendar"
    assert result["__interrupt__"][0].value["reasoning"] == "The email requests time to be reserved."
    assert result["__interrupt__"][0].value["proposed_action"] == "Block the requested time on your calendar."
    assert result["__interrupt__"][0].value["question"] == "Block Thursday at 2 PM?"


def test_feedback_revises_calendar_proposal_and_stores_calendar_preference():
    class CalendarRevisionModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if "memory preference classifier" in messages[0]["content"]:
                return AIMessage(
                    content='{"preferences":[{"memory":"Move meetings one hour later when requested.","category":"calendar"}]}'
                )
            if self.calls == 1:
                return AIMessage(
                    content='{"intent":"block_calendar","reasoning":"A meeting was requested.","requires_review":true,"question":"Approve this event?","calendar_event":{"summary":"Meeting","start":"2026-09-01T14:00:00+05:30","end":"2026-09-01T15:00:00+05:30","timezone":"Asia/Kolkata","description":"Original time"}}'
                )
            return AIMessage(
                content='{"summary":"Meeting","start":"2026-09-01T15:00:00+05:30","end":"2026-09-01T16:00:00+05:30","timezone":"Asia/Kolkata","description":"Moved one hour later"}'
            )

    with patch("inboxpilot.agent.ModelFactory.create", return_value=CalendarRevisionModel()):
        agent = InboxPilotAgent(Settings())
        email = {
            "id": "calendar-revision-test",
            "from": "colleague@example.com",
            "to": "user@example.com",
            "subject": "Meeting",
            "body": "Can we meet at 2 PM?",
        }
        agent.process_email(email, user_id="user@example.com")
        revised = agent.resume_email(
            "calendar-revision-test", "revise", feedback="Move it one hour later."
        )

    review = revised["__interrupt__"][0].value
    assert review["calendar_event"]["start"] == "2026-09-01T15:00:00+05:30"
    assert "15:00:00" in review["proposed_action"]
    memories = agent.memory.get_user_memories("user@example.com")
    assert memories[0]["memory"] == "Move meetings one hour later when requested."
    assert memories[0]["metadata"]["category"] == "calendar"


def test_incoming_personal_message_uses_response_review():
    class PersonalModel:
        def invoke(self, messages):
            return AIMessage(
                content='{"intent":"respond","reasoning":"A person sent a conversational message that should receive a reply.","requires_review":true,"question":"Approve a reply to this personal message?"}'
            )

    with patch("inboxpilot.agent.ModelFactory.create", return_value=PersonalModel()):
        agent = InboxPilotAgent(Settings())
        result = agent.process_email(
            {
                "from": "friend@example.com",
                "to": "user@example.com",
                "subject": "Catching up",
                "body": "Hope you are doing well. How have you been?",
            }
        )

    review = result["__interrupt__"][0].value
    assert result["intent"] == "respond"
    assert review["question"] == "Approve a reply to this personal message?"


def test_feedback_revises_draft_before_approval():
    class RevisionModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if "memory preference classifier" in messages[0]["content"]:
                return AIMessage(
                    content='{"preferences":[{"memory":"Keep replies warm.","category":"response"}]}'
                )
            if self.calls == 1:
                return AIMessage(content='{"intent":"respond","reasoning":"A reply is appropriate.","requires_review":true,"question":"Approve this reply?"}')
            if self.calls == 2:
                return AIMessage(content="Initial draft")
            return AIMessage(content="Revised draft")

    model = RevisionModel()
    with patch("inboxpilot.agent.ModelFactory.create", return_value=model):
        agent = InboxPilotAgent(Settings())
        email = {"id": "revision-test", "from": "friend@example.com", "to": "user@example.com", "subject": "Hello", "body": "How are you?"}
        pending = agent.process_email(email)
        revised = agent.resume_email("revision-test", "revise", feedback="Make it warmer.")

    assert revised["__interrupt__"][0].value["draft_reply"] == "Revised draft"
    assert model.calls == 4


def test_approval_uses_edited_reply_and_saves_feedback():
    class ApprovalModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if "memory preference classifier" in messages[0]["content"]:
                return AIMessage(
                    content='{"preferences":[{"memory":"Keep future replies warm and direct.","category":"response"}]}'
                )
            if self.calls == 1:
                return AIMessage(
                    content='{"intent":"respond","reasoning":"A reply is appropriate.","requires_review":true,"question":"Approve this reply?"}'
                )
            return AIMessage(content="Initial draft")

    with patch("inboxpilot.agent.ModelFactory.create", return_value=ApprovalModel()):
        agent = InboxPilotAgent(Settings())
        email = {
            "id": "approval-feedback-test",
            "from": "friend@example.com",
            "to": "user@example.com",
            "subject": "Hello",
            "body": "How are you?",
        }
        agent.process_email(email, user_id="user@example.com")
        approved = agent.resume_email(
            "approval-feedback-test",
            "approve",
            edited_reply="My manually edited reply",
            feedback="Keep future replies warm and direct.",
        )

    assert approved["final_reply"] == "My manually edited reply"
    memories = agent.memory.get_user_memories("user@example.com")
    assert memories[0]["memory"] == "Keep future replies warm and direct."
    assert memories[0]["metadata"]["category"] == "response"


def test_combined_intent_reviews_reply_and_calendar_proposal_together():
    class CombinedModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content='{"intent":"respond_and_block_calendar","reasoning":"The email asks for a reply and a meeting time.","requires_review":true,"question":"Approve the reply and calendar proposal?"}')
            return AIMessage(content="Please confirm the meeting time.")

    with patch("inboxpilot.agent.ModelFactory.create", return_value=CombinedModel()):
        agent = InboxPilotAgent(Settings())
        result = agent.process_email(
            {
                "id": "combined-test",
                "from": "friend@example.com",
                "to": "user@example.com",
                "subject": "Meet Thursday",
                "body": "Can we meet Thursday at 2 PM?",
            }
        )

    review = result["__interrupt__"][0].value
    assert review["kind"] == "response_and_calendar_action"
    assert review["draft_reply"] == "Please confirm the meeting time."
    assert review["proposed_action"] == "Block the requested time on your calendar."


def test_combined_feedback_revises_reply_and_calendar_and_saves_preference():
    class CombinedRevisionModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if "memory preference classifier" in messages[0]["content"]:
                return AIMessage(
                    content='{"preferences":[{"memory":"Do not include the user phone number in email replies.","category":"response"},{"memory":"Prefer Saturday from 3 to 4 PM for weekend meetings.","category":"calendar"}]}'
                )
            if self.calls == 1:
                return AIMessage(
                    content='{"intent":"respond_and_block_calendar","reasoning":"Coordinate a meeting and hold the preferred time.","requires_review":true,"question":"Approve both actions?","calendar_event":{"summary":"Meeting with Suraj","start":"2026-09-05T14:00:00+05:30","end":"2026-09-05T15:00:00+05:30","timezone":"Asia/Kolkata","description":"Tentative hold"}}'
                )
            if self.calls == 2:
                return AIMessage(content="Saturday works for me.")
            return AIMessage(
                content='{"draft_reply":"I prefer Saturday between 3 and 4 PM. What time works best for you?","calendar_event":{"summary":"Tentative meeting with Suraj","start":"2026-09-05T15:00:00+05:30","end":"2026-09-05T16:00:00+05:30","timezone":"Asia/Kolkata","description":"Tentative hold pending Suraj confirmation"}}'
            )

    with patch("inboxpilot.agent.ModelFactory.create", return_value=CombinedRevisionModel()):
        agent = InboxPilotAgent(Settings())
        email = {
            "id": "combined-revision-test",
            "from": "Suraj <suraj@example.com>",
            "to": "user@example.com",
            "subject": "Weekend meeting",
            "body": "When should we meet this weekend?",
        }
        agent.process_email(email, user_id="user@example.com")
        revised = agent.resume_email(
            "combined-revision-test",
            "revise",
            feedback=(
                "Do not include my phone number in email replies. "
                "I prefer Saturday from 3 to 4 PM for weekend meetings. "
                "Ask Suraj what he prefers."
            ),
        )

    review = revised["__interrupt__"][0].value
    assert "What time works best for you?" in review["draft_reply"]
    assert review["calendar_event"]["start"] == "2026-09-05T15:00:00+05:30"
    assert "15:00:00" in review["proposed_action"]
    memories = agent.memory.get_user_memories("user@example.com")
    assert [item["metadata"]["category"] for item in memories] == ["response", "calendar"]
    assert "phone number" in memories[0]["memory"]
    assert memories[1]["memory"].startswith("Prefer Saturday")
