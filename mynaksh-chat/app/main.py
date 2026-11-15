"""FastAPI application factory."""
from __future__ import annotations

import logging

from fastapi import FastAPI

import sys

_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
_file_handler = logging.FileHandler("app.log")
_file_handler.setFormatter(_fmt)
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_fmt)
logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(_file_handler)
logging.root.addHandler(_stream_handler)

from pydantic import BaseModel

from app.chat_service import ChatService
from app.config import DB_PATH
from app.llm import LLMClient, get_llm_client
from app.storage import Storage

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str


class ChatResponse(BaseModel):
    user_id: str
    session_id: str
    response: str
    context_used: list[str]
    memories_saved: list[str]


def create_app(storage: Storage | None = None, llm: LLMClient | None = None) -> FastAPI:
    _storage = storage or Storage(DB_PATH)
    _llm = llm or get_llm_client()
    service = ChatService(_storage, _llm)

    logger.info("App started — db=%s", DB_PATH)

    app = FastAPI()

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        logger.info("chat request  user=%s session=%s message=%r", req.user_id, req.session_id, req.message)
        result = service.chat(req.user_id, req.session_id, req.message)
        logger.info("chat response user=%s session=%s memories_saved=%s context_used=%s",
                    req.user_id, req.session_id, result.memories_saved, result.context_used)
        return ChatResponse(
            user_id=req.user_id,
            session_id=req.session_id,
            response=result.response,
            context_used=result.context_used,
            memories_saved=result.memories_saved,
        )

    @app.get("/users/{user_id}/memories")
    def get_memories(user_id: str) -> list[dict]:
        return [{"key": m.key, "value": m.value} for m in _storage.get_memories(user_id)]

    return app


app = create_app()
