# Codebase Explainer

A multi-agent system that takes any public GitHub repository URL and produces a complete onboarding kit for new developers — automatically.

Paste a GitHub URL. Three AI agents collaborate over the A2A protocol to map the repo, read the code, and write a developer guide. Results stream live to a dashboard.

## 🎥 Watch it in action

[![Watch the demo](https://img.youtube.com/vi/rAWRIidatlU/maxresdefault.jpg)](https://www.youtube.com/watch?v=rAWRIidatlU)

Full project write-up: [ashishmehrotra.com/projects/codebase-explainer](https://ashishmehrotra.com/projects/codebase-explainer)
Related blog post: [ashishmehrotra.com/blog/a2a-protocol-how-ai-agents-talk-to-each-other](https://ashishmehrotra.com/blog/a2a-protocol-how-ai-agents-talk-to-each-other)

---

## What It Does

You give it a GitHub URL like `https://github.com/tiangolo/fastapi`.

Within ~2 minutes you get back:

- **Tech stack** — every language, framework, and build tool detected
- **Architecture summary** — one-paragraph plain-English overview
- **New Developer Guide** — how to set up and navigate the project
- **Data Flow** — how a request travels through the codebase, with an ASCII diagram
- **Top 5 Files** — the five files a new developer should read first, with reasons

---

## Architecture

Three AI agents, each built on a different framework, communicate via the [A2A protocol](https://google.github.io/A2A/):

```
Dashboard (browser)
     │  POST /a2a + GET /events (SSE)
     ▼
┌─────────────────────────────┐
│  Agent 1 — Repo Mapper      │  Google ADK + Gemini 2.5 Flash
│  Fetches repo from GitHub   │  Identifies tech stack & architecture
│  Orchestrates the pipeline  │
└──────────┬──────────────────┘
           │ A2A
           ▼
┌─────────────────────────────┐
│  Agent 2 — Code Reader      │  LangGraph (StateGraph loop)
│  Reads actual source files  │  Maps imports & connections
│  Up to 15 iterations        │
└──────────┬──────────────────┘
           │ A2A
           ▼
┌─────────────────────────────┐
│  Agent 3 — Onboarding Writer│  CrewAI (3 parallel sub-agents)
│  Writes the developer guide │  Data flow + top 5 files
│  Returns structured JSON    │
└─────────────────────────────┘
```

**Key technical choices:**
- All agents run on **Cloud Run** (serverless, no servers to manage)
- **Vertex AI** with Application Default Credentials (no API keys in code)
- **Server-Sent Events (SSE)** stream live progress to the dashboard
- The dashboard is a single static HTML file — no build step, no framework

---

## Prerequisites

- **GCP account** with billing enabled
- **`gcloud` CLI** installed and authenticated
- **Python 3.11+** (only needed if running locally)
- A public GitHub repository to analyze (no auth needed)

---

## Deployment

### Step 1 — Authenticate with GCP

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

### Step 2 — Enable required GCP APIs

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com
```

### Step 3 — Deploy all three agents

Use the provided script (no local Docker required — Cloud Build handles it):

```bash
export GCP_PROJECT=your-gcp-project-id
bash deploy.sh
```

The script deploys agents in order (3 → 2 → 1) and prints the URLs at the end:

```
Agent 1 (Mapper):    https://agent1-mapper-XXXX.us-central1.run.app
Agent 2 (Reader):    https://agent2-reader-XXXX.us-central1.run.app
Agent 3 (Explainer): https://agent3-explainer-XXXX.us-central1.run.app
```

Deployment takes about 5–8 minutes total (Cloud Build compiles each image).

### Step 4 — Wire up the dashboard

Open `dashboard/index.html` in a text editor and replace the placeholder URL with your Agent 1 URL from Step 3:

```js
// line 377
const AGENT1_URL = "https://agent1-mapper-XXXX.us-central1.run.app";
```

### Step 5 — Open the dashboard

Open `dashboard/index.html` directly in your browser (no server needed — it's a plain HTML file):

```
File → Open → dashboard/index.html
```

Or on macOS:

```bash
open dashboard/index.html
```

### Step 6 — Analyze a repository

1. Paste any public GitHub URL into the input field
2. Click **Analyze**
3. Watch the three agent cards light up as each one runs
4. Read the results in the Agent 3 card when the pipeline completes

---

## Project Structure

```
codebase-explainer/
├── agent1-mapper/          # Agent 1 — Google ADK orchestrator
│   ├── main.py             # FastAPI server + SSE broadcaster + pipeline runner
│   ├── mapper_agent.py     # ADK LlmAgent wrapping Gemini 2.5 Flash
│   ├── github_client.py    # GitHub REST API calls (no auth needed for public repos)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── agent2-reader/          # Agent 2 — LangGraph iterative code reader
│   ├── main.py             # FastAPI server
│   ├── graph.py            # StateGraph: prioritize → read → connect → (loop) → summarize
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── agent3-explainer/       # Agent 3 — CrewAI onboarding writer
│   ├── main.py             # FastAPI server
│   ├── crew.py             # CrewAI Crew with 3 parallel agents + 1 synthesis task
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── dashboard/
│   └── index.html          # Single-file dashboard — SSE client + card UI
│
├── deploy.sh               # One-command deployment script (Cloud Build, no Docker)
└── .gitignore
```

---

## Running Locally (Optional)

Each agent can run locally for development. You need `gcloud` authenticated for Vertex AI.

```bash
# Terminal 1 — Agent 3 (start first, it has no dependencies)
cd agent3-explainer
pip install -r requirements.txt
GOOGLE_GENAI_USE_VERTEXAI=true \
GOOGLE_CLOUD_PROJECT=your-project \
VERTEXAI_PROJECT=your-project \
VERTEXAI_LOCATION=us-central1 \
uvicorn main:app --port 8003

# Terminal 2 — Agent 2
cd agent2-reader
pip install -r requirements.txt
GOOGLE_GENAI_USE_VERTEXAI=true \
GOOGLE_CLOUD_PROJECT=your-project \
uvicorn main:app --port 8002

# Terminal 3 — Agent 1
cd agent1-mapper
pip install -r requirements.txt
GOOGLE_GENAI_USE_VERTEXAI=true \
GOOGLE_CLOUD_PROJECT=your-project \
AGENT2_URL=http://localhost:8002 \
AGENT3_URL=http://localhost:8003 \
uvicorn main:app --port 8001
```

Then change `AGENT1_URL` in `dashboard/index.html` to `http://localhost:8001` and open it.

---

## Environment Variables

| Variable | Agent | Description |
|----------|-------|-------------|
| `GOOGLE_GENAI_USE_VERTEXAI` | 1, 2, 3 | Set to `true` to use Vertex AI instead of an API key |
| `GOOGLE_CLOUD_PROJECT` | 1, 2, 3 | Your GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | 1, 2, 3 | GCP region (default: `us-central1`) |
| `VERTEXAI_PROJECT` | 3 | Same as `GOOGLE_CLOUD_PROJECT` (required by CrewAI/LiteLLM) |
| `VERTEXAI_LOCATION` | 3 | Same as `GOOGLE_CLOUD_LOCATION` (required by CrewAI/LiteLLM) |
| `AGENT2_URL` | 1 | URL of Agent 2 (set automatically by `deploy.sh`) |
| `AGENT3_URL` | 1 | URL of Agent 3 (set automatically by `deploy.sh`) |
| `GITHUB_TOKEN` | 1 | Optional — raises GitHub API rate limit from 60 to 5000 req/hr |

---

## Frameworks Used

| Agent | Framework | Why |
|-------|-----------|-----|
| Agent 1 | [Google ADK](https://google.github.io/adk-docs/) | Structured LLM agent with session management |
| Agent 2 | [LangGraph](https://langchain-ai.github.io/langgraph/) | Stateful loop graph (read → connect → check → repeat) |
| Agent 3 | [CrewAI](https://docs.crewai.com/) | Parallel sub-agents with role-based prompting |
| All | [A2A Protocol](https://google.github.io/A2A/) | Standardized agent-to-agent HTTP communication |
| All | [Gemini 2.5 Flash](https://ai.google.dev/gemini-api/docs/models) | via Vertex AI |

---

## Cost

All LLM calls go through **Vertex AI** using Application Default Credentials. Gemini 2.5 Flash is very affordable — a typical pipeline run (one repo analysis) costs less than $0.01.

Cloud Run charges only for actual request time (no idle cost when not in use).

---

## License

MIT
