from __future__ import annotations

from typing import Any

from inboxpilot.config import Settings

try:
    from mem0 import MemoryClient  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    MemoryClient = None


class MemoryStore:
    """User-scoped preference store backed by Mem0 with a local fallback."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings
        self._fallback_store: dict[str, dict[str, Any]] = {}
        self._client = None

        if settings and settings.mem0_api_key and MemoryClient is not None:
            self._client = MemoryClient(api_key=settings.mem0_api_key, host=settings.mem0_host)

    def store_user_preference(self, user_id: str, preference: str) -> dict[str, Any]:
        return self.store_feedback(user_id, preference)

    def store_feedback(
        self,
        user_id: str,
        feedback: str,
        *,
        intent: str = "respond",
        source: str = "review_center",
        category: str | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "category": category or self._category_for_intent(intent),
            "intent": intent,
            "source": source,
        }
        if self._client is not None:
            try:
                return self._client.add(
                    [{"role": "user", "content": feedback}],
                    user_id=user_id,
                    metadata=metadata,
                )
            except Exception:
                pass

        self._fallback_store.setdefault(user_id, {})
        memories = self._fallback_store[user_id].setdefault("memories", [])
        memories.append({"memory": feedback, "metadata": metadata})
        return {"user_id": user_id, "memories": memories}

    @staticmethod
    def _category_for_intent(intent: str) -> str:
        if intent in {"respond", "respond_and_block_calendar"}:
            return "response"
        if intent == "block_calendar":
            return "calendar"
        return "triage"

    def get_user_memories(self, user_id: str) -> list[dict[str, Any]]:
        if self._client is not None:
            try:
                result = self._client.get_all(filters={"user_id": user_id})
                items = result.get("results", []) if isinstance(result, dict) else result
                return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            except Exception:
                pass

        return list(self._fallback_store.get(user_id, {}).get("memories", []))

    def get_relevant_memory(self, user_id: str, query: str) -> list[str]:
        if self._client is not None:
            try:
                result = self._client.search(
                    query=query,
                    filters={"user_id": user_id},
                    top_k=5,
                )
                items = result.get("results", []) if isinstance(result, dict) else result
                if isinstance(items, list):
                    return [str(item.get("memory", item) if isinstance(item, dict) else item) for item in items]
                return [str(items)]
            except Exception:
                pass

        memories = self._fallback_store.get(user_id, {}).get("memories", [])
        if not memories:
            return []
        return [
            item["memory"]
            for item in memories
            if query.lower() in str(item.get("memory", "")).lower()
        ]
