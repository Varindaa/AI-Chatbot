# MyNaksh — Personalized AI Chat

A small FastAPI chat service that answers with an LLM, uses recent session history for
follow-ups, remembers useful facts about a user across sessions, and sends the LLM only
the memories relevant to the current question.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...      # optional: without it, a mock LLM is used
uvicorn app.main:create_app --factory --reload
```

Open http://localhost:8000/docs for interactive API docs.

| Env var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Enables the real LLM |
| `LLM_PROVIDER` | `anthropic` if a key is set, else `mock` | `anthropic` or `mock` |
| `LLM_MODEL` | `claude-haiku-5-5` | Model name |
| `DB_PATH` | `chat.db` | SQLite file |

Run tests (no API key or network needed):

```bash
pytest
```

## Architecture

```
app/
  main.py          HTTP layer: request/response models, POST /chat
  chat_service.py  One chat turn: remember -> recall -> prompt -> LLM -> log
  memory.py        Rules for what to save and what to retrieve (pure logic)
  llm.py           LLMClient interface + Anthropic and Mock implementations
  storage.py       SQLite: messages table (history) + memories table
tests/
  test_chat.py     End-to-end tests through the API with a mock LLM
```

Each module has one job, and the dependencies point one way:
`main → chat_service → memory / llm / storage`. `create_app(storage, llm)` lets tests inject
an in-memory database and a mock LLM.

### One chat turn

1. **Remember.** Extract facts from the message and upsert them into `memories`.
2. **Recall.** Pick only the memories relevant to this message.
3. **History.** Load the last 6 messages (3 exchanges) of *this session*.
4. **Generate.** System prompt = persona + relevant memories + language instruction;
   messages = history + current message. If the LLM fails, return a fallback reply.
5. **Log.** Save the user message and reply to `messages`.

## Memory approach

**Storage.** One row per `(user_id, category)`, for example `career_goal` or
`language_preference`. The value is what the user said, e.g. *"I'm planning to switch jobs
next year"*. Saving the same category again replaces the old value, so corrections work
automatically. `interests` is the exception: it accumulates, because people have many.

**What gets saved (rule-based).** The message is split into statements. Questions are skipped.

- *Goals* (career, relationship, finance, education, health) need a topic word (*job*,
  *marriage*…) **and** an intent word (*planning*, *want*, *hope*…).
- *Facts* need a trigger phrase: *"I was born…"*, *"I live in…"*, *"I love…"*.
- *Language preference* is matched with patterns like *"prefer … Hindi"* or *"reply in English"*.
- Goals and facts must be first-person (*I / my / me*), so "my sister is getting married"
  isn't saved as the user's goal.

**What gets retrieved.** A memory is sent to the LLM only if the question mentions that
category's topic words, or shares a meaningful (non-stopword) word with the memory. The
language preference is always included because it affects every reply. A generic question
like *"What do you remember about me?"* returns everything. `context_used` in the response
lists exactly which memories were sent.

### Why rules instead of an LLM extractor or embeddings?

- **Predictable and testable.** Tests assert exact behaviour with no flakiness.
- **Cheap and fast.** No extra LLM call per message.
- **Easy to explain.** Every save or recall decision can be traced to a rule.

The trade-off is recall. Rules miss phrasings they don't anticipate ("thinking of quitting"
has no career word) and can't resolve "it"/"that". `memory.extract_memories` is a pure
function with the same output shape an LLM extractor would have, so it can be replaced
without touching the rest of the code.

### Known limitations / next steps

- Follow-ups like *"Why do you say that?"* don't re-retrieve memories (no topic words). The
  previous answer is in history, so context is kept, but retrieval could also carry over the
  last turn's `context_used`.
- Single-valued categories hold only the latest statement (e.g. one career goal).
- An LLM-based extractor (with JSON output and a confidence score) would improve recall.

## Sample requests and responses

Responses below come from the mock LLM; with a real key, `response` contains the model's
answer. The other fields are identical.

**1. Share a goal and a preference** (session-1)

```bash
curl -s localhost:8000/chat -H 'Content-Type: application/json' -d '{
  "user_id": "user-123", "session_id": "session-1",
  "message": "I love painting. I am planning to switch jobs next year, and I prefer advice in Hindi."
}'
```
```json
{
  "user_id": "user-123",
  "session_id": "session-1",
  "response": "[mock reply] You asked: I love painting. I am planning to switch jobs next year, and I prefer advice in Hindi.",
  "context_used": ["career_goal", "interests", "language_preference"],
  "memories_saved": ["interests", "career_goal", "language_preference"]
}
```

**2. Career question.** Painting is excluded as irrelevant.

```json
// request:  {"user_id": "user-123", "session_id": "session-1", "message": "What should I focus on for my career?"}
{
  "response": "...",
  "context_used": ["career_goal", "language_preference"],
  "memories_saved": []
}
```

**3. Follow-up** in the same session. The previous turns are sent as history.

```json
// request:  {"user_id": "user-123", "session_id": "session-1", "message": "Why do you say that?"}
{ "response": "...", "context_used": ["language_preference"], "memories_saved": [] }
```

**4. Recall in a new session**

```json
// request:  {"user_id": "user-123", "session_id": "session-2", "message": "What do you remember about my career plans?"}
{ "response": "...", "context_used": ["career_goal", "language_preference"], "memories_saved": [] }
```

**Inspect stored memories:** `GET /users/user-123/memories`

```json
[
  {"key": "career_goal", "value": "I am planning to switch jobs next year"},
  {"key": "interests", "value": "I love painting"},
  {"key": "language_preference", "value": "Hindi"}
]
```

## Tests

| Test | Verifies |
|---|---|
| `test_user_gets_a_response` | Basic request/response |
| `test_memory_is_saved_and_recalled_in_a_new_session` | Cross-session memory reaches the LLM prompt |
| `test_follow_up_question_uses_session_history` | History is sent for follow-ups; sessions are isolated |
| `test_irrelevant_memories_are_excluded` | An interest is not sent for a career question |
| `test_questions_are_not_stored_as_memories` | Not every message becomes a memory |
| `test_correction_replaces_old_memory` | "Reply in English" replaces "Hindi" |
| `test_memories_are_isolated_per_user` | No leakage between users |
| `test_fallback_reply_when_llm_fails` | Provider outage returns a graceful reply |
