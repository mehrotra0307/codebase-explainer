"""
Agent 1: The Mapper (ADK) — the orchestrator.

Full pipeline:
  1. Receive GitHub URL from dashboard via POST /a2a
  2. Map the repository (GitHub REST API + ADK/Gemini analysis)
  3. Stream progress to dashboard via GET /events (SSE)
  4. Call Agent 2 (Code Reader) via A2A → get code analysis
  5. Call Agent 3 (Explainer) via A2A → get onboarding kit
  6. Stream results to dashboard
"""

import asyncio
import json
import os
import uuid
from datetime import datetime

import httpx
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
        "Orchestrator agent. Maps a GitHub repo, then delegates to Agent 2 "
        "(Code Reader) and Agent 3 (Explainer) via A2A to produce a complete "
        "developer onboarding kit."
    ),
    "version": "0.3.0",
    "framework": "Google ADK",
    "skills": [
        {
            "id": "map_repository",
            "name": "Map Repository",
            "description": "Full pipeline: map → read → explain.",
            "input_modes": ["application/json"],
            "output_modes": ["application/json"],
        }
    ],
    "capabilities": {"streaming": True},
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
}

AGENT2_URL = os.getenv("AGENT2_URL", "http://localhost:8002")
AGENT3_URL = os.getenv("AGENT3_URL", "http://localhost:8003")

_subscribers: list[asyncio.Queue] = []


def _now() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")


async def _broadcast(event: dict) -> None:
    # Include `event:` line so browser EventSource named listeners fire correctly
    event_type = event.get("type", "message")
    payload = f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
    for q in list(_subscribers):
        await q.put(payload)


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_pipeline(repo_url: str) -> None:
    await _broadcast({"type": "status", "agent": "mapper", "state": "working", "time": _now()})
    await _broadcast({"type": "log", "agent": "mapper", "message": f"Pipeline started for: {repo_url}", "time": _now()})

    # ── 1. Parse URL ─────────────────────────────────────────────────────────
    try:
        owner, repo = gh.parse_github_url(repo_url)
    except ValueError as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR: {e}", "time": _now()})
        await _broadcast({"type": "status", "agent": "mapper", "state": "idle", "time": _now()})
        return

    # ── 2. Repo metadata ──────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching repo metadata…", "time": _now()})
    try:
        metadata = await gh.get_repo_metadata(owner, repo)
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"ERROR: {e}", "time": _now()})
        await _broadcast({"type": "status", "agent": "mapper", "state": "idle", "time": _now()})
        return

    await _broadcast({
        "type": "log", "agent": "mapper",
        "message": f"{metadata['name']} · {metadata['language']} · ⭐ {metadata['stars']:,}",
        "time": _now(),
    })

    # ── 3. File tree ──────────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching file tree…", "time": _now()})
    try:
        tree = await gh.get_file_tree(owner, repo, metadata["default_branch"])
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"Tree fetch failed: {e}", "time": _now()})
        tree = []

    await _broadcast({"type": "log", "agent": "mapper", "message": f"Found {len(tree)} entries", "time": _now()})

    folders = gh.extract_folders(tree, max_depth=2)
    for item in folders[:30]:
        depth = item["path"].count("/")
        label = item["path"].split("/")[-1]
        await _broadcast({
            "type": "tree_entry",
            "text": "  " * depth + f"📁 {label}/",
            "entry_type": "folder",
            "time": _now(),
        })
        await asyncio.sleep(0.04)

    # ── 4. Package files ──────────────────────────────────────────────────────
    pkg_file_paths = gh.find_package_files(tree)
    package_contents: dict[str, str] = {}
    for path in pkg_file_paths:
        content = await gh.get_file_content(owner, repo, path)
        if content:
            package_contents[path] = content
            await _broadcast({"type": "tree_entry", "text": f"  📄 {path}", "entry_type": "file", "time": _now()})

    # ── 5. README ─────────────────────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Fetching README…", "time": _now()})
    readme = await gh.get_readme(owner, repo)

    # ── 6. Build Gemini prompt ────────────────────────────────────────────────
    top_paths = [i["path"] for i in tree if i["type"] == "tree"][:60]
    pkg_text = "\n\n".join(f"=== {n} ===\n{c}" for n, c in package_contents.items())

    repo_summary = f"""
Repository: {owner}/{repo}
Primary language: {metadata['language']}
Description: {metadata['description']}
Topics: {', '.join(metadata['topics']) or 'none'}

--- Folder structure ---
{chr(10).join(top_paths)}

--- Package files ---
{pkg_text or 'None found'}

--- README (first 3000 chars) ---
{readme or 'No README found'}
""".strip()

    # ── 7. ADK / Gemini analysis ──────────────────────────────────────────────
    await _broadcast({"type": "log", "agent": "mapper", "message": "Analysing with Gemini (ADK)…", "time": _now()})
    session_id = str(uuid.uuid4())
    try:
        analysis = await analyze_repo(repo_summary, session_id)
    except Exception as e:
        await _broadcast({"type": "log", "agent": "mapper", "message": f"Gemini error: {e}", "time": _now()})
        analysis = {"tech_stack": [], "entry_points": [], "main_modules": [], "architecture_summary": ""}

    for tech in analysis.get("tech_stack", []):
        await _broadcast({"type": "tech_badge", "tech": tech, "time": _now()})
        await asyncio.sleep(0.08)

    # ── 8. Build repo map ─────────────────────────────────────────────────────
    repo_map = {
        "repo_url": repo_url,
        "owner": owner,
        "repo": repo,
        "metadata": metadata,
        "file_count": len(tree),
        "folder_structure": [i["path"] for i in folders],
        "package_files": {k: v[:500] for k, v in package_contents.items()},
        "readme_excerpt": readme[:1000],
        "analysis": analysis,
    }

    await _broadcast({"type": "status", "agent": "mapper", "state": "done", "time": _now()})
    await _broadcast({
        "type": "log", "agent": "mapper",
        "message": f"Repo map complete. Tech: {', '.join(analysis.get('tech_stack', []))}",
        "time": _now(),
    })

    # ── 9. A2A call to Agent 2 ────────────────────────────────────────────────
    await _broadcast({
        "type": "a2a_send",
        "message": f"Agent 1 → Agent 2 (Code Reader): read_code for {owner}/{repo}",
        "time": _now(),
    })
    await _broadcast({"type": "status", "agent": "reader", "state": "working", "time": _now()})
    await _broadcast({"type": "log", "agent": "reader", "message": "Received repo map from Agent 1. Starting LangGraph loop…", "time": _now()})

    code_analysis: dict = {}
    files_read: int = 0
    iters: int = 0
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"{AGENT2_URL}/a2a", json={"repo_map": repo_map})
            r.raise_for_status()
            agent2_result = r.json()
            code_analysis = agent2_result.get("code_analysis", {})
            files_read = agent2_result.get("files_read_count", 0)
            iters = agent2_result.get("iterations_used", 0)
    except Exception as e:
        await _broadcast({"type": "log", "agent": "reader", "message": f"Agent 2 error: {e}", "time": _now()})

    await _broadcast({
        "type": "a2a_recv",
        "message": f"Agent 2 → Agent 1: code analysis done ({files_read} files, {iters} loops)",
        "time": _now(),
    })
    await _broadcast({"type": "status", "agent": "reader", "state": "done", "time": _now()})
    await _broadcast({"type": "iteration", "current": iters, "max": 15, "time": _now()})

    # Send file graph data to dashboard
    if code_analysis.get("file_purposes"):
        await _broadcast({
            "type": "graph_node",
            "files": list(code_analysis["file_purposes"].keys()),
            "time": _now(),
        })

    # ── 10. A2A call to Agent 3 ───────────────────────────────────────────────
    await _broadcast({
        "type": "a2a_send",
        "message": f"Agent 1 → Agent 3 (Explainer): explain_codebase for {owner}/{repo}",
        "time": _now(),
    })
    await _broadcast({"type": "status", "agent": "explainer", "state": "working", "time": _now()})
    await _broadcast({"type": "log", "agent": "explainer", "message": "Received data from Agent 1. Launching CrewAI crew…", "time": _now()})

    onboarding_kit: dict = {}
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{AGENT3_URL}/a2a",
                json={"repo_map": repo_map, "code_analysis": code_analysis},
            )
            r.raise_for_status()
            agent3_result = r.json()
            onboarding_kit = agent3_result.get("onboarding_kit", {})
    except Exception as e:
        await _broadcast({"type": "log", "agent": "explainer", "message": f"Agent 3 error: {e}", "time": _now()})

    await _broadcast({
        "type": "a2a_recv",
        "message": "Agent 3 → Agent 1: onboarding kit complete",
        "time": _now(),
    })
    await _broadcast({"type": "status", "agent": "explainer", "state": "done", "time": _now()})

    # Push results into the dashboard's Agent 3 column
    if onboarding_kit.get("new_developer_guide"):
        await _broadcast({"type": "result_guide", "text": onboarding_kit["new_developer_guide"], "time": _now()})
    if onboarding_kit.get("data_flow"):
        await _broadcast({"type": "result_flow", "text": onboarding_kit["data_flow"], "time": _now()})
    if onboarding_kit.get("top_5_files"):
        await _broadcast({"type": "result_top5", "items": onboarding_kit["top_5_files"], "time": _now()})

    await _broadcast({"type": "pipeline_complete", "time": _now()})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "agent": "mapper", "phase": "4"}


@app.get("/.well-known/agent.json")
async def agent_card():
    return JSONResponse(content=AGENT_CARD)


@app.get("/events")
async def events(request: Request):
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.append(queue)

    async def stream():
        try:
            yield f"event: connected\ndata: {json.dumps({'type': 'connected', 'time': _now()})}\n\n"
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
    body = await request.json()
    repo_url = body.get("repo_url", "").strip()
    if not repo_url:
        return JSONResponse(status_code=400, content={"error": "repo_url is required"})

    background_tasks.add_task(run_pipeline, repo_url)
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "message": "Pipeline started — watch /events"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
