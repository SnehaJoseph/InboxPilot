# InboxPilot Architecture and Application Walkthrough

This is a presentation-ready talk track for explaining InboxPilot's architecture, agent flow, design decisions, and user experience.

## 1. Introduction

InboxPilot is a human-in-the-loop email assistant. It reads recent Primary inbox messages and determines whether each message should be ignored, answered, scheduled on the calendar, or handled with both a reply and a calendar event.

The defining principle is controlled automation. The model interprets and proposes; the user reviews and approves; deterministic application code performs the external action. InboxPilot never sends mail or changes the calendar solely because a language model suggested it.

## 2. System architecture

The system diagram in the README is divided into five layers.

### Presentation layer

The Review Center is an HTML, CSS, and JavaScript interface served by FastAPI. It displays the original message, agent intent, reasoning, draft reply, calendar proposal, and review controls. The browser uses JSON endpoints, while credentials and provider calls remain on the server.

### Agent orchestration

LangGraph coordinates triage, drafting, calendar preparation, and human review. Its interrupt acts as a real checkpoint: the graph pauses with the email and proposed artifacts preserved, then resumes with an explicit approve, reject, or revise decision.

### Model layer

A Nebius-hosted model is accessed through an OpenAI-compatible interface. It performs structured triage, reply drafting, calendar interpretation, feedback-based revision, and preference classification. Model output is validated before it can control routing.

### Memory layer

Mem0 is the primary durable preference store. InboxPilot retrieves relevant user preferences before triage and drafting, allowing future proposals to reflect choices such as concise replies or preferred meeting times.

Feedback is processed by a dedicated classifier. It extracts durable preferences and stores each one separately as a response, calendar, or triage memory. If Mem0 is unavailable, a process-local fallback keeps development running, but that fallback is not durable across restarts.

### Google integrations

The Gmail client reads Primary inbox messages and sends approved replies. The Calendar client checks availability and creates approved events. Provider-specific logic stays outside the graph, and every external write remains behind approval.

## 3. Agent flowchart

The workflow for one email is:

1. Read a recent Primary email.
2. Return one validated intent: `ignore`, `respond`, `block_calendar`, or `respond_and_block_calendar`.
3. Complete ignored messages without an external action.
4. Draft a reply for response messages.
5. Prepare an event for scheduling messages.
6. Prepare both artifacts for combined messages.
7. Pause at the LangGraph human-review checkpoint.
8. Let the user edit, revise, reject, or approve.
9. Apply revision feedback and return the proposal for another review when requested.
10. On approval, resume the graph and execute the approved Gmail or Calendar operation.

Intent and review status are deliberately different concepts. Intent describes what the email needs. Pending, revised, approved, rejected, and addressed describe the lifecycle of the proposal.

## 4. Design decisions

### Structured output for reliable routing

Triage returns validated JSON rather than free-form prose. Routing depends on exact fields, so invalid responses fail clearly instead of silently taking the wrong branch.

### Explicit approval before side effects

Email sends and calendar writes are consequential. The model proposes them, but only application code can execute them after an explicit user decision.

### LangGraph interrupts as the HITL boundary

Review is part of workflow state, not merely a paused screen. The interrupt preserves the exact email, reasoning, draft, event, and thread identity until the graph resumes.

### Combined review for coordinated actions

If one email needs both a reply and a calendar hold, InboxPilot presents them together. The user can evaluate the communication and scheduling decision as one proposal.

### Direct editing plus model revision

Small changes can be made directly in the reply editor. Broader feedback can ask the model to revise the current artifacts. Approval sends the displayed edit exactly as shown instead of regenerating it at the final step.

### Semantic memory classification

Memory category is not inferred from the current email intent. One feedback message can contain several preferences, and a calendar review can contain a response preference. A separate classifier extracts and categorizes each durable preference independently.

### User-scoped memory

Mem0 retrieval and storage use the configured Gmail user as the boundary, preventing preferences from different users from being mixed.

### Thin integration clients

Gmail, Calendar, model, and memory concerns are isolated behind focused clients or adapters. This keeps orchestration understandable and makes integrations easier to test or replace.

### Transparent state

The Review Center exposes the original email, reasoning, proposals, and action status. After success, the addressed subject is named and removed from the pending list, making similar messages distinguishable.

## 5. Live application walkthrough

### Start the app

Run:

```powershell
.venv\Scripts\python.exe -m inboxpilot.web
```

Open `http://127.0.0.1:8000`. Explain that the browser is the review surface and FastAPI owns credentials and integrations.

### Inspect the inbox

Select **Inspect my new primary emails**. InboxPilot reads up to five recent Primary messages and processes them independently. Promotions may be ignored, while conversational messages may require replies or scheduling.

### Explain a review card

Point out the sender, subject, original content, intent, reasoning, editable draft, and calendar proposal. At this stage they are proposals; no external write has occurred.

### Edit or revise

Make a small direct edit to demonstrate deterministic user control. Then show **Revise with feedback** and explain that feedback can update the current proposal and contribute durable preferences.

### Show memory

Use **My saved preferences** to show response, triage, and calendar categories. Clarify that Mem0 is durable when configured, while the local fallback disappears on restart.

### Approve

Choose **Approve and send** only after checking both the reply and event. A response sends through Gmail, a calendar action creates an event, and a combined action performs both. The UI then marks the subject as addressed and shows the number of pending reviews.

### Verify externally

Open Gmail Sent mail and Google Calendar to prove that the operations are real provider changes, not local UI updates.

## 6. Operational considerations

A production deployment should add durable LangGraph checkpoints, authenticated Review Center access, audit records, monitoring, and idempotency controls.

Idempotency is particularly important for combined actions. If sending succeeds but calendar creation fails, a retry must not duplicate the successful operation. Until that protection is implemented, repeated approval attempts should be avoided and the calendar should be checked for duplicates during testing.

## 7. Closing summary

InboxPilot separates probabilistic reasoning from deterministic action. Nebius interprets and drafts, LangGraph manages workflow state, Mem0 supplies personalization, FastAPI exposes the review boundary, and Gmail and Calendar execute only approved operations.

The result is a personalized assistant that remains observable and under human control.

