#!/usr/bin/env bash
# CASE ZERO -> Cloud Run
#
# NOT YET RUN. Written from current docs, never executed against a real project.
# Run preflight.py first, then work through this line by line rather than
# trusting it wholesale.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-case-zero}"
SA="case-zero-run@${PROJECT}.iam.gserviceaccount.com"

echo "==> project=$PROJECT region=$REGION service=$SERVICE"

# ---------------------------------------------------------------- 1. APIs
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "$PROJECT"

# ------------------------------------------------------------- 2. Firestore
# Native mode. One-time; fails harmlessly if the database already exists.
gcloud firestore databases create --location="$REGION" --project "$PROJECT" \
  || echo "    (firestore database already exists — continuing)"

# ------------------------------------------- 3. Least-privilege service account
gcloud iam service-accounts create case-zero-run \
  --display-name="CASE ZERO Cloud Run" --project "$PROJECT" \
  || echo "    (service account already exists — continuing)"

# datastore.user, NOT editor. The fleet writes its own case documents and
# nothing else; a compromised agent cannot reach the rest of the project.
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA}" --role="roles/datastore.user" --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA}" --role="roles/aiplatform.user" --condition=None

# ---------------------------------------------------------------- 4. Deploy
#
# --no-cpu-throttling is NOT optional here, and it is the single most likely
# thing to break this demo.
#
# Under Cloud Run's default request-based billing, CPU is allocated only while a
# request is being processed. POST /api/start returns immediately and the
# investigation continues on a background thread — which is exactly the work
# that gets frozen the moment the response is sent. The board would show the
# mission start and then nothing, and it would look like the fleet hung.
#
# --min-instances=1 keeps the instance (and the in-flight investigation) warm
# rather than scaling to zero mid-run.
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$SA" \
  --no-cpu-throttling \
  --min-instances=1 \
  --max-instances=1 \
  --cpu=2 --memory=2Gi \
  --timeout=3600 \
  --allow-unauthenticated \
  --set-env-vars="CASEZERO_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=${PROJECT},GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_LOCATION=${REGION}"

# max-instances=1 is deliberate: pop_lead() is read-then-update, not
# transactional, so two orchestrators would claim the same lead. Make that a
# constraint you chose rather than a bug you shipped.

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" \
       --project "$PROJECT" --format='value(status.url)')
echo
echo "==> deployed: $URL"
echo "==> show this URL and the Cloud Run console in the demo video — the rules"
echo "    require visible proof the backend runs on Google Cloud."
echo
echo "    logs:   gcloud run services logs tail $SERVICE --region $REGION"
echo "    traces: https://console.cloud.google.com/traces/list?project=$PROJECT"
