"""
Agent 2: The Code Reader (LangGraph)
FastAPI server that wraps the LangGraph StateGraph.
Receives the repo map from Agent 1, runs the graph, returns code analysis.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from graph import reader_graph

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
        "using a LangGraph StateGraph loop (up to 15 iterations), builds a "
        "file-connection graph, and returns a structured code analysis JSON."
    ),
    "version": "0.2.0",
    "framework": "LangGraph",
    "skills": [
        {
            "id": "read_code",
            "name": "Read Code",
            "description": "Iteratively reads source files and maps their connections.",
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
    return {"status": "ok", "agent": "reader", "phase": "3"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a")
async def a2a_endpoint(request: Request):
    """
    Receives repo_map JSON from Agent 1.
    Runs the LangGraph StateGraph and returns the code analysis.
    """
    body = await request.json()
    repo_map = body.get("repo_map") or body

    if not repo_map or not repo_map.get("owner"):
        return JSONResponse(
            status_code=400,
            content={"error": "Expected a repo_map JSON object with at least an 'owner' field"},
        )

    # Initial state — the graph fills in the rest via the PRIORITIZE node
    initial_state = {
        "repo_map": repo_map,
        "files_to_read": [],
        "files_read": {},
        "connections": {},
        "iteration_count": 0,
        "max_iterations": 15,
        "final_analysis": {},
    }

    # ainvoke runs the full graph asynchronously and returns the final state
    # recursion_limit must be > max_iterations × nodes_per_loop to avoid GraphRecursionError
    final_state = await reader_graph.ainvoke(
        initial_state,
        config={"recursion_limit": 100},
    )

    return {
        "status": "complete",
        "code_analysis": final_state["final_analysis"],
        "files_read_count": len(final_state["files_read"]),
        "iterations_used": final_state["iteration_count"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002, reload=False)
