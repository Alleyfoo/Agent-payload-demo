from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.agents.shadow import ShadowAgent
from app.speaker import SpeakerAgent
from app.utils.llm_client import LLMClient

app = FastAPI(title="Moniagenttinen piiriarkkitehtuuri")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    run_id: str
    decision: str
    summary: str
    content: dict
    shadow_report_path: str


@app.on_event("startup")
async def startup_event() -> None:
    global speaker
    llm_client = LLMClient()
    shadow_agent = ShadowAgent()
    speaker = SpeakerAgent(llm_client, shadow_agent)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    result = speaker.process_and_summarize(request.message)
    response = result["response"]
    return ChatResponse(**response)
