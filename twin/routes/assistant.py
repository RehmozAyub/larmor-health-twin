"""Assistant API: readiness status, warm-up, sources, and the streaming answer endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from nmr_twin import assistant

router = APIRouter()


class Turn(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str = Field(max_length=4000)
    history: list[Turn] = Field(default_factory=list, max_length=40)
    screen: dict | None = None


@router.get("/assistant/status")
def status():
    return assistant.status()


@router.post("/assistant/warm")
def warm():
    assistant.warm_in_background()
    return assistant.status()


@router.get("/assistant/sources")
def sources():
    return assistant.sources()


@router.post("/assistant/ask")
def ask(req: AskRequest):
    stream = assistant.ask_stream(req.question, [t.model_dump() for t in req.history], req.screen)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
