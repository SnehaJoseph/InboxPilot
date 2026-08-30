from unittest.mock import MagicMock

from inboxpilot.config import Settings
from inboxpilot.memory import MemoryStore


def test_mem0_feedback_uses_user_filter_and_metadata():
    store = MemoryStore(Settings())
    store._client = MagicMock()
    store._client.add.return_value = {"results": []}

    store.store_feedback("user@example.com", "Keep replies warm and concise.")

    store._client.add.assert_called_once_with(
        [{"role": "user", "content": "Keep replies warm and concise."}],
        user_id="user@example.com",
        metadata={"category": "response", "intent": "respond", "source": "review_center"},
    )


def test_mem0_search_returns_memory_text():
    store = MemoryStore(Settings())
    store._client = MagicMock()
    store._client.search.return_value = {"results": [{"memory": "Keep replies concise."}]}

    assert store.get_relevant_memory("user@example.com", "reply") == ["Keep replies concise."]
    store._client.search.assert_called_once_with(
        query="reply",
        filters={"user_id": "user@example.com"},
        top_k=5,
    )


def test_mem0_memories_can_be_listed_for_user():
    store = MemoryStore(Settings())
    store._client = MagicMock()
    store._client.get_all.return_value = {
        "results": [{"id": "memory-1", "memory": "Keep replies concise.", "metadata": {"category": "response"}}]
    }

    memories = store.get_user_memories("user@example.com")

    assert memories[0]["memory"] == "Keep replies concise."
    store._client.get_all.assert_called_once_with(filters={"user_id": "user@example.com"})
