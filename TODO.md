# CASE ZERO — what's left

**Aug 19. Submission closes Aug 31, 5:00 PM PT. 12 days.**

The build is done, deployed and tested. Everything below is yours — I can't
record a video, push to your GitHub, or fill in a Devpost form.

---

## Where you actually are

| | |
|---|---|
| ✅ Project + Firestore | `gen-lang-client-0491046828`, Native mode, us-central1 |
| ✅ Billing linked, APIs enabled | the blocker from last week is gone |
| ✅ Deployed to Cloud Run | four production-only bugs found and fixed |
| ✅ Live fleet runs against Gemini 3.5 | 10 runs; best 8 findings, 108 citations, 100% accuracy |
| ✅ Cold-prompt test run | `FRAUD_BLIND` — 0 case-specific hits / 5 scored probes |
| ✅ 121 offline tests green | preflight 8 pass · 2 warn · 0 fail |
| ✅ Deterministic screens | forensic (XBRL) + ledger (books) + windowed retrieval |
| ✅ **Deployed, current code** | https://case-zero-7u5lvpk4ta-uc.a.run.app — verified serving today's build |
| ⚠️ Exposed Gemini API key | still live — rotate it (STEP 4) |
| ❌ Video not recorded | **the single biggest scoring risk** |
| ✅ Git repo committed | 142 files, clean, leak-checked — needs only `git remote add` + push |
| ✅ SUBMISSION.md cut | 3,375 → 1,542 words; full version kept as `SUBMISSION_FULL.md` |
| ✅ Video script + architecture diagram | rewritten against current system, timed to 4:00 |
| ❌ Repo not pushed | you add the remote — **private is allowed** (see STEP 3) |
| ❌ Not submitted | |

---

# STEP 1 — Watch the demo once, end to end (10 minutes)

**I re-verified this on Aug 19 with all guards active** — 5 verdicts fire, H-05
blocks at 0.79, one citation quarantine, tally reads
`3 ACTIVE · 1 NOT SUPPORTED BY RECORD · 1 REFUTED`. `board_blocked.png` is a
fresh screenshot of exactly that. Watch it anyway — you're about to narrate it.

```bash
python3 -m casezero.board --demo --pace 0.7
```

Open the printed URL, click **BEGIN INVESTIGATION**, and watch the right-hand
column. The moment the whole submission rests on is near the end:

> **John Fanning Sr., husband of the CFO, controls the counterparties**
> ⊘ NOT SUPPORTED BY RECORD — 79%

✅ **Check:** the tally line reads `3 ACTIVE · 1 NOT SUPPORTED BY RECORD · 1 REFUTED`.
`board_blocked.png` is what it should look like.

If that hypothesis shows as ACTIVE instead, stop and tell me — that was a real
bug (a cursor in the demo script silently ate the skeptic's verdict) and there is
now a test guarding it, but I'd rather hear it from you than assume.

---

# STEP 2 — Record the video (2–3 hours)

`VIDEO.md` is a shot-by-shot script, measured at 478 narrated words / 120 wpm
across exactly 4:00. Don't improvise — the pacing is the hard part and it's
solved.

**Redeploy first.** The live service predates the ledger and the retrieval fix.

The rules require four things in the video: **problem overview, value
proposition, live demo, and visible proof the backend runs on Google Cloud.**
The script carries all four; the first two live in the 0:20 segment, so don't
cut it.

Four beats carry the score:

1. **The cold prompt** — the model denying knowledge of the fraud in its own
   words is what makes everything after it mean something.
2. **The ledger** — `python3 -m casezero.ledger --corpus corpus`. 4.5 seconds,
   $14.58M = 87% of revenue paid in customer stock, 117× the company's own rate
   card. Say plainly that no agent found this, and that that's the point.
3. **The refusal** — the blocked hypothesis. The most shareable 20 seconds here.
4. **The scorecard, including the bad number.** 22% recovery, said out loud.

✅ **Check:** under 4:00, all four beats, and English subtitles if your audio
isn't clean.

---

# STEP 3 — Push the repo (20 minutes)

**Correction to what I told you earlier: the repo does NOT have to be public.**
The rules say "a URL to your private or public code repository" — if you keep it
private you must grant access to `testing@devpost.com` and
`cloudhackathons@google.com`. Private is the safer choice here, because your git
history would otherwise publish the API key that was pasted in chat.

Either way, **`.gitignore` already excludes the answer key
and `.env`** — verify that rather than trusting it:

**⚠ Correction #2: `.gitignore` did NOT exclude the answer key.** I told you it
did. It only had `.env`. I found it by checking, rewrote `.gitignore`, and made
the commit — so this is already done and verified:

- `complaint.pdf`, `complaint.txt`, `ground_truth.json` — excluded
- `cold_prompt_result.json`, `scorecard_*.json`, `bench_*.json`, `run_*.json` —
  **deliberately included.** They are the evidence behind every number in the
  submission, and preflight hard-FAILS without the contamination transcript. A
  repo that cites results it doesn't contain asks to be taken on trust.
- A simulated fresh clone was tested: **7 pass · 3 warn · 0 fail**, no leaks

All you need to do:

The remote is already configured and the branch is `main`. Create the empty
repo at <https://github.com/new?name=case-zero> — **no README, no .gitignore, no
licence**, or the push is rejected — then:

```bash
git push -u origin main
```

If you keep the repo private, grant `testing@devpost.com` and
`cloudhackathons@google.com`.

---

# STEP 4 — Rotate the exposed API key (5 minutes)

The Gemini key was pasted in chat, so treat it as public.

1. https://aistudio.google.com/apikey → delete the old key, create a new one.
2. Update Cloud Run:

```bash
gcloud run services update case-zero --region us-central1 \
  --update-env-vars GOOGLE_API_KEY=<new key>
```

3. Update your local `.env`.

✅ **Check:** the board still runs a live investigation after the swap.

---

# STEP 5 — Submit (30 minutes)

Everything goes into the Devpost submission form at
**https://allthingsagentichackathon.devpost.com** — that is the only place a
submission is made. Nothing is uploaded *to* Google.

| what | where it goes | notes |
|---|---|---|
| **Video** | Upload to **YouTube or Vimeo, set PUBLIC**, then paste the link into Devpost | Unlisted is not public. Max 4:00 — only the first 4:00 is judged |
| **Code** | GitHub/GitLab/Bitbucket URL in the Devpost form | Private is allowed — then grant `testing@devpost.com` and `cloudhackathons@google.com` |
| **Architecture diagram** | Committed **in the repo** (`architecture.png` / `.html`) | The rules require it in the repo, not just attached |
| **README** | In the repo | Must contain a step-by-step local setup guide |
| **Hosted demo URL** | Devpost form field | Your Cloud Run URL. "Highly encouraged", not strictly required |
| **Text description** | Devpost "About the project" field | Paste `SUBMISSION.md` |
| **Category** | **Fortified Enterprise Fleet** | One project, one prize. Pick it, don't hedge |

✅ **Check:** Devpost shows the submission as **submitted**, not draft. A draft at
5:00 PM PT on Aug 31 scores zero.

---

# STEP 6 — Afterwards

```bash
gcloud run services delete case-zero --region us-central1
```

`--min-instances=1` bills continuously. Do this once judging closes, not before —
a dead demo URL during judging is worse than a few dollars.

---

## If you only do three things

1. **Record the video.** A finished build with no video scores nothing. This is
   30% of the total and the only item with no partial credit.
2. **Redeploy, then push the repo** — after running that grep.
3. **Submit early.** Aug 29, not Aug 31. Devpost gets slow on deadline day and
   there is no appeal.

Everything else on this page is a rounding error next to those three.
