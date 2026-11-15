"""End-to-end tests through the HTTP API, using an in-memory DB and a mock LLM."""
import pytest
from fastapi.testclient import TestClient

from app.chat_service import FALLBACK_REPLY
from app.llm import MockLLM
from app.main import create_app
from app.memory import extract_memories
from app.storage import Storage

USER = "user-123"


@pytest.fixture
def llm():
    return MockLLM()


@pytest.fixture
def client(llm):
    return TestClient(create_app(storage=Storage(":memory:"), llm=llm))


def send(client, message, session="session-1", user=USER):
    response = client.post("/chat", json={"user_id": user, "session_id": session, "message": message})
    assert response.status_code == 200, response.text
    return response.json()


# ---- required behaviour ----------------------------------------------------

def test_user_gets_a_response(client):
    body = send(client, "Hello!")
    assert body["user_id"] == USER
    assert body["session_id"] == "session-1"
    assert body["response"]


def test_memory_is_saved_and_recalled_in_a_new_session(client, llm):
    first = send(client, "I'm planning to switch jobs next year, and I prefer advice in Hindi.", session="s1")
    assert set(first["memories_saved"]) == {"career_goal", "language_preference"}

    body = send(client, "What do you remember about my career plans?", session="s2")

    assert "career_goal" in body["context_used"]
    system_prompt = llm.calls[-1]["system"]
    assert "switch jobs next year" in system_prompt
    assert "Hindi" in system_prompt


def test_follow_up_question_uses_session_history(client, llm):
    send(client, "What should I focus on for my career?", session="s1")
    send(client, "Why do you say that?", session="s1")

    sent = llm.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "What should I focus on for my career?"

    # A different session starts with a clean history.
    send(client, "Why do you say that?", session="s2")
    assert len(llm.calls[-1]["messages"]) == 1


def test_irrelevant_memories_are_excluded(client, llm):
    send(client, "I love painting.", session="s1")
    send(client, "I'm planning to switch jobs next year.", session="s1")

    body = send(client, "What should I focus on for my career?", session="s2")

    assert "career_goal" in body["context_used"]
    assert "interests" not in body["context_used"]
    assert "painting" not in llm.calls[-1]["system"]


# ---- memory rules -----------------------------------------------------------

def test_questions_are_not_stored_as_memories():
    assert extract_memories("What should I focus on for my career?") == []
    assert extract_memories("Thanks, that was helpful.") == []


def test_correction_replaces_old_memory(client):
    send(client, "I prefer advice in Hindi.")
    send(client, "Actually, please reply in English.")

    memories = client.get(f"/users/{USER}/memories").json()
    assert {"key": "language_preference", "value": "English"} in memories


def test_memories_are_isolated_per_user(client, llm):
    send(client, "I'm planning to switch jobs next year.", user="alice")
    body = send(client, "What should I focus on for my career?", user="bob")
    assert body["context_used"] == []


# ---- resilience -------------------------------------------------------------

def test_fallback_reply_when_llm_fails():
    class BrokenLLM:
        def generate(self, system_prompt, messages):
            raise RuntimeError("provider down")

    client = TestClient(create_app(storage=Storage(":memory:"), llm=BrokenLLM()))
    assert send(client, "Hello")["response"] == FALLBACK_REPLY
