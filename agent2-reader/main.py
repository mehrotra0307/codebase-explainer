"""
Agent 2: The Code Reader (LangGraph)
Skeleton server — health, AgentCard, placeholder A2A endpoint.
Real LangGraph StateGraph loop is added in Phase 3.
"""

import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

app = FastAPI(title="Agent 2: Code Reader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_CARD = {
    "name": "Code Reader",
    "description": (
        "Receives a repo map from Agent 1, reads actual source files from GitHub "
        "using a LangGraph StateGraph loop, builds a file-connection graph, and "
        "returns a code analysis JSON."
    ),
    "version": "0.1.0",
    "framework": "LangGraph",
    "skills": [
        {
            "id": "read_code",
            "name": "Read Code",
            "description": (
                "Iteratively reads source files and maps their connections "
                "(up to 15 iterations)."
            ),
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }
    ],
    "capabilities": {"streaming": False},
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
}


def _now() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "reader", "phase": "skeleton"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a")
async def a2a_endpoint(request: Request):
    """
    A2A entry point — receives repo map from Agent 1.
    Phase 1: echoes the request back as a placeholder.
    Phase 3: this drives the LangGraph StateGraph loop.
    """
    body = await request.json()
    return {
        "status": "placeholder",
        "message": "Agent 2 skeleton — LangGraph loop added in Phase 3",
        "received_keys": list(body.keys()) if isinstance(body, dict) else str(body)[:80],
        "mock_analysis": {
            "files_read": [],
            "connections": {},
            "data_flow": "Not yet implemented",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
