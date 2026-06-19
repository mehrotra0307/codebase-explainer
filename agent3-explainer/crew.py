"""
Agent 3: CrewAI Crew — the Explainer.

Three sub-agents run in parallel (async_execution=True on their tasks),
then a fourth task synthesises everything into the final onboarding kit.

Sub-agents:
  Onboarding Writer  → New Developer Guide (max 400 words)
  Architect          → How Data Flows (max 300 words + text diagram)
  Prioritizer        → Top 5 most important files

Why parallel?
  CrewAI's Process.parallel doesn't exist in the current version.
  The correct pattern is: set async_execution=True on each parallel task,
  then create a final "synthesise" task that lists the three parallel tasks
  in its context= parameter. CrewAI then automatically waits for all three
  before running the final task.
"""

import os

from crewai import Agent, Crew, LLM, Process, Task

# ── LLM ──────────────────────────────────────────────────────────────────────
# CrewAI uses LiteLLM under the hood, so the model string needs the
# provider prefix "gemini/" for Google AI Studio.
_llm = LLM(
    model="gemini/gemini-2.0-flash",
    api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0.4,
)

# ── Sub-agents ────────────────────────────────────────────────────────────────

onboarding_writer = Agent(
    role="Onboarding Writer",
    goal="Write a warm, plain-English guide that helps a brand-new developer understand this codebase in under 5 minutes.",
    backstory=(
        "You are a technical writer who has spent years writing onboarding docs for open-source projects. "
        "You hate jargon and love analogies. You write as if talking to a smart friend who has never seen this repo."
    ),
    llm=_llm,
    verbose=False,
)

architect = Agent(
    role="Software Architect",
    goal="Explain how data moves through this codebase, tracing one user action from start to finish.",
    backstory=(
        "You are a senior architect who can read any codebase and immediately understand its data flow. "
        "You explain complex flows using simple text diagrams and plain English, never UML."
    ),
    llm=_llm,
    verbose=False,
)

prioritizer = Agent(
    role="Code Prioritizer",
    goal="Identify the 5 most important files a new developer should read first, and explain why each one matters.",
    backstory=(
        "You are an experienced engineering lead who onboards junior developers. "
        "You know exactly which files unlock understanding of an entire codebase. "
        "You explain file importance in one clear, specific sentence each."
    ),
    llm=_llm,
    verbose=False,
)


# ── Task factory ──────────────────────────────────────────────────────────────

def build_crew(repo_map: dict, code_analysis: dict) -> Crew:
    """
    Builds and returns a Crew configured for this specific repo.
    Called once per request so each run gets fresh tasks with the right context.
    """
    # Build a compact text brief to pass into each task description
    meta = repo_map.get("metadata", {})
    analysis = repo_map.get("analysis", {})
    tech_stack = ", ".join(analysis.get("tech_stack", ["unknown"]))
    arch_summary = analysis.get("architecture_summary", "")
    data_flow = code_analysis.get("data_flow", "")
    file_purposes = code_analysis.get("file_purposes", {})
    connection_map = code_analysis.get("connection_map", {})

    file_list = "\n".join(
        f"  - {path}: {purpose}" for path, purpose in list(file_purposes.items())[:20]
    )
    conn_list = "\n".join(
        f"  - {src} → {', '.join(targets)}"
        for src, targets in list(connection_map.items())[:10]
        if targets
    )

    brief = f"""
Repository: {meta.get('name', 'unknown')} ({meta.get('language', 'unknown')})
Description: {meta.get('description', '')}
Tech stack: {tech_stack}
Architecture: {arch_summary}
Data flow: {data_flow}

Files and what they do:
{file_list or '  (no file analysis available)'}

File connections (A imports B):
{conn_list or '  (no connection data available)'}
""".strip()

    # ── Three parallel tasks ──────────────────────────────────────────────────

    task_guide = Task(
        description=(
            f"Using this codebase brief:\n\n{brief}\n\n"
            "Write a 'New Developer Guide' (max 400 words). Cover: "
            "(1) what this project is and why it exists, "
            "(2) how to set it up locally (infer from the tech stack), "
            "(3) which files to read first and in what order. "
            "Use plain conversational English. No bullet walls. Write in paragraphs."
        ),
        expected_output="A 400-word max new developer guide in plain English, written in paragraphs.",
        agent=onboarding_writer,
        async_execution=True,  # runs in parallel with the other two tasks
    )

    task_flow = Task(
        description=(
            f"Using this codebase brief:\n\n{brief}\n\n"
            "Write a 'How Data Flows' explanation (max 300 words). "
            "Pick ONE representative user action (e.g. 'user sends a request', 'user adds an item'). "
            "Trace it from the entry point through the code to the data layer and back. "
            "Include a simple ASCII text diagram. Example diagram style:\n"
            "  User → routes.py → service.py → database.py → response\n"
            "Keep the diagram on one line or a few lines max."
        ),
        expected_output="A 300-word max data flow explanation with a simple ASCII diagram.",
        agent=architect,
        async_execution=True,  # runs in parallel
    )

    task_top5 = Task(
        description=(
            f"Using this codebase brief:\n\n{brief}\n\n"
            "Identify the 5 most important files in this codebase. "
            "For each file, write exactly ONE sentence explaining why it matters to a new developer. "
            "Format your response as a JSON array:\n"
            '[{"file": "path/to/file.py", "reason": "one sentence"}, ...]\n'
            "Return ONLY the JSON array. No markdown, no explanation outside the JSON."
        ),
        expected_output='A JSON array of 5 objects, each with "file" and "reason" keys.',
        agent=prioritizer,
        async_execution=True,  # runs in parallel
    )

    # ── Final synthesis task ──────────────────────────────────────────────────
    # This task does NOT run async — it runs AFTER the three above complete.
    # The context= parameter tells CrewAI to wait for all three and feed
    # their outputs into this task's context.

    task_combine = Task(
        description=(
            "You have received three pieces of analysis: "
            "(1) a New Developer Guide, (2) a Data Flow explanation, (3) a Top 5 Files list. "
            "Combine them into a single JSON object with exactly these keys:\n"
            "{\n"
            '  "new_developer_guide": "the full guide text",\n'
            '  "data_flow": "the full data flow text with diagram",\n'
            '  "top_5_files": [{"file": "...", "reason": "..."}]\n'
            "}\n"
            "Return ONLY the JSON. No markdown fences, no extra text."
        ),
        expected_output='A JSON object with keys: new_developer_guide, data_flow, top_5_files.',
        agent=onboarding_writer,  # reuse any agent for synthesis
        context=[task_guide, task_flow, task_top5],  # waits for all three
    )

    return Crew(
        agents=[onboarding_writer, architect, prioritizer],
        tasks=[task_guide, task_flow, task_top5, task_combine],
        process=Process.sequential,  # CrewAI handles async tasks within sequential process
        verbose=False,
    )


async def run_explainer(repo_map: dict, code_analysis: dict) -> dict:
    """
    Runs the crew and returns the parsed onboarding kit.
    Called by main.py's /a2a endpoint.
    """
    import json
    import re

    crew = build_crew(repo_map, code_analysis)
    result = crew.kickoff()

    # result.raw contains the final task's output text
    raw = result.raw if hasattr(result, "raw") else str(result)
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # If JSON parsing fails, return the raw text under a fallback key
        return {
            "new_developer_guide": raw,
            "data_flow": "",
            "top_5_files": [],
        }
