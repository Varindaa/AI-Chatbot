"""Long-term user memory: deciding what to remember and what to recall.

The approach is deliberately rule-based (no embeddings, no extra LLM calls):

SAVING
  A message is split into statements. Questions and statements that aren't
  about the user ("I", "my", "me") are skipped. Each remaining statement is
  checked against a small set of categories:
    * goals (career, relationship, health, ...) need a topic word ("job")
      AND an intent word ("planning", "want", "hope")
    * facts (birth details, location, interests) need a trigger phrase
      ("I was born", "I live in", "I love")
    * language preference is detected with its own pattern ("prefer ... Hindi")

RECALL
  Before answering, a memory is passed to the LLM only if
    * the question mentions that category's topic words, or
    * the question shares a meaningful word with the stored memory.
  The language preference is always included because it shapes every reply.
  Generic questions like "What do you remember about me?" get everything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import LANGUAGE_KEY, LANGUAGES
from app.storage import Memory, Storage


def _words(*words: str) -> re.Pattern:
    """Case-insensitive whole-word pattern that also accepts simple plurals."""
    alternatives = "|".join(re.escape(w) for w in words)
    return re.compile(rf"\b(?:{alternatives})(?:s|es)?\b", re.IGNORECASE)


@dataclass(frozen=True)
class Category:
    key: str
    topic: re.Pattern            # a question mentioning these words is "about" this memory
    trigger: re.Pattern          # a statement must match this to be saved
    is_goal: bool = False        # goals must ALSO mention the topic when saved
    multi_valued: bool = False   # append new values instead of replacing

    def should_save(self, statement: str) -> bool:
        if not self.trigger.search(statement):
            return False
        return bool(self.topic.search(statement)) if self.is_goal else True


INTENT = re.compile(
    r"\b(?:plan|plans|planning|planned|want|wanting|hope|hoping|goal|aim|aiming|intend|"
    r"preparing|thinking (?:of|about)|going to|trying to|looking to|wish|dream)\b",
    re.IGNORECASE,
)

CATEGORIES: list[Category] = [
    Category("career_goal", is_goal=True, trigger=INTENT, topic=_words(
        "job", "career", "work", "promotion", "business", "startup", "office",
        "salary", "profession", "interview", "boss", "company", "employer")),
    Category("relationship_goal", is_goal=True, trigger=INTENT, topic=_words(
        "marriage", "married", "marry", "wedding", "partner", "relationship",
        "spouse", "love life", "boyfriend", "girlfriend", "husband", "wife")),
    Category("finance_goal", is_goal=True, trigger=INTENT, topic=_words(
        "money", "finance", "invest", "investment", "saving", "loan", "debt",
        "property", "house", "wealth")),
    Category("education_goal", is_goal=True, trigger=INTENT, topic=_words(
        "study", "exam", "college", "degree", "course", "university", "masters",
        "mba", "education")),
    Category("health_goal", is_goal=True, trigger=INTENT, topic=_words(
        "health", "fitness", "weight", "exercise", "diet", "sleep", "stress")),
    Category("birth_details",
             trigger=re.compile(r"\b(?:i was born|born on|born in|born at|my (?:birth|date of birth|dob))\b",
                                re.IGNORECASE),
             topic=_words("born", "birth", "kundli", "kundali", "horoscope", "chart",
                          "zodiac", "rashi", "nakshatra", "sign")),
    Category("location",
             trigger=re.compile(r"\b(?:i live in|i'm living in|i am living in|i stay in|i'm from|i am from)\b",
                                re.IGNORECASE),
             topic=_words("live", "city", "relocate", "relocation", "move", "abroad", "location")),
    Category("interests", multi_valued=True,
             trigger=re.compile(r"\bi (?:really |also )?(?:love|like|enjoy)\b|\b(?:interested in|passionate about)\b"
                                r"|\bmy (?:hobby|hobbies|passion)\b", re.IGNORECASE),
             topic=_words("hobby", "hobbies", "interest", "free time", "passion", "fun")),
]
CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}

LANGUAGE_PREFERENCE = re.compile(
    r"\b(?:prefer\w*|(?:reply|respond|answer|talk|speak|write)\w*(?: to me)?(?: only)? in)\b"
    rf"[^.!?]*?\b({'|'.join(LANGUAGES)})\b",
    re.IGNORECASE,
)
ALWAYS_INCLUDE = {LANGUAGE_KEY}  # affects how every answer is written

FIRST_PERSON = re.compile(r"\b(?:i|i'm|im|my|me|i've|i'd|i'll)\b", re.IGNORECASE)
RECALL_EVERYTHING = re.compile(r"\bwhat do you (?:remember|know)\b|\b(?:remember|know)\b.*\babout me\b",
                               re.IGNORECASE)

STOPWORDS = {
    "what", "should", "would", "could", "about", "your", "with", "have", "this", "that",
    "there", "their", "from", "will", "when", "where", "which", "focus", "tell", "know",
    "remember", "think", "want", "like", "please", "advice", "plan", "plans", "planning",
    "really", "also", "just", "some", "much", "more", "does", "doing", "going", "make",
    "been", "them", "they", "into", "over", "then", "than", "very", "help", "say",
}


# ---- saving --------------------------------------------------------------

def _statements(message: str) -> list[str]:
    """Split a message into non-question statements."""
    statements = []
    for sentence in re.findall(r"[^.!?]+[.!?]?", message):
        if sentence.strip().endswith("?"):
            continue  # questions are things to answer, not facts to remember
        for clause in re.split(r",\s*(?:and|but|so)\s+|;", sentence):
            clause = clause.strip(" .!,")
            if clause:
                statements.append(clause[0].upper() + clause[1:])
    return statements


def extract_memories(message: str) -> list[Memory]:
    """Find facts worth remembering in a message. Pure function, no I/O."""
    found: dict[str, Memory] = {}
    for statement in _statements(message):
        language = LANGUAGE_PREFERENCE.search(statement)
        if language:
            found[LANGUAGE_KEY] = Memory(LANGUAGE_KEY, language.group(1).capitalize())
            continue  # "I like answers in Hindi" is a preference, not an interest
        if not FIRST_PERSON.search(statement):
            continue  # other facts must be about the user ("I", "my"), not someone else
        for category in CATEGORIES:
            if category.key not in found and category.should_save(statement):
                found[category.key] = Memory(category.key, statement)
    return list(found.values())


def remember(storage: Storage, user_id: str, message: str) -> list[str]:
    """Extract memories from a message and persist them. Returns saved keys."""
    existing = {m.key: m.value for m in storage.get_memories(user_id)}
    saved = []
    for mem in extract_memories(message):
        value = mem.value
        category = CATEGORY_BY_KEY.get(mem.key)
        old = existing.get(mem.key)
        if category and category.multi_valued and old:
            if value.lower() in old.lower():
                continue  # already known
            value = f"{old}; {value}"
        storage.save_memory(user_id, mem.key, value)
        saved.append(mem.key)
    return saved


# ---- recall --------------------------------------------------------------

def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in STOPWORDS}


def _is_relevant(memory: Memory, query: str) -> bool:
    category = CATEGORY_BY_KEY.get(memory.key)
    if category and category.topic.search(query):
        return True
    return bool(_keywords(memory.value) & _keywords(query))


def recall(storage: Storage, user_id: str, query: str) -> list[Memory]:
    """Return only the memories that are relevant to the current question."""
    memories = storage.get_memories(user_id)
    relevant = [m for m in memories if m.key in ALWAYS_INCLUDE or _is_relevant(m, query)]
    has_topical_match = any(m.key not in ALWAYS_INCLUDE for m in relevant)
    if not has_topical_match and RECALL_EVERYTHING.search(query):
        return memories  # "What do you remember about me?" -> everything
    return relevant
