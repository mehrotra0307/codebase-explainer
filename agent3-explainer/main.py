"""
Agent 3: The Explainer (CrewAI)
Skeleton server — health, AgentCard, placeholder A2A endpoint.
Real CrewAI crew with three parallel sub-agents is added in Phase 3.
"""

import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

app = FastAPI(title="Agent 3: Explainer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AGENT_CARD = {
    "name": "Codebase Explainer",
    "description": (
        "Receives the repo map and code analysis from Agent 1, then runs a "
        "CrewAI crew of three specialized sub-agents (Onboarding Writer, "
        "Architect, Prioritizer) to produce a developer onboarding kit."
    ),
    "version": "0.1.0",
    "framework": "CrewAI",
    "skills": [
        {
            "id": "explain_codebase",
            "name": "Explain Codebase",
            "description": "Produces: New Developer Guide, Data Flow explanation, Top 5 Files.",
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
    return {"status": "ok", "agent": "explainer", "phase": "skeleton"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a")
async def a2a_endpoint(request: Request):
    """
    A2A entry point — receives combined repo map + code analysis from Agent 1.
    Phase 1: echoes the request back as a placeholder.
    Phase 3: this kicks off the CrewAI crew.
    """
    body = await request.json()
    return {
        "status": "placeholder",
        "message": "Agent 3 skeleton — CrewAI crew added in Phase 3",
        "received_keys": list(body.keys()) if isinstance(body, dict) else str(body)[:80],
        "mock_onboarding_kit": {
            "new_developer_guide": "Not yet implemented",
            "data_flow": "Not yet implemented",
            "top_5_files": [],
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
