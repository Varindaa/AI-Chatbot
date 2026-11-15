"""Central place for every constant and environment variable used by the app.

Environment variables (set these in .env or your shell):
    LLM_PROVIDER   mock (default) | anthropic | custom | any key of PROVIDERS below
    LLM_MODEL      model name, e.g. "gpt-4o-mini", "gemini-2.0-flash"
    LLM_API_KEY    API key; falls back to the provider's own variable
    LLM_BASE_URL   override the endpoint (required when LLM_PROVIDER=custom)
    DB_PATH        path to the SQLite database file (default: chat.db)
    LOG_FILE       path to the log file (default: app.log)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# ---- database ---------------------------------------------------------------

DB_PATH: str = os.getenv("DB_PATH", "chat.db")

# ---- logging ----------------------------------------------------------------

LOG_FILE: str = os.getenv("LOG_FILE", "app.log")

# ---- LLM provider -----------------------------------------------------------

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").lower()
LLM_MODEL: str | None = os.getenv("LLM_MODEL")
LLM_API_KEY: str | None = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str | None = os.getenv("LLM_BASE_URL")


@dataclass(frozen=True)
class Provider:
    base_url: str
    api_key_env: str | None  # None = no key needed (local models)


# Base URLs for each provider's OpenAI-compatible API.
# LLM_BASE_URL overrides any of them without a code change.
PROVIDERS: dict[str, Provider] = {
    "openai":     Provider("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "gemini":     Provider("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "grok":       Provider("https://api.x.ai/v1", "XAI_API_KEY"),
    "qwen":       Provider("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "kimi":       Provider("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    "deepseek":   Provider("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "groq":       Provider("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": Provider("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama":     Provider("http://localhost:11434/v1", None),
}

# ---- chat service -----------------------------------------------------------

HISTORY_MESSAGES: int = 6  # last 3 user/assistant exchanges kept per session

BASE_PROMPT: str = (
    "You are MyNaksh's friendly astrology assistant. Give warm, practical, concise guidance.\n"
    "Use the user details below only when they are relevant to the question.\n"
    "If the user asks what you remember about them, answer only from the details below; "
    "if none are listed, say you haven't saved anything about that yet."
)

FALLBACK_REPLY: str = "Sorry, I'm having trouble answering right now. Please try again in a moment."

# ---- memory / language ------------------------------------------------------

LANGUAGE_KEY: str = "language_preference"

LANGUAGES: tuple[str, ...] = (
    "hindi", "english", "hinglish", "tamil", "telugu", "bengali", "marathi",
    "gujarati", "kannada", "malayalam", "punjabi", "odia", "urdu",
)
