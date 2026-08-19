# Deploy — the whole thing, in order

**Where:** Google Cloud Shell → **<https://shell.cloud.google.com>**

Cloud Shell already has `gcloud` and `git` authenticated as you. Nothing needs
installing. Last time the tarball upload failed, so this route clones from git
instead.

---

## 0 · Push the repo first (from your machine, 2 min)

**The remote is already set to `https://github.com/banksythequantlab/case-zero.git` and the branch is
`main`.** Three commits are staged and waiting.

First create the empty repo — **do not** let GitHub add a README, .gitignore or
licence, or the push will be rejected as a non-fast-forward:

<https://github.com/new?name=case-zero>

Then extract the tarball I sent and push:

```bash
cd case_zero
git push -u origin main
```

Private is fine, and is the safer choice here. If private, grant
`testing@devpost.com` and `cloudhackathons@google.com` under
**Settings → Collaborators**.

*If you name the repo something other than `case-zero`, fix the remote first:*
`git remote set-url origin https://github.com/banksythequantlab/<name>.git`

---

## 1 · Open Cloud Shell and clone

<https://shell.cloud.google.com>

```bash
git clone https://github.com/banksythequantlab/case-zero.git
cd case-zero
```

*(If the repo is private, Cloud Shell will prompt for a GitHub token — a
fine-grained PAT with read access to this one repo is enough.)*

---

## 2 · Set the three variables

```bash
export GOOGLE_CLOUD_PROJECT=gen-lang-client-0491046828
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_API_KEY=<your key>
```

**Rotate the key first** if you haven't — <https://aistudio.google.com/apikey>.
The old one was pasted in chat. Doing it now means you set the new one here once
instead of twice.

---

## 3 · Deploy

```bash
./deploy.sh
```

Takes 5–10 minutes; most of it is Cloud Build. It prints the service URL at the
end.

**I fixed a bug in this script today.** It used to set
`GOOGLE_GENAI_USE_VERTEXAI=True`, and Vertex returns `404 Publisher model not
found` for `gemini-3.5-flash` in us-central1 — so every deploy silently undid the
manual fix and the fleet died on its first dispatch. It now uses the Gemini API
key and refuses to run without one.

---

## 4 · Verify before you trust it

```bash
URL=$(gcloud run services describe case-zero --region us-central1 \
      --format='value(status.url)')
echo "$URL"                       # <- WRITE THIS DOWN, it is a Devpost field
curl -s -o /dev/null -w '%{http_code}\n' "$URL"        # expect 200
```

Then open `$URL` in a browser, click **BEGIN INVESTIGATION**, and watch the event
stream for a line beginning:

> **LEDGER RECONCILED** — 15 counterparties; $11,905,000 settled in customer
> equity…

✅ **If you see that line, you are running today's code.** If you don't, the build
didn't pick up the new modules — stop and tell me.

Reset between runs so a demo doesn't pile onto an earlier one:

```bash
curl -s -X POST "$URL/api/reset"
```

---

## 5 · Afterwards (only once judging closes)

```bash
gcloud run services delete case-zero --region us-central1
```

`--min-instances=1` bills continuously. Don't do this before judging — a dead
demo URL is worse than a few dollars.

---

## What I verified from here

- The repo produces a clean clone with **no answer key**, and preflight on that
  clone is **7 pass · 3 warn · 0 fail**
- The app starts and serves `200` on `/` and `/api/state` with **only** the files
  the Dockerfile copies (`casezero/`, `board.html`, `corpus/`, `requirements.txt`)
- The Dockerfile's answer-key assertion passes against that exact file set

## What I could not verify

- The actual `docker build` — no daemon in my sandbox
- The `gcloud` steps — no CLI, and no credentials here (Cloud Run API returns 401)

So step 3 is genuinely the first time this exact code meets Cloud Run. Budget for
one hiccup, and paste me anything that fails.
