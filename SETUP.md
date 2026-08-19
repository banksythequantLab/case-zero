# Getting unblocked — 10 minutes

You do **not** need GCP for the thing that's currently blocking you.

Preflight's only failure is the contamination test, and that needs one Gemini
API key — not a project, not billing, not Cloud Run. Do step 1 and you're
unblocked. Steps 2–3 can wait until you're actually ready to deploy.

---

## 1. Gemini API key → run the contamination test  (3 min)

1. https://aistudio.google.com/apikey
2. **Create API key** (free tier is enough for this)
3. Copy it, then:

```bash
export GOOGLE_API_KEY="paste-it-here"
python3 cold_prompt_test.py --company "Netcapital Inc." --ticker NCPL
```

Five scored probes, two diagnostic. Writes `cold_prompt_result.json`.

- **CLEAN** → the case is blind. Everything downstream is valid. Re-run
  `python3 preflight.py` and it goes green.
- **CONTAMINATED** → stop and switch to RYVYL (see `CANDIDATES.md`). Do not
  rationalise a partial hit.

**Send me the output either way** and I'll read the verdict with you — the
red-flag grep is deliberately blunt and a borderline result deserves a human
look, not just a keyword match.

---

## 2. Single-shot baseline  (2 min, same key)

Before building anything else, find out what one Gemini call achieves on the
same corpus. Your headline number is *fleet minus single-shot* — that's the
number that argues for the architecture rather than for Gemini.

I can write this harness once you have the key working.

---

## 3. GCP project — only when you're ready to deploy

**Use Cloud Shell, not a local install.** It's a browser terminal with `gcloud`
already installed and already authenticated as you. No SDK download, no
`gcloud auth login` dance.

1. https://shell.cloud.google.com
2. Create or pick a project:

```bash
gcloud projects create case-zero-$RANDOM --name="CASE ZERO"   # or use an existing one
gcloud config set project YOUR_PROJECT_ID
gcloud config get-value project        # confirm
```

3. Link billing (required for Cloud Run — the $150 credit covers this):
   https://console.cloud.google.com/billing
4. Request the hackathon credits — **deadline Aug 28, 12:00 PT**, earlier than
   the submission deadline. Don't let this one slip.
5. Then, from the repo:

```bash
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export GOOGLE_CLOUD_LOCATION=us-central1
./deploy.sh
```

`deploy.sh` enables the APIs, creates the Firestore database, makes a
least-privilege service account, and deploys with `--no-cpu-throttling`. It has
never been run — expect to work through it a line at a time the first time.

---

## Why I can't do this part for you

Three hard blocks, not preferences:

1. **No desktop bridge in this session.** If the Claude desktop app were
   connected I could drive a browser on your machine. It isn't, so I can't.
2. **This sandbox can't reach the GCP console.** I tried:
   `console.cloud.google.com` returns `ERR_CONNECTION_RESET` — it's not on this
   container's network allowlist.
3. **Even if it loaded, it's your Google account.** I'd hit a login wall, and I
   shouldn't be holding credentials to your cloud project regardless.

What I *can* do the moment you have a key: interpret the contamination output,
write the baseline harness, and debug the live `adk_dispatch` run against real
Gemini responses — which is where the schema validation will actually break.
