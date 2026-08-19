# Deploy runbook — Cloud Shell, step by step

You have the project and the credits. This is the next blocker.

`deploy.sh` exists but **has never been executed**. Do not run it blind — work
through the checkpoints below. Each step has a verification you can eyeball
before moving on, because a failure three steps back is miserable to diagnose
from a Cloud Run error.

Budget 1–2 hours for the first pass. Expect two or three things to break.

---

## 0. Open Cloud Shell

https://shell.cloud.google.com — gcloud is installed and already authenticated
as you. Don't install the SDK locally.

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud config get-value project          # ✅ prints your project id
gcloud auth list                         # ✅ your account, ACTIVE
```

---

## 1. Get the code into Cloud Shell

Two ways. Pick one.

**A — upload the tarball** (simplest). Cloud Shell menu ⋮ → *Upload* →
`case_zero.tar.gz`, then:

```bash
mkdir -p ~/case-zero && tar -xzf ~/case_zero.tar.gz -C ~/case-zero
cd ~/case-zero && ls
```

**B — push to GitHub first**, then clone. Better if you want the repo link in
the submission anyway (the rules require a repo with spin-up instructions).

```bash
git clone https://github.com/YOU/case-zero.git ~/case-zero && cd ~/case-zero
```

✅ **Checkpoint:** `ls corpus | wc -l` prints **72** (71 filings + manifest).

> **Before you push to GitHub:** confirm `.env` is not in the tarball — it isn't
> in the ones I sent, and `.gitignore` covers it, but check. `git status` should
> never list `.env`.

---

## 2. Local sanity before touching the cloud

```bash
pip install -r requirements.txt --quiet
python3 preflight.py
```

✅ **Checkpoint:** `8 pass · 2 warn · 0 fail`.
The two warns are expected: no `GOOGLE_API_KEY` exported in this shell, and the
identity-KNOWN note from the contamination test. **Any FAIL, stop and fix.**

---

## 3. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com firestore.googleapis.com aiplatform.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com
```

Takes 1–2 minutes. ✅ `gcloud services list --enabled | grep -E 'run|firestore|aiplatform'`
shows all three.

---

## 4. Firestore — **the irreversible one**

```bash
gcloud firestore databases create --location=us-central1
```

⚠️ **A project's Firestore mode (Native vs Datastore) cannot be changed later.**
This creates Native mode, which is what the code expects. If the project already
has a Datastore-mode database, make a new project rather than fighting it.

✅ `gcloud firestore databases list` shows one database, type `FIRESTORE_NATIVE`.

---

## 5. Service account — least privilege on purpose

```bash
PROJECT=$(gcloud config get-value project)
gcloud iam service-accounts create case-zero-run --display-name="CASE ZERO Cloud Run"

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:case-zero-run@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/datastore.user" --condition=None

gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:case-zero-run@${PROJECT}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" --condition=None
```

`datastore.user`, not `editor`. Worth a sentence in the video: a compromised
agent can write its own case documents and reach nothing else in the project.

---

## 6. Deploy

```bash
export GOOGLE_CLOUD_PROJECT=$(gcloud config get-value project)
export GOOGLE_CLOUD_LOCATION=us-central1
./deploy.sh
```

First build takes 5–10 minutes (Cloud Build packaging the corpus).

### The flag that is not optional

`deploy.sh` passes **`--no-cpu-throttling`**. Under Cloud Run's default
request-based billing, CPU is allocated only while a request is being processed.
`POST /api/start` returns immediately and the investigation continues on a
background thread — exactly the work that gets frozen the moment the response is
sent. **The board would show the mission start and then nothing**, looking for
all the world like the fleet hung.

If you ever hand-roll the deploy, keep that flag and `--min-instances=1`.

✅ **Checkpoint:** the script prints a `https://case-zero-….run.app` URL.

---

## 7. Verify before you trust it

```bash
URL=$(gcloud run services describe case-zero --region us-central1 --format='value(status.url)')
curl -s -o /dev/null -w "%{http_code}\n" $URL          # ✅ 200
curl -s $URL/api/state | head -c 200                   # ✅ JSON, counts present
```

Open `$URL` in a browser. ✅ Board renders, KPI row reads 71 documents, status
STANDBY.

**Do not click BEGIN yet.** First confirm the model credentials work in the
cloud, or you'll watch it fail live:

```bash
gcloud run services logs tail case-zero --region us-central1
```

Then click BEGIN in the browser and watch the log. ✅ Within ~30s you should see
dispatch activity. ❌ If you see auth errors, the service account is missing
`aiplatform.user`, or `GOOGLE_GENAI_USE_VERTEXAI` isn't set — both are in the
`--set-env-vars` line in `deploy.sh`.

---

## 8. Capture the video evidence

The rules require visible proof the backend runs on Google Cloud. Get these four
tabs loaded and authenticated *before* you record:

1. Cloud Run service page — URL visible, green check
2. `gcloud run services logs tail case-zero --region us-central1`
3. Cloud Trace — https://console.cloud.google.com/traces/list
4. Firestore — `cases/0001/events`, the audit trail persisted

---

## Known failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Board loads, mission starts, then nothing | CPU throttling | `gcloud run services update case-zero --no-cpu-throttling --region us-central1` |
| Container fails health check | app not listening on `$PORT` | already handled; check the Dockerfile wasn't edited |
| `PERMISSION_DENIED` on Firestore | missing `datastore.user` | re-run step 5 |
| `403` calling Gemini | missing `aiplatform.user`, or Vertex not enabled | step 3 + step 5 |
| Build fails on `RUN test ! -e complaint.pdf` | answer key leaked into the build context | check `.dockerignore` survived the transfer |
| Investigation dies partway | budget exhausted (expected) | raise `Budget(max_dispatches=...)` in `board.py` |

## Cost

A full fleet run is roughly **$1–2** in Gemini tokens. Cloud Run with
`min-instances=1` runs a few dollars a day, so **delete the service after the
video** unless judges need it live:

```bash
gcloud run services delete case-zero --region us-central1
```

The $150 covers this comfortably — but min-instances=1 bills whether or not
anyone is using it, and that is how people quietly burn a credit balance.
