import os
import time
from uuid import uuid4

import pytest

from inboxpilot.config import load_settings
from inboxpilot.memory import MemoryStore


@pytest.mark.skipif(
    os.getenv("RUN_MEM0_INTEGRATION") != "1",
    reason="Set RUN_MEM0_INTEGRATION=1 to run the live Mem0 check.",
)
def test_live_mem0_connection():
    settings = load_settings(env_file=r"D:\AIProjects\inboxpilot\.env")
    assert settings.mem0_api_key
    assert settings.mem0_host == "https://api.mem0.ai"

    store = MemoryStore(settings)
    memories = store.get_relevant_memory("inboxpilot-connectivity-test", "connection check")

    assert isinstance(memories, list)


@pytest.mark.skipif(
    os.getenv("RUN_MEM0_INTEGRATION") != "1",
    reason="Set RUN_MEM0_INTEGRATION=1 to run the live Mem0 check.",
)
def test_live_mem0_feedback_is_persisted_and_retrievable():
    settings = load_settings(env_file=r"D:\AIProjects\inboxpilot\.env")
    store = MemoryStore(settings)
    assert store._client is not None

    test_user = f"inboxpilot-persistence-test-{uuid4()}"
    feedback = "Prefer Saturday evening for weekend meetings."
    try:
        store.store_feedback(
            test_user,
            feedback,
            intent="respond_and_block_calendar",
            category="calendar",
            source="integration_test",
        )

        results = []
        for _ in range(10):
            raw = store._client.get_all(filters={"user_id": test_user})
            results = raw.get("results", []) if isinstance(raw, dict) else raw
            if results:
                break
            time.sleep(1)

        assert results, "Mem0 accepted the write but no persisted memory could be retrieved."
        assert results[0].get("metadata", {}).get("category") == "calendar"
    finally:
        store._client.delete_all(user_id=test_user)
