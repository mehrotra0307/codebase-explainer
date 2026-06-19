"""
ADK LlmAgent that analyses a raw repo summary and returns structured JSON.

Auth (pick one):
  Local dev  → set GOOGLE_API_KEY in .env
  Cloud Run  → set GOOGLE_GENAI_USE_VERTEXAI=true + GOOGLE_CLOUD_PROJECT
               and deploy with a service account that has Vertex AI User role.
               ADC handles the rest automatically.
"""

import json
import re

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

_MODEL = "gemini-2.0-flash"

_INSTRUCTION = """
You are a senior software architect.
You receive a text summary of a GitHub repository: its folder structure,
README excerpt, and any package files found.

Your job is to return ONLY a JSON object — no markdown, no explanation,
just the raw JSON — with exactly these keys:

{
  "tech_stack": ["list of technologies, languages, frameworks, build tools"],
  "entry_points": ["list of files where the app starts, e.g. main.py, index.js"],
  "main_modules": [
    {"name": "folder or file name", "purpose": "one sentence description"}
  ],
  "architecture_summary": "one paragraph plain-English summary of what this codebase does and how it is structured"
}

Rules:
- tech_stack must contain only real technologies visible in the file tree or package files.
- entry_points must be real file paths from the tree.
- main_modules should list the 5-8 most important directories or files only.
- architecture_summary must be plain English, no jargon, max 80 words.
- Output ONLY the JSON. Nothing else.
"""

_session_service = InMemorySessionService()

_agent = LlmAgent(
    model=_MODEL,
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
    """
    Send the repo summary text to Gemini via ADK and parse the JSON response.
    Returns a dict with keys: tech_stack, entry_points, main_modules, architecture_summary.
    """
    message = types.Content(
        role="user",
        parts=[types.Part(text=repo_summary)],
    )

    final_text = ""
    async for event in _runner.run_async(
        user_id="mapper_pipeline",
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or ""

    # Strip markdown code fences if Gemini adds them despite instructions
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", final_text).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Best-effort: return what we got as the summary
        return {
            "tech_stack": [],
            "entry_points": [],
            "main_modules": [],
            "architecture_summary": final_text.strip(),
        }
