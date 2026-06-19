"""
Agent 3: CrewAI Crew — three parallel sub-agents producing the onboarding kit.
Uses Vertex AI via Application Default Credentials.
"""

import asyncio
import json
import os
import re

from crewai import Agent, Crew, LLM, Process, Task

_llm = LLM(
    model="vertex_ai/gemini-2.5-flash",
    temperature=0.4,
)

onboarding_writer = Agent(
    role="Onboarding Writer",
    goal="Write a warm, plain-English guide for a brand-new developer.",
    backstory="You are a technical writer who hates jargon and loves analogies.",
    llm=_llm,
    verbose=False,
)

architect = Agent(
    role="Software Architect",
    goal="Explain how data moves through the codebase by tracing one user action.",
    backstory="You explain complex flows with simple ASCII diagrams and plain English.",
    llm=_llm,
    verbose=False,
)

prioritizer = Agent(
    role="Code Prioritizer",
    goal="Identify the 5 most important files a new developer should read first.",
    backstory="You are an engineering lead who knows which files unlock an entire codebase.",
    llm=_llm,
    verbose=False,
)


def build_crew(repo_map: dict, code_analysis: dict) -> Crew:
    meta = repo_map.get("metadata", {})
    analysis = repo_map.get("analysis", {})
    tech_stack = ", ".join(analysis.get("tech_stack", ["unknown"]))

    file_purposes = code_analysis.get("file_purposes", {})
    connection_map = code_analysis.get("connection_map", {})

    brief = f"""
Repository: {meta.get('name', 'unknown')} ({meta.get('language', 'unknown')})
Description: {meta.get('description', '')}
Tech stack: {tech_stack}
Architecture: {analysis.get('architecture_summary', '')}
Data flow: {code_analysis.get('data_flow', '')}

Files:
{chr(10).join(f'  - {p}: {s}' for p, s in list(file_purposes.items())[:20]) or '  (none)'}

Connections (A imports B):
{chr(10).join(f'  - {s} → {", ".join(t)}' for s, t in list(connection_map.items())[:10] if t) or '  (none)'}
""".strip()

    task_guide = Task(
        description=(
            f"Codebase brief:\n\n{brief}\n\n"
            "Write a 'New Developer Guide' (max 400 words): what the project is, "
            "how to set it up, which files to read first. Plain paragraphs only."
        ),
        expected_output="400-word max new developer guide in plain English paragraphs.",
        agent=onboarding_writer,
        async_execution=True,
    )

    task_flow = Task(
        description=(
            f"Codebase brief:\n\n{brief}\n\n"
            "Write a 'How Data Flows' explanation (max 300 words). "
            "Trace ONE user action through the code with a simple ASCII diagram. "
            "Example: User → routes.py → service.py → db.py → response"
        ),
        expected_output="300-word max data flow explanation with ASCII diagram.",
        agent=architect,
        async_execution=True,
    )

    task_top5 = Task(
        description=(
            f"Codebase brief:\n\n{brief}\n\n"
            "List the 5 most important files. ONE sentence each on why it matters. "
            'Return ONLY JSON array: [{"file": "path", "reason": "one sentence"}]'
        ),
        expected_output='JSON array of 5 objects with "file" and "reason" keys.',
        agent=prioritizer,
        async_execution=True,
    )

    task_combine = Task(
        description=(
            "Combine the three outputs into a single JSON object:\n"
            "{\n"
            '  "new_developer_guide": "full guide text",\n'
            '  "data_flow": "full data flow with diagram",\n'
            '  "top_5_files": [{"file": "...", "reason": "..."}]\n'
            "}\n"
            "Return ONLY the JSON. No markdown."
        ),
        expected_output='JSON with keys: new_developer_guide, data_flow, top_5_files.',
        agent=onboarding_writer,
        context=[task_guide, task_flow, task_top5],
    )

    return Crew(
        agents=[onboarding_writer, architect, prioritizer],
        tasks=[task_guide, task_flow, task_top5, task_combine],
        process=Process.sequential,
        verbose=False,
    )


async def run_explainer(repo_map: dict, code_analysis: dict) -> dict:
    crew = build_crew(repo_map, code_analysis)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, crew.kickoff)

    raw = result.raw if hasattr(result, "raw") else str(result)
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"new_developer_guide": raw, "data_flow": "", "top_5_files": []}
