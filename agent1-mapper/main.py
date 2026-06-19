"""
Agent 1: The Mapper (ADK)
Skeleton server — health, AgentCard, placeholder A2A endpoint, SSE events stream.
Real logic is added in Phase 2.
"""

import asyncio
import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.requests import Request
from starlette.responses import JSONResponse

app = FastAPI(title="Agent 1: Mapper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_CARD = {
    "name": "Codebase Mapper",
    "description": (
        "Receives a GitHub repo URL, maps its structure using the GitHub REST API, "
        "identifies the tech stack and entry points using Gemini, then delegates "
        "to Agent 2 (Code Reader) and Agent 3 (Explainer) via A2A."
    ),
    "version": "0.1.0",
    "framework": "Google ADK",
    "skills": [
        {
            "id": "map_repository",
            "name": "Map Repository",
            "description": "Produces a structured JSON map of a public GitHub repository.",
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }
    ],
    "capabilities": {"streaming": True},
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
}

_event_subscribers: list[asyncio.Queue] = []


def _now() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


async def _broadcast(event: dict) -> None:
    payload = f"data: {json.dumps(event)}\n\n"
    for q in list(_event_subscribers):
        await q.put(payload)


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "mapper", "phase": "skeleton"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.get("/events")
async def events(request: Request):
    """SSE endpoint — dashboard connects here to receive live updates."""
    queue: asyncio.Queue = asyncio.Queue()
    _event_subscribers.append(queue)

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'time': _now()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = queue.get_nowait()
                    yield msg
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.1)
        finally:
            _event_subscribers.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/a2a")
async def a2a_endpoint(request: Request):
    """
    A2A entry point — receives the initial task from the dashboard.
    Phase 1: echoes the request back as a placeholder.
    Phase 2: this becomes a full A2A task handler driving the whole pipeline.
    """
    body = await request.json()
    await _broadcast({
        "type": "log",
        "agent": "mapper",
        "message": f"Received task: {json.dumps(body)[:120]}",
        "time": _now(),
    })
    return {
        "status": "placeholder",
        "message": "Agent 1 skeleton — real logic in Phase 2",
        "received": body,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
