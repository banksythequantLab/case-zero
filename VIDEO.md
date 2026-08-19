# CASE ZERO — 4:00 demo video

Hard cap is 4:00. Over by a second and the submission is invalid, so the timings
below are a budget, not a suggestion.

**The rules require four things in this video** — problem overview, value
proposition, a live demo, and visible proof the backend runs on Google Cloud.
The first two are easy to forget when you are excited about the demo; they are
carried by the 0:20 segment, so do not cut it. English or English subtitles.

**Two rules that decide whether this lands.**

1. **Let the board run in silence.** Roughly a third of this video has no
   narration. Judges have watched a hundred people talk over their own screen
   recordings. Almost none of them stop talking and let the thing work. Silence
   is what makes it look autonomous.
2. **Disclose every cut.** The rules require a working demo, not an unedited
   one — but an undisclosed speed-up reads as a lie the moment anyone notices,
   and this project's entire pitch is honesty about what is and isn't
   established. On-screen labels, every time.

---

## The timing problem, and how to solve it honestly

**A real run takes 13½ minutes.** Measured: 807 seconds at a 40-dispatch budget,
1,788 seconds at 90. You cannot fit that in 90 seconds of video, and pretending
otherwise is the one thing that would sink this submission.

Pick one and label it on screen:

| option | how | on-screen label |
|---|---|---|
| **A — recommended** | Start it live, hands off, then hard-cut forward | `[ 11 minutes later — unedited run continues ]` |
| B | Speed-ramp the middle of the run | `4× SPEED` burned into the corner |
| C | `Budget(max_dispatches=12)` so it finishes in ~4 min | `reduced budget for runtime — full run in LIVE_RUN.md` |

A is best: the start and the finish are genuinely live, and the cut is visibly
declared. C is honest but produces a weaker investigation, so the findings you
narrate will be thinner.

---

## Shot list

### 0:00–0:20 — COLD OPEN: what the model does and doesn't know
**Screen:** terminal, full frame, large font.

```bash
python3 cold_prompt_test.py --company "Netcapital Inc." --ticker NCPL
```

Let it scroll. Land on **`FRAUD_BLIND`**.

> "Gemini three-point-five, asked about a company called Netcapital.
> It knows the company. It even names an executive, unprompted.
> Ask it about the fraud — nothing. Its training ends January twenty
> twenty-five. The S-E-C only sued this month.
> It knows the cast. It does not know the crime."

*Why first: "the model already knew" is the first objection any judge forms.
Don't overclaim it away — show the split. Claiming total blindness invites
someone to disprove it in one prompt. Showing exactly what it knows and what it
doesn't is unfalsifiable, because it's just true.*

---

### 0:20–0:40 — THE SETUP
**Screen:** the board at standby. Click **BEGIN INVESTIGATION**.

> "Document investigation eats analyst-months, and the hard part isn't answering
> questions — it's not knowing which to ask.
> Seventy-one real S-E-C filings. One instruction: find out what happened.
> The S-E-C's complaint is the answer key. It is not in the system.
> I start it, then I don't touch anything."

Click. **Take your hands off the keyboard, visibly.**

---

### 0:40–1:15 — THE PART THAT ISN'T AN AGENT
**Screen:** split — board still streaming on one side, a terminal on the other:

```bash
python3 -m casezero.ledger --corpus corpus
```

Four and a half seconds. Let the reconciliation land on screen.

> "Before any model runs, arithmetic does.
> This rebuilds the customer ledger straight from the filings.
> Fourteen and a half million dollars of revenue — eighty-seven percent of
> everything reported — settled not in cash but in the customers' own stock.
> The company's published price for this service is five to ten thousand dollars.
> These clients were billed a median of one-point-one-seven million.
> A hundred and seventeen times the rate card."

*Beat. Then:*

> "No model. No prompt. No variance. Arithmetic has one right answer, so it
> doesn't get an agent."

*This is the strongest thirty-five seconds in the video. The numbers are exact,
they're derived from public filings, and the module never sees the complaint —
yet it lands within six percent of the S-E-C's figure and recovers all eleven
companies the S-E-C charged. Do not rush it.*

---

### 1:15–2:10 — LET IT RUN
**Screen:** the board. Event stream left, hypotheses right. **Insert your
disclosed time cut here.**

**Narrate only what actually happens.** This is a live run and it varies —
across ten logged runs these are the reliable beats:

Non-cash revenue (reliable, expect it early):
> "Evidence agent. Revenue is almost entirely non-cash — paid in the customers'
> own shares."

Competing explanations appearing side by side (reliable, and the point):
> "Two readings of the same numbers, both alive at once. The innocent one is
> there because an agent is required to build it."

The Skeptic moving confidence (reliable):
> "The skeptic exists to attack the other agents' theories, not to agree with
> them."

A citation quarantine (**less likely now** — the last run quarantined zero of
forty-five; if it happens, take it):
> "An agent cited a quote that isn't in the corpus. Caught at ingest, before it
> could become a hypothesis."

Then **stop talking** until 2:10.

---

### 2:10–2:45 — THE PUNCHLINE
**Screen:** the blocked hypothesis card. Then cut briefly back to the cold-prompt
transcript from the opening.

> "Now the part that matters. The fleet worked out that an insider related to the
> C-F-O controls these customers. It cannot name him. That name is in none of the
> seventy-one filings.
>
> But the model knows him."

*(cut to the cold prompt — the name, volunteered)*

> "It named him in three seconds. It also invented an S-E-C case against him that
> never happened.
>
> The fleet still won't say it. Not because it can't. Because the record doesn't
> support it."

*This is the whole submission. The model can produce the answer; the
architecture stops it. That's a controlled experiment, not a lucky gap in a
training set. Hold the card on screen for a full beat.*

---

### 2:45–3:10 — IT RUNS ON GOOGLE CLOUD
**Screen:** hard cuts between tabs, ~6 seconds each. Required by the rules.

1. **Cloud Run console** — service page, URL visible, green check
2. **Logs tail** — `gcloud run services logs tail case-zero` scrolling live
3. **Firestore console** — `cases/0001/events`, the audit trail persisted

> "Cloud Run, with C-P-U always allocated — the fleet runs on a background
> thread, so under default billing it would freeze the moment the request
> returned. Firestore holds the investigation graph.
> The event stream you just watched is the same immutable log an auditor reads
> back. One structure, two consumers."

**⚠ Before you record this segment:** the deployed service must be running
*current* code. See the checklist below — this is the one item most likely to
embarrass you on camera.

---

### 3:10–3:33 — THE SCORECARD, INCLUDING WHAT IT DOESN'T DO
**Screen:** `python3 score_run.py --run run.json`

> "Scored against the S-E-C's own complaint.
> A hundred and eight citations, every one verified — deterministically, no
> model in the loop.
> Five calibration traps: true claims the filings can't support. It asserted
> none, in every run we've scored.
> Findings recovered: twenty-two percent. That's not good, and we publish it
> anyway."

*Say the weak number out loud. A judge who finds it themselves after you hid it
discounts everything else you said; a judge who hears you volunteer it trusts
the rest. The readiness score rewards exactly this.*

---

### 3:33–4:00 — CLOSE
**Screen:** back to the board, complete.

> "One run reported it couldn't find a figure in the filings.
> We logged that as a hallucination.
> It wasn't. We were feeding it the first forty thousand characters of documents
> where the evidence sat at character three hundred thousand.
> The agent was right. We were wrong.
>
> When an agent says it can't find something — check your retrieval before you
> check its honesty."

Hold two seconds. End.

*Ending on the correction rather than a boast is deliberate. Every other
submission ends on a claim. This one ends on a bug the team found in itself,
which is the most credible thing anyone can say in a production-readiness
category.*

---

## Pre-flight for the recording

**Do these in order. The first two are the ones that actually bite.**

- [ ] **Redeploy before recording.** The deployed service predates the ledger,
      the windowed retrieval, and both guards. A judge clicking your demo URL
      must not get the old build. `./deploy.sh`, then load the URL and confirm
      the board shows a `LEDGER RECONCILED` event on start.
- [ ] **Write the service URL down.** It is a submission field and it is
      currently recorded nowhere in this repo.
- [ ] `python3 preflight.py` — target 8 pass / 2 warn / 0 fail
- [ ] `python3 -m casezero.ledger --corpus corpus` — confirm it prints the
      reconciliation and the 117× line
- [ ] Live mode, real API key. **Not `--demo`.**
- [ ] Full dry run, timed end to end, so you know where your cut goes
- [ ] `cold_prompt_result.json` open in a tab — if a judge asks, the transcript
      is the answer
- [ ] Browser zoom so text is legible at 720p. Judges watch small.
- [ ] Cloud Run + Firestore tabs pre-opened and pre-authenticated
- [ ] Hide bookmarks, notifications, anything with a personal name in it
- [ ] Total runtime **under 4:00**. Check before upload.
- [ ] Upload **public** on YouTube or Vimeo. Unlisted is not public.

## If the live run misbehaves on camera

Narrate it, don't hide it. *"That agent just timed out — the orchestrator logged
it and reassigned the lead."* A fleet visibly surviving a failure is a better
demo than one that never hits a bump, and the architecture is built for exactly
that.

The two things you cannot do: present demo mode as a live run, or make an
undisclosed cut.
