"""
Agent 2: LangGraph StateGraph — iterative code reader.
Uses Vertex AI via Application Default Credentials.

Graph: START → PRIORITIZE → READ ↔ CONNECT (loop) → SUMMARIZE → END
"""

import json
import os
import re
from typing import TypedDict

import httpx
from langchain_google_vertexai import ChatVertexAI
from langgraph.graph import END, START, StateGraph

_llm = ChatVertexAI(
    model="gemini-2.5-flash",
    project=os.getenv("GOOGLE_CLOUD_PROJECT"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
    temperature=0.2,
)


class ReaderState(TypedDict):
    repo_map: dict
    files_to_read: list[str]
    files_read: dict[str, str]
    connections: dict[str, list[str]]
    iteration_count: int
    max_iterations: int
    final_analysis: dict


async def _fetch_raw_file(owner: str, repo: str, branch: str, path: str) -> str:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.text[:3000]
    except Exception:
        pass
    return ""


async def _ask(prompt: str) -> str:
    response = await _llm.ainvoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def prioritize(state: ReaderState) -> dict:
    analysis = state["repo_map"].get("analysis", {})
    entry_points = analysis.get("entry_points", [])
    main_modules = [m["name"] for m in analysis.get("main_modules", [])]

    seen: set[str] = set()
    queue: list[str] = []
    for path in entry_points + main_modules:
        if path and path not in seen:
            seen.add(path)
            queue.append(path)

    for folder in state["repo_map"].get("folder_structure", [])[:5]:
        candidate = f"{folder}/__init__.py"
        if candidate not in seen:
            seen.add(candidate)
            queue.append(candidate)

    return {
        "files_to_read": queue[:15],
        "files_read": {},
        "connections": {},
        "iteration_count": 0,
        "max_iterations": 15,
        "final_analysis": {},
    }


async def read_file(state: ReaderState) -> dict:
    rm = state["repo_map"]
    owner, repo = rm["owner"], rm["repo"]
    branch = rm["metadata"].get("default_branch", "main")

    queue = list(state["files_to_read"])
    if not queue:
        return {"iteration_count": state["iteration_count"] + 1}

    current = queue[0]
    content = await _fetch_raw_file(owner, repo, branch, current)
    summary = (
        await _ask(f"One sentence: what does `{current}` do?\n\n```\n{content[:2000]}\n```")
        if content else "File not found."
    )

    files_read = dict(state["files_read"])
    files_read[current] = summary
    return {
        "files_to_read": queue[1:],
        "files_read": files_read,
        "iteration_count": state["iteration_count"] + 1,
    }


async def connect(state: ReaderState) -> dict:
    files_read = state["files_read"]
    if not files_read:
        return {}

    rm = state["repo_map"]
    last_file = list(files_read.keys())[-1]
    content = await _fetch_raw_file(
        rm["owner"], rm["repo"],
        rm["metadata"].get("default_branch", "main"),
        last_file,
    )
    if not content:
        return {}

    raw = await _ask(
        f"List relative file paths `{last_file}` imports (not external libs). "
        f"Return JSON array only. Example: [\"app/models.py\"]\n\n```\n{content[:2000]}\n```"
    )
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    referenced: list[str] = []
    if match:
        try:
            referenced = json.loads(match.group())
        except json.JSONDecodeError:
            pass

    already_done = set(files_read.keys())
    current_queue = set(state["files_to_read"])
    new_files = [f for f in referenced if f not in already_done and f not in current_queue]

    connections = dict(state["connections"])
    connections[last_file] = referenced
    return {
        "files_to_read": state["files_to_read"] + new_files[:3],
        "connections": connections,
    }


def check(state: ReaderState) -> str:
    if state["files_to_read"] and state["iteration_count"] < state["max_iterations"]:
        return "keep_reading"
    return "summarize"


async def summarize(state: ReaderState) -> dict:
    files_read = state["files_read"]
    connections = state["connections"]

    file_list = "\n".join(f"- {p}: {s}" for p, s in files_read.items())
    conn_list = "\n".join(
        f"- {src} → {', '.join(targets)}"
        for src, targets in connections.items() if targets
    ) or "No explicit connections found."

    raw = await _ask(f"""
Based on these file analyses:
{file_list}

And connections (A imports B):
{conn_list}

Return ONLY this JSON (no markdown):
{{
  "file_purposes": {{"filename": "one sentence purpose"}},
  "connection_map": {{"filename": ["files it imports"]}},
  "data_flow": "2-3 sentences on how data moves through the codebase",
  "key_patterns": ["3 design patterns or architectural choices observed"]
}}
""".strip())

    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        result = {
            "file_purposes": files_read,
            "connection_map": connections,
            "data_flow": raw[:500],
            "key_patterns": [],
        }

    return {
        "final_analysis": {
            **result,
            "files_read_count": len(files_read),
            "iterations_used": state["iteration_count"],
        }
    }


def build_reader_graph():
    graph = StateGraph(ReaderState)
    graph.add_node("prioritize", prioritize)
    graph.add_node("read", read_file)
    graph.add_node("connect", connect)
    graph.add_node("summarize", summarize)

    graph.add_edge(START, "prioritize")
    graph.add_edge("prioritize", "read")
    graph.add_edge("read", "connect")
    graph.add_conditional_edges(
        "connect", check,
        {"keep_reading": "read", "summarize": "summarize"},
    )
    graph.add_edge("summarize", END)
    return graph.compile()


reader_graph = build_reader_graph()
