"""
Agent 3: The Explainer (CrewAI)
FastAPI server that wraps the CrewAI crew.
Receives repo_map + code_analysis from Agent 1, runs the crew, returns onboarding kit.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from crew import run_explainer

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
        "Receives the repo map (from Agent 1) and code analysis (from Agent 2). "
        "Runs a CrewAI crew of three parallel sub-agents — Onboarding Writer, "
        "Architect, and Prioritizer — to produce a complete developer onboarding kit."
    ),
    "version": "0.2.0",
    "framework": "CrewAI",
    "skills": [
        {
            "id": "explain_codebase",
            "name": "Explain Codebase",
            "description": "Produces: New Developer Guide, How Data Flows, Top 5 Files.",
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }
    ],
    "capabilities": {"streaming": False},
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
}


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "explainer", "phase": "3"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a")
async def a2a_endpoint(request: Request):
    """
    Receives combined payload from Agent 1:
      { "repo_map": {...}, "code_analysis": {...} }
    Runs the CrewAI crew and returns the onboarding kit.
    """
    body = await request.json()
    repo_map = body.get("repo_map")
    code_analysis = body.get("code_analysis", {})

    if not repo_map:
        return JSONResponse(
            status_code=400,
            content={"error": "Expected payload with 'repo_map' key"},
        )

    onboarding_kit = await run_explainer(repo_map, code_analysis)

    return {
        "status": "complete",
        "onboarding_kit": onboarding_kit,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003, reload=False)
