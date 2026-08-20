# Handoff prompt — paste this into the Claude running on Johnson

Everything below is self-contained. The receiving Claude has no memory of the
cloud session that produced this, so it states facts rather than referring back.

---

I'm Derek Soltis. You have Desktop Commander / Windows CLI and access to my local
drives. A separate Claude session in the cloud built this project but cannot
reach my machine, so the remaining work is yours.

## The project

**CASE ZERO** — an autonomous agent fleet that investigates SEC filings with no
human in the loop. It's my submission to the **All Things Agentic Hackathon**
(Google/Devpost). **Deadline: August 31 2026, 5:00 PM Pacific.** Category:
Fortified Enterprise Fleet.

The benchmark: 71 real EDGAR filings for Netcapital Inc. (NCPL), and a real SEC
enforcement action filed **after** the model's training cutoff, with the SEC's
complaint held out as the answer key. The fleet gets the filings and one
instruction — *find out what happened*.

## What already exists

| | |
|---|---|
| **Live deployment** | https://case-zero-7u5lvpk4ta-uc.a.run.app |
| **GCP project** | `gen-lang-client-0491046828` / us-central1 |
| **GitHub** | `banksythequantlab/case-zero` (may not be pushed yet) |
| **Code archive** | `casezero-aug19.tgz` in my Downloads — 11,855,573 bytes |
| **Voice cloning** | `B:\freeclone-backend\SKILL.md` |
| **Tests** | 121 offline, all passing |

The archive contains a git repo with commits and the remote already configured.
**Extract it with `tar`, not 7-Zip or Explorer** — those silently drop `.git` and
`.gitignore`, which already cost me an afternoon.

## What I need you to do, in priority order

### 1 · Record the 4-minute demo video (this is 30% of the score)

`VIDEO.md` in the archive is a shot-by-shot script, measured at 478 narrated
words across exactly 4:00. Don't rewrite it; it's timed.

The rules require four things in the video: **problem overview, value
proposition, a live application demo, and visible proof the backend runs on
Google Cloud.** Max 4:00 — only the first four minutes are judged, so an overrun
silently truncates the ending. English audio or English subtitles.

Four segments:

- **0:00–0:20** cold open — `cold_prompt_test.py` output, lands on `FRAUD_BLIND`
- **0:40–1:15** the deterministic ledger — **already shot**, use
  `ledger_segment.mp4` from the archive (8s, 1920×1080)
- **1:15–2:45** the live board at the URL above, then the blocked hypothesis card
- **2:45–3:10** Cloud Run console, `gcloud run services logs tail case-zero`,
  and the Firestore console showing `cases/0001/events`

**A real run takes 13½ minutes.** You cannot fit that in the slot. Start it live,
hands off, then hard-cut with an on-screen label reading
`[ 11 minutes later — unedited run continues ]`. **Never make an undisclosed
cut**, and never present demo mode as a live run — the entire pitch of this
project is honesty about what is and isn't established, and a judge who catches
a fake discounts everything else.

Reset the board before recording so the demo doesn't start mid-investigation:

```
curl -s -X POST "https://case-zero-7u5lvpk4ta-uc.a.run.app/api/reset"
```

### 2 · Generate the narration with my voice clone

Read `B:\freeclone-backend\SKILL.md` and use that setup. The archive has a
`narration/` folder: eight plain-text files, one per segment, already stripped of
markdown and with every figure written the way it should be spoken.

Generate **one clip per file** — not one long render — so a clip that runs long
can be regenerated alone. Targets:

```
01 → 20s    02 → 20s    03 → 35s    04 → 55s
05 → 35s    06 → 25s    07 → 23s    08 → 27s
```

Two notes. **Segment 4 is deliberately sparse** (75 wpm over 55s) — that's the
board running in silence, which is what makes it read as autonomous; do not pad
it. **Segment 3 is tightest** at 146 wpm — if my cloned voice runs slower than
the source this is the one that overruns; trim "No model. No prompt. No
variance." to "No model, no variance" and regenerate just that clip.

### 3 · Push the repo

The archive's git repo has the remote set to
`https://github.com/banksythequantlab/case-zero.git` on branch `main`.

Create the empty repo first at <https://github.com/new?name=case-zero> with
**nothing** ticked — no README, no .gitignore, no licence, or the push is
rejected as a non-fast-forward. Then `git push -u origin main`. Username is
`banksythequantlab`; the password field takes a fine-grained PAT with
**Contents: Read and write**, not my account password.

Private is fine and is the safer choice. If private, grant `testing@devpost.com`
and `cloudhackathons@google.com`.

**Before any `git add -A`, verify nothing sensitive is staged:**

```
git status --short | Select-String -Pattern 'complaint|ground_truth|\.env$'
```

That must print nothing. `complaint.pdf`, `complaint.txt` and `ground_truth.json`
are the withheld answer key and must never reach the repo — the whole benchmark
claim rests on them staying out.

### 4 · Submit on Devpost

<https://allthingsagentichackathon.devpost.com>

- **Video** → upload to YouTube or Vimeo, set **public** (unlisted is not
  public), paste the link
- **Code** → the GitHub URL
- **Hosted project** → https://case-zero-7u5lvpk4ta-uc.a.run.app
- **About the project** → paste `SUBMISSION.md` from the archive
- **Category** → Fortified Enterprise Fleet (one project, one prize — don't hedge)

Optional +0.2: `BLOG_POST.md` in the archive is ready to publish on any public
platform; paste that link too.

## House rules that matter here

- **Don't fake anything.** If a run fails on camera, narrate it — a fleet
  visibly surviving a failure is a better demo than one that never stumbles.
- **Don't claim something was done that wasn't tested.** Tell me what's
  incomplete rather than papering over it.
- **Don't take control of the mouse or a shared app without asking first.**
- The submission deliberately publishes an unflattering number (21.9% recovery).
  That's intentional — don't "fix" it in any copy you touch.

## Afterwards

Once judging closes:

```
gcloud run services delete case-zero --region us-central1
```

`--min-instances=1` bills continuously. Not before judging — a dead demo URL is
worse than a few dollars.

Also rotate the Gemini API key at <https://aistudio.google.com/apikey>; the
current one was pasted in chat and should be treated as public. Swapping it is
one command, no redeploy:

```
gcloud run services update case-zero --region us-central1 --update-env-vars GOOGLE_API_KEY=<new key>
```

## Start by telling me

1. Whether you can read `B:\freeclone-backend\SKILL.md`
2. Whether the archive extracted with `.git` and `.gitignore` intact
3. Which of the four tasks you want to take first

Don't begin recording until you've confirmed 1 and 2.
