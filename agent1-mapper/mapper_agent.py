"""
ADK LlmAgent — analyses repo summary and returns structured JSON.
Uses Vertex AI via Application Default Credentials (no API key needed).
Set env vars: GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
"""

import json
import re

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

_INSTRUCTION = """
You are a senior software architect.
You receive a text summary of a GitHub repository.
Return ONLY a JSON object — no markdown, no explanation — with exactly these keys:

{
  "tech_stack": ["list of technologies, languages, frameworks, build tools"],
  "entry_points": ["list of files where the app starts"],
  "main_modules": [
    {"name": "folder or file name", "purpose": "one sentence description"}
  ],
  "architecture_summary": "one paragraph plain-English summary, max 80 words"
}

Output ONLY the JSON. Nothing else.
"""

_session_service = InMemorySessionService()

_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="repo_mapper",
    description="Analyses a GitHub repo structure and identifies tech stack and architecture.",
    instruction=_INSTRUCTION,
)

_runner = Runner(
    agent=_agent,
    app_name="codebase_mapper",
    session_service=_session_service,
)


async def analyze_repo(repo_summary: str, session_id: str) -> dict:
    # Create session explicitly — required by ADK 1.x before run_async
    await _session_service.create_session(
        app_name="codebase_mapper",
        user_id="mapper_pipeline",
        session_id=session_id,
    )
    message = types.Content(role="user", parts=[types.Part(text=repo_summary)])
    final_text = ""
    async for event in _runner.run_async(
        user_id="mapper_pipeline",
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""

    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", final_text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "tech_stack": [],
            "entry_points": [],
            "main_modules": [],
            "architecture_summary": final_text.strip(),
        }
