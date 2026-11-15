"""Orchestrates one chat turn: remember -> recall -> build prompt -> call LLM -> log."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app import memory
from app.config import BASE_PROMPT, FALLBACK_REPLY, HISTORY_MESSAGES
from app.llm import LLMClient
from app.storage import Memory, Storage

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    response: str
    context_used: list[str]    # memory keys sent to the LLM
    memories_saved: list[str]  # memory keys saved from this message


def build_system_prompt(memories: list[Memory]) -> str:
    parts = [BASE_PROMPT]

    facts = [m for m in memories if m.key != memory.LANGUAGE_KEY]
    if facts:
        lines = "\n".join(f"- {m.key.replace('_', ' ')}: {m.value}" for m in facts)
        parts.append(f"What the user has told you before:\n{lines}")

    language = next((m.value for m in memories if m.key == memory.LANGUAGE_KEY), None)
    if language:
        parts.append(f"The user prefers {language}. Write your reply in {language}.")

    return "\n\n".join(parts)


class ChatService:
    def __init__(self, storage: Storage, llm: LLMClient) -> None:
        self.storage = storage
        self.llm = llm

    def chat(self, user_id: str, session_id: str, message: str) -> ChatResult:
        # 1. Save anything worth remembering long-term (cross-session).
        saved = memory.remember(self.storage, user_id, message)

        # 2. Pick only the memories relevant to this question.
        relevant = memory.recall(self.storage, user_id, message)

        # 3. Short-term context: recent turns from this session only.
        history = self.storage.recent_messages(user_id, session_id, HISTORY_MESSAGES)
        messages = history + [{"role": "user", "content": message}]

        # 4. Ask the LLM, falling back to a polite message if the provider fails.
        try:
            reply = self.llm.generate(build_system_prompt(relevant), messages)
        except Exception:
            logger.exception("LLM call failed; returning fallback reply")
            reply = FALLBACK_REPLY

        # 5. Log the turn so the next message can use it as history.
        self.storage.add_message(user_id, session_id, "user", message)
        self.storage.add_message(user_id, session_id, "assistant", reply)

        return ChatResult(reply, [m.key for m in relevant], saved)
