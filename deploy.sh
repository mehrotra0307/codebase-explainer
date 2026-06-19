#!/bin/bash
# deploy.sh — deploys all three agents to Cloud Run using Cloud Build (no local Docker needed)
#
# Prerequisites:
#   gcloud auth login
#   gcloud auth application-default login
#   gcloud config set project YOUR_GCP_PROJECT_ID
#
# Usage:
#   export GCP_PROJECT=your-gcp-project-id
#   bash deploy.sh

set -e

# ── Configuration — set your GCP project ID ───────────────────────────────────
GCP_PROJECT="${GCP_PROJECT:?Please set GCP_PROJECT env var, e.g. export GCP_PROJECT=my-project}"
REGION="us-central1"

# ── 1. Enable required APIs ───────────────────────────────────────────────────
echo "==> Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  --project="${GCP_PROJECT}"

# ── 2. Deploy Agent 3 first (no outgoing A2A calls) ──────────────────────────
echo "==> Deploying Agent 3 (Explainer / CrewAI)..."
gcloud run deploy agent3-explainer \
  --source ./agent3-explainer \
  --region="${REGION}" \
  --allow-unauthenticated \
  --memory=2Gi \
  --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${GCP_PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},VERTEXAI_PROJECT=${GCP_PROJECT},VERTEXAI_LOCATION=${REGION}" \
  --project="${GCP_PROJECT}"

AGENT3_URL=$(gcloud run services describe agent3-explainer \
  --region="${REGION}" --project="${GCP_PROJECT}" \
  --format="value(status.url)")
echo "Agent 3 URL: ${AGENT3_URL}"

# ── 3. Deploy Agent 2 (no outgoing A2A calls) ─────────────────────────────────
echo "==> Deploying Agent 2 (Code Reader / LangGraph)..."
gcloud run deploy agent2-reader \
  --source ./agent2-reader \
  --region="${REGION}" \
  --allow-unauthenticated \
  --memory=1Gi \
  --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${GCP_PROJECT},GOOGLE_CLOUD_LOCATION=${REGION}" \
  --project="${GCP_PROJECT}"

AGENT2_URL=$(gcloud run services describe agent2-reader \
  --region="${REGION}" --project="${GCP_PROJECT}" \
  --format="value(status.url)")
echo "Agent 2 URL: ${AGENT2_URL}"

# ── 4. Deploy Agent 1 (knows the URLs of Agent 2 and 3) ──────────────────────
echo "==> Deploying Agent 1 (Mapper / ADK orchestrator)..."
gcloud run deploy agent1-mapper \
  --source ./agent1-mapper \
  --region="${REGION}" \
  --allow-unauthenticated \
  --memory=1Gi \
  --timeout=300 \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${GCP_PROJECT},GOOGLE_CLOUD_LOCATION=${REGION},AGENT2_URL=${AGENT2_URL},AGENT3_URL=${AGENT3_URL}" \
  --project="${GCP_PROJECT}"

AGENT1_URL=$(gcloud run services describe agent1-mapper \
  --region="${REGION}" --project="${GCP_PROJECT}" \
  --format="value(status.url)")
echo "Agent 1 URL: ${AGENT1_URL}"

# ── 5. Print final instructions ───────────────────────────────────────────────
echo ""
echo "========================================="
echo "  DEPLOYMENT COMPLETE"
echo "========================================="
echo "  Agent 1 (Mapper):    ${AGENT1_URL}"
echo "  Agent 2 (Reader):    ${AGENT2_URL}"
echo "  Agent 3 (Explainer): ${AGENT3_URL}"
echo ""
echo "  Next step: open dashboard/index.html"
echo "  and replace AGENT1_URL with:"
echo "  ${AGENT1_URL}"
echo "========================================="
