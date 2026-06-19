"""
Agent 2: LangGraph StateGraph — the iterative code reader.

Graph shape (the loop is the key LangGraph concept here):

    START
      |
   PRIORITIZE          ← decides which files to read first
      |
    READ  ←──────────┐  ← fetches one file from GitHub, asks Gemini what it does
      |               |
   CONNECT            |  ← finds imports/references, adds new files to the queue
      |               |
    CHECK ────────────┘  ← conditional: if more files AND under limit → loop back
      |                                 otherwise → SUMMARIZE
   SUMMARIZE               ← compiles everything into a final analysis JSON
      |
     END

State fields:
  repo_map          — the JSON from Agent 1 (input, never changes)
  files_to_read     — queue of files we still want to read
  files_read        — dict of {path: analysis_text} for files already done
  connections       — dict of {path: [list of files it references]}
  iteration_count   — how many READ iterations have run
  max_iterations    — hard cap (15) to prevent infinite loops
  final_analysis    — the output from SUMMARIZE (output)
"""

import json
import os
import re
from typing import TypedDict

import httpx
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

# ── LLM ──────────────────────────────────────────────────────────────────────
_llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.2,
)

# ── State definition ──────────────────────────────────────────────────────────

class ReaderState(TypedDict):
    repo_map: dict
    files_to_read: list[str]
    files_read: dict[str, str]
    connections: dict[str, list[str]]
    iteration_count: int
    max_iterations: int
    final_analysis: dict


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_raw_file(owner: str, repo: str, branch: str, path: str) -> str:
    """Fetch raw file content from GitHub (first 3000 chars)."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            if r.status_code == 200:
                return r.text[:3000]
    except Exception:
        pass
    return ""


def _ask_llm_sync(prompt: str) -> str:
    """Call Gemini synchronously and return the text response."""
    response = _llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


# ── Node functions ────────────────────────────────────────────────────────────

def prioritize(state: ReaderState) -> dict:
    """
    PRIORITIZE node.
    Looks at the repo map and picks the most important files to read first.
    Entry points (from Agent 1's analysis) go to the front of the queue.
    """
    repo_map = state["repo_map"]
    analysis = repo_map.get("analysis", {})
    entry_points = analysis.get("entry_points", [])
    main_modules = [m["name"] for m in analysis.get("main_modules", [])]

    # Build initial queue: entry points first, then main module paths
    seen = set()
    queue = []
    for path in entry_points + main_modules:
        if path and path not in seen:
            seen.add(path)
            queue.append(path)

    # Add a few top-level source files from the tree if the queue is thin
    folder_structure = repo_map.get("folder_structure", [])
    for folder in folder_structure[:5]:
        candidate = f"{folder}/__init__.py"
        if candidate not in seen:
            seen.add(candidate)
            queue.append(candidate)

    return {
        "files_to_read": queue[:15],  # cap initial queue at 15
        "files_read": {},
        "connections": {},
        "iteration_count": 0,
        "max_iterations": 15,
        "final_analysis": {},
    }


async def read_file(state: ReaderState) -> dict:
    """
    READ node.
    Pops the next file from the queue, fetches it from GitHub,
    and asks Gemini what it does in one sentence.
    """
    repo_map = state["repo_map"]
    owner = repo_map["owner"]
    repo = repo_map["repo"]
    branch = repo_map["metadata"].get("default_branch", "main")

    queue = list(state["files_to_read"])
    if not queue:
        return {"iteration_count": state["iteration_count"] + 1}

    current_file = queue[0]
    remaining = queue[1:]

    content = await _fetch_raw_file(owner, repo, branch, current_file)

    if content:
        prompt = (
            f"You are a code analyst. Read this file and answer in ONE sentence: "
            f"what does `{current_file}` do?\n\n```\n{content[:2000]}\n```"
        )
        summary = _ask_llm_sync(prompt)
    else:
        summary = "File not found or empty."

    files_read = dict(state["files_read"])
    files_read[current_file] = summary

    return {
        "files_to_read": remaining,
        "files_read": files_read,
        "iteration_count": state["iteration_count"] + 1,
    }


async def connect(state: ReaderState) -> dict:
    """
    CONNECT node.
    Takes the most recently read file and asks Gemini which other files
    it imports or references. Adds new, not-yet-read files to the queue.
    """
    repo_map = state["repo_map"]
    owner = repo_map["owner"]
    repo = repo_map["repo"]
    branch = repo_map["metadata"].get("default_branch", "main")

    files_read = state["files_read"]
    if not files_read:
        return {}

    last_file = list(files_read.keys())[-1]
    content = await _fetch_raw_file(owner, repo, branch, last_file)

    if not content:
        return {}

    prompt = (
        f"Look at this file `{last_file}`. "
        f"List ONLY the relative file paths it imports or references (not external libraries). "
        f"Return a JSON array of strings. If none, return []. "
        f"Example: [\"app/models.py\", \"utils/helpers.py\"]\n\n```\n{content[:2000]}\n```"
    )
    raw = _ask_llm_sync(prompt)

    # Parse the JSON array from the response
    match = re.search(r"\[.*?\]", raw, re.DOTALL)
    referenced: list[str] = []
    if match:
        try:
            referenced = json.loads(match.group())
        except json.JSONDecodeError:
            referenced = []

    # Add new files to the queue (avoid duplicates with already-read files)
    already_done = set(files_read.keys())
    current_queue = set(state["files_to_read"])
    new_files = [f for f in referenced if f not in already_done and f not in current_queue]

    connections = dict(state["connections"])
    connections[last_file] = referenced

    return {
        "files_to_read": state["files_to_read"] + new_files[:3],  # max 3 new per round
        "connections": connections,
    }


def check(state: ReaderState) -> str:
    """
    CHECK node — this is the conditional edge function.
    Returns a string key that LangGraph uses to decide the next node.

    "keep_reading" → go back to READ (the loop)
    "summarize"    → go to SUMMARIZE (exit the loop)
    """
    has_files_left = len(state["files_to_read"]) > 0
    under_limit = state["iteration_count"] < state["max_iterations"]

    if has_files_left and under_limit:
        return "keep_reading"
    return "summarize"


def summarize(state: ReaderState) -> dict:
    """
    SUMMARIZE node.
    Compiles everything into a final analysis JSON — file purposes,
    connection map, data flow.
    """
    files_read = state["files_read"]
    connections = state["connections"]

    file_list = "\n".join(
        f"- {path}: {summary}" for path, summary in files_read.items()
    )
    conn_list = "\n".join(
        f"- {src} → {', '.join(targets)}" for src, targets in connections.items() if targets
    )

    prompt = f"""
You are a software architect. Based on these file analyses:

{file_list}

And these file connections (A imports B):
{conn_list or "No explicit connections found."}

Write a JSON object with exactly these keys:
{{
  "file_purposes": {{"filename": "one sentence purpose"}},
  "connection_map": {{"filename": ["files it imports"]}},
  "data_flow": "2-3 sentences describing how data moves through the codebase",
  "key_patterns": ["list of 3 design patterns or architectural choices observed"]
}}

Return ONLY the JSON. No markdown, no explanation.
""".strip()

    raw = _ask_llm_sync(prompt)
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


# ── Build the graph ───────────────────────────────────────────────────────────

def build_reader_graph():
    """
    Assembles and compiles the StateGraph.
    Call this once at startup — the compiled graph is reusable.
    """
    graph = StateGraph(ReaderState)

    # Register nodes
    graph.add_node("prioritize", prioritize)
    graph.add_node("read", read_file)
    graph.add_node("connect", connect)
    graph.add_node("summarize", summarize)

    # Edges — the linear parts
    graph.add_edge(START, "prioritize")
    graph.add_edge("prioritize", "read")
    graph.add_edge("read", "connect")

    # Conditional edge — this is the loop
    # After CONNECT, run check() to decide: loop back to READ or go to SUMMARIZE
    graph.add_conditional_edges(
        "connect",
        check,
        {
            "keep_reading": "read",   # ← the loop-back edge
            "summarize": "summarize", # ← the exit edge
        },
    )

    graph.add_edge("summarize", END)

    return graph.compile()


# Module-level compiled graph — imported by main.py
reader_graph = build_reader_graph()
