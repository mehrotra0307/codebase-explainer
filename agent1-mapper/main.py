"""
Agent 1: The Mapper (ADK)

Responsibilities:
  1. Receive a GitHub repo URL from the dashboard via POST /a2a
  2. Map the repository using the GitHub REST API
  3. Analyse the map using an ADK LlmAgent (Gemini Flash)
  4. Stream live progress to the dashboard via GET /events (SSE)
  5. Return a structured repo-map JSON
  6. (Phase 4) Forward the map to Agent 2, then combined results to Agent 3
"""

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.requests import Request
from starlette.responses import JSONResponse

import github_client as gh
from mapper_agent import analyze_repo

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
        "identifies the tech stack and entry points using Gemini via ADK, then "
        "delegates to Agent 2 (Code Reader) and Agent 3 (Explainer) via A2A."
    ),
    "version": "0.2.0",
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

# ── SSE subscriber list ───────────────────────────────────────────────────────
# Each connected dashboard gets a Queue. When we broadcast an event, every
# queue gets the message and each SSE response reads from its own queue.
_subscribers: list[asyncio.Queue] = []


def _now() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


async def _broadcast(event: dict) -> None:
    payload = f"data: {json.dumps(event)}\n\n"
    for q in list(_subscribers):
        await q.put(payload)


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(repo_url: str) -> None:
    """
    Full mapping pipeline. Runs in the background so /a2a can return immediately.
    Broadcasts SSE events throughout so the dashboard updates in real time.
    """
    await _broadcast({"type": "status", "agent": "mapper", "state": "working", "time": _now()})
    await _broadcast({"type": "log", "agent": "mapper", "message": f"Starting pipeline for: {repo_url}", "time": _now()})

    # ── 1. Parse GitHub URL ───────────────────────────────────────────────────
    try:
        owner, repo = gh.parse_github_url(repo_url)
    except ValueError as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR: {e}", "time": _now()})
        await _broadcast({"type": "status", "agent": "mapper", "state": "idle", "time": _now()})
        return

    await _broadcast({"type": "log", "agent": "mapper", "message": f"Parsed repo: {owner}/{repo}", "time": _now()})

    # ── 2. Repo metadata ──────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching repo metadata from GitHub…", "time": _now()})
    try:
        metadata = await gh.get_repo_metadata(owner, repo)
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR fetching metadata: {e}", "time": _now()})
        await _broadcast({"type": "status", "agent": "mapper", "state": "idle", "time": _now()})
        return

    await _broadcast({
        "type": "log", "agent": "mapper",
        "message": f"Repo: {metadata['name']} · {metadata['language']} · ⭐ {metadata['stars']:,}",
        "time": _now(),
    })

    # ── 3. File tree ──────────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching file tree…", "time": _now()})
    try:
        tree = await gh.get_file_tree(owner, repo, metadata["default_branch"])
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR fetching tree: {e}", "time": _now()})
        tree = []

    await _broadcast({"type": "log", "agent": "mapper", "message": f"Found {len(tree)} entries in tree", "time": _now()})

    # Stream top-level folders to the dashboard one by one
    folders = gh.extract_folders(tree, max_depth=2)
    for item in folders[:30]:  # cap at 30 for UI clarity
        depth = item["path"].count("/")
        indent = "  " * depth
        label = item["path"].split("/")[-1]
        await _broadcast({
            "type": "tree_entry",
            "text": f"{indent}📁 {label}/",
            "entry_type": "folder",
            "time": _now(),
        })
        await asyncio.sleep(0.04)  # small delay so the tree appears to build live

    # ── 4. Package files ──────────────────────────────────────────────────────
    pkg_file_paths = gh.find_package_files(tree)
    await _broadcast({
        "type": "log", "agent": "mapper",
        "message": f"Found package files: {pkg_file_paths or ['none']}",
        "time": _now(),
    })

    package_contents: dict[str, str] = {}
    for path in pkg_file_paths:
        content = await gh.get_file_content(owner, repo, path)
        if content:
            package_contents[path] = content
            await _broadcast({
                "type": "tree_entry",
                "text": f"  📄 {path}",
                "entry_type": "file",
                "time": _now(),
            })

    # ── 5. README ─────────────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching README…", "time": _now()})
    readme = await gh.get_readme(owner, repo)

    # ── 6. Build text summary for Gemini ─────────────────────────────────────
    top_paths = [item["path"] for item in tree if item["type"] == "tree"][:60]
    tree_text = "\n".join(top_paths)

    pkg_text = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in package_contents.items()
    )

    repo_summary = f"""
Repository: {owner}/{repo}
Primary language: {metadata['language']}
Description: {metadata['description']}
Topics: {', '.join(metadata['topics']) or 'none'}

--- Folder structure (top 60 paths) ---
{tree_text}

--- Package / build files ---
{pkg_text or 'None found'}

--- README (first 3000 chars) ---
{readme or 'No README found'}
""".strip()

    # ── 7. ADK / Gemini analysis ──────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Sending to Gemini for analysis (ADK)…", "time": _now()})

    session_id = str(uuid.uuid4())
    try:
        analysis = await analyze_repo(repo_summary, session_id)
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR in ADK agent: {e}", "time": _now()})
        analysis = {"tech_stack": [], "entry_points": [], "main_modules": [], "architecture_summary": ""}

    await _broadcast({"type": "log", "agent": "mapper", "message": "Gemini analysis complete", "time": _now()})

    # Stream tech badges to the dashboard
    for tech in analysis.get("tech_stack", []):
        await _broadcast({"type": "tech_badge", "tech": tech, "time": _now()})
        await asyncio.sleep(0.08)

    # ── 8. Build final repo map JSON ──────────────────────────────────────────
    repo_map = {
        "repo_url": repo_url,
        "owner": owner,
        "repo": repo,
        "metadata": metadata,
        "file_count": len(tree),
        "folder_structure": [item["path"] for item in folders],
        "package_files": {k: v[:500] for k, v in package_contents.items()},
        "readme_excerpt": readme[:1000],
        "analysis": analysis,
    }

    await _broadcast({
        "type": "log", "agent": "mapper",
        "message": f"Repo map built. Tech stack: {', '.join(analysis.get('tech_stack', []))}",
        "time": _now(),
    })

    # ── 9. Phase 4: forward to Agent 2 then Agent 3 ──────────────────────────
    # Placeholder — A2A calls to Agent 2 and Agent 3 are wired in Phase 4.
    await _broadcast({"type": "log", "agent": "mapper", "message": "(Phase 4) Will forward to Agent 2 via A2A next", "time": _now()})

    # ── 10. Done ──────────────────────────────────────────────────────────────
    await _broadcast({"type": "status", "agent": "mapper", "state": "done", "time": _now()})
    await _broadcast({
        "type": "pipeline_complete",
        "repo_map": repo_map,
        "time": _now(),
    })


# ── FastAPI routes ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "mapper", "phase": "2"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.get("/events")
async def events(request: Request):
    """
    SSE endpoint. The dashboard opens a persistent connection here.
    Every event broadcast by run_pipeline() arrives here and is pushed
    to the browser in real time.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.append(queue)

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
            if queue in _subscribers:
                _subscribers.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/a2a")
async def a2a_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Entry point for the dashboard.
    Starts the pipeline in the background and returns immediately (202).
    All progress is streamed via /events.
    """
    body = await request.json()
    repo_url = body.get("repo_url", "").strip()

    if not repo_url:
        return JSONResponse(status_code=400, content={"error": "repo_url is required"})

    task_id = str(uuid.uuid4())

    # Start pipeline without blocking this response
    background_tasks.add_task(run_pipeline, repo_url)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "task_id": task_id,
            "message": "Pipeline started. Watch /events for live updates.",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
