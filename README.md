# CASE ZERO

An autonomous investigation fleet. Give it a corpus of SEC filings and one
instruction — *find out what happened* — and walk away.

It is scored against a benchmark it cannot game: a real SEC enforcement action
filed **after** the model's training cutoff, with the SEC's own complaint held
out as the answer key.

```
Corpus      71 real EDGAR filings, Netcapital Inc. (NCPL), 2021-01 → 2024-06
Answer key  SEC v. Fanning et al., D. Mass., filed 2026-08-10 — never in context
Blindness   Gemini 3.5 cutoff is January 2025. The case did not exist publicly.
Cost        $1.19 per full pass · $0.12 cached
Humans      0
```

## Why the case is blind

The usual objection to "AI investigates documents" demos is that the model
already knows the answer. Enron is in every training set. This corpus is not:
the fraud was never disclosed before the SEC sued on **August 10, 2026** — no
restatement, no non-reliance 8-K, no auditor resignation, no press. The model's
training data ends in January 2025.

Verify it yourself before trusting any of this:

```bash
export GOOGLE_API_KEY=...
python3 cold_prompt_test.py --company "Netcapital Inc." --ticker NCPL
```

Five probes, red-flag grep, CLEAN or CONTAMINATED. **Result: `FRAUD_BLIND`** —
0 case-specific hits across 5 scored probes; asked directly whether Netcapital
ever restated or was accused of misstating revenue, the model denies knowledge in
207 characters. It *does* know the company and its officers, and volunteers John
Fanning's name unprompted — so the fraud is blind, the cast is not, and only the
accounting findings are scored. `CONTAMINATION_ASSESSMENT.md` has the full
transcript. Run it again on camera as the opening beat of the demo.

## A note on the answer key

`complaint.pdf`, `complaint.txt` and `ground_truth.json` are **deliberately not in
this repo.** The whole benchmark claim is that the SEC's complaint never enters
the fleet's context; `.dockerignore` asserts it is absent from the serving image
and `preflight.py` fails the build if that assertion is removed. Keeping it out
of the repo is a second surface for the same guarantee.

Consequence: a fresh clone shows `warn — ground_truth.json missing, scoring
unavailable`, and `score_run.py` will not run. **That warning is expected.**
Everything else — the corpus, the deterministic screens, all 121 tests, demo
mode — works from a clean clone with no credentials at all.

The complaint is a public SEC document (`comp26607.pdf` on sec.gov), so this is
not secrecy. It is keeping the answer key and the system visibly separate. Every
result that key produced *is* committed: `cold_prompt_result.json`,
`scorecard_*.json`, `bench_*.json` and `run_*.json` are all here, so every number
in `SUBMISSION.md` and `LIVE_RUN.md` can be checked against the run that produced
it.

## The honest ceiling

The corpus proves the revenue was not real. It never names the man behind it.

"John Fanning" appears in **none of the 71 filings**. The only thread is a
related-party disclosure naming *"John Fanning, Jr., son of Coreen Kraysler, our
Chief Financial Officer"* — a different person. The corpus also contains live
traps: **Shawn Fanning** (Napster) appears in boilerplate, and **Jason Frishman**
is the named "Founder."

So the top-scoring answer is:

> The customers are almost certainly under common control with an insider, the
> revenue is almost certainly not real, and the filings do not tell us who the
> control person is.

A fleet that confidently names Fanning has **failed**, not succeeded. The
Skeptic agent enforces this and `score_run.py` penalises it. That is the whole
design: an investigator that knows the limit of its evidence.

## Architecture

`architecture.html` renders the full diagram. In short:

Four ADK `LlmAgent`s with enforced structured output — **Evidence** (extracts
cited facts), **Hypothesis** (competing explanations, always including an
innocent one), **Skeptic** (opposing counsel), **Lead** (decides what runs next).
A custom `BaseAgent` orchestrator drains a priority queue. Agents create work for
other agents; the execution topology is decided at runtime, not built in. The
fleet stops when Lead returns no leads — not on a step count.

Cut from six agents to four: Timeline is a field on Evidence, Judge is the
Skeptic's final pass. Four agents that genuinely disagree beat six that politely
hand off.

## Verified vs unverified

Be clear about this in the submission — the readiness score rewards honesty
about the boundary.

| | |
|---|---|
| ✅ Corpus fetched and measured | 71 docs, 6,341,092 chars, 1,585,273 tokens |
| ✅ Ground truth extracted | 21 findings, corpus-grepped and tiered |
| ✅ Loop logic tested | 14/14 offline tests, no API calls |
| ✅ Resilience layer tested | 12/12 — JSON extraction, schema repair, backoff, citation + coverage guards |
| ✅ Forensic screens tested | 6/6 — accruals, Beneish, derived-quarter timeline |
| ✅ Ledger screen tested | 43/43 — register, reconciliation, pricing, citations, corpus regressions |
| ✅ ADK agents construct | against real `google-adk` 2.7.1 |
| ✅ Board runs end to end | demo mode and live mode |
| ✅ Firestore backend | 7/7 against an in-memory Firestore double |
| ✅ Preflight | 10 checks, exits non-zero on blockers |
| ✅ Citation layer tested | catches fabricated quote (39%) and bad file |
| ✅ Cold-prompt test | run: `FRAUD_BLIND`, 0 case-specific hits across 5 scored probes |
| ✅ Live Gemini dispatch | 10 documented runs; best: 8 findings, 108 citations, 0 quarantined, 100% accuracy |
| ✅ Cloud Run deploy | deployed and debugged; four production-only bugs found and fixed |
| ✅ Firestore *service* behaviour | composite-index requirement hit for real, and designed out |
| ✅ Scored against the withheld complaint | 5 runs, 12.5–21.9% recovery · **0/5 traps asserted in every one** |
| ✅ Retrieval reaches the decisive evidence | fixed: was `read()[:40000]`, and the key sentence sits at char 302,971 |
| ⚠️ Fleet recovers the arithmetic unaided | it does not. The ledger reconciles to within 5.9% of the SEC's figure |
| ❌ Fleet reaches its own stopping point | it does not, at budget 40 **or** 90 — this is a termination problem, not a budget one |
| ⚠️ Hypothesis consolidation | built and tested; fires **0 times** on real output — the fragmentation diagnosis was wrong |
| ❌ What caps recovery at ~22% | unknown. Four interventions did not move it. Not retrieval |
| ⚠️ Run-to-run variance | high: 1 of 3 runs reproduced the core hypothesis |

## Resilience: what breaks when you point this at a real model

Five failure modes cost more build time than the agents themselves. All five are
handled in `casezero/resilience.py` and tested offline:

1. **Model returns prose, or JSON in markdown fences, or JSON with a preamble.**
   `extract_json` handles 10 real-world response shapes including nested braces,
   braces inside strings, escaped quotes, and trailing commas.
2. **JSON parses but violates the schema.** `repair_loop` feeds the *actual*
   validation error back and asks for a correction, rather than throwing away an
   expensive call.
3. **API rate-limits or 5xxs.** `retry_with_backoff` uses exponential backoff
   with jitter — and deliberately does **not** retry a deterministic 400, which
   will fail identically every time.
4. **The model fabricates a quote.** `CitationGuard` checks every citation
   against the corpus **at ingest**, before evidence can become a hypothesis.
5. **The model asserts something is ABSENT that is present.** `CoverageGuard` is
   the inverse check. At a 90-dispatch budget the fleet claimed the FY2022 and
   FY2023 10-Ks were missing from the corpus; both are in it. Absence is
   checkable against the corpus index for free, so it is never taken on trust.

> **The correction that taught us the most.** An earlier run reported *"verbatim
> sentences containing 2,853,659 cannot be extracted... the text is truncated
> after Note 3."* We logged it as a hallucination and built the guard above. It
> was not a hallucination — the dispatcher was sending `read()[:40000]` and that
> sentence sits at character 302,971. The agent was describing its own context
> window accurately, and we were the ones who were wrong. **When an agent says it
> cannot find something, check your retrieval before you check its honesty.**

(4) is the one that matters architecturally. Verifying citations only at scoring
time means a fabricated quote has already propagated through the hypothesis
graph and shaped the investigation. Checking at ingest quarantines the
hallucination where it happens — the citation is stripped, a DIRECT claim is
downgraded to INFERRED, an `integrity_flag` is set, and a `citation_quarantine`
event hits the audit trail. Nothing is silently dropped: "the model asserted this
without support" is itself a finding worth keeping.

The demo run includes one deliberate fabrication so you can watch the guard catch
it live. Leave it in. A fleet that can be *seen* catching its own hallucination is
worth more than one that claims it never has them.

> While wiring this up the guard caught a citation error I had made myself — I
> attributed a real quote to the 10-K when it actually appears in the DEF 14A.
> That is the failure mode in miniature: the quote was genuine, the attribution
> was not, and only a mechanical check found it.

## Quick start

Step by step, from a clean checkout.

**1. Prerequisites** — Python 3.11+, and a Gemini API key from
<https://aistudio.google.com/apikey>. No Google Cloud account is needed to run
locally; only the deploy step needs one.

**2. Install**

```bash
git clone <this repo> && cd case_zero
pip install -r requirements.txt
```

**3. Configure** — copy the template and paste your key in:

```bash
cp .env.example .env      # then edit .env and set GOOGLE_API_KEY=...
```

**4. Verify the install** — no API key needed for any of these:

```bash
python3 preflight.py                      # 10 checks; target 8 pass / 2 warn / 0 fail
python3 -m casezero.ledger --corpus corpus   # the deterministic pass, ~5 seconds
python3 -m casezero.board --demo          # scripted fleet, open the printed URL
```

**5. Run the real thing** (needs the key, ~13 minutes, ~$1.20 of tokens):

```bash
set -a && . ./.env && set +a
python3 -m casezero.board                 # live fleet, open the printed URL
```

## Everything else

```bash

# offline: loop logic, no API key, no GCP
python3 tests/test_loop.py

# the deterministic accountant's pass — rebuilds the customer ledger and
# reconciles it against reported revenue. No API key, ~5 seconds.
python3 -m casezero.ledger --corpus corpus

# rebuild the corpus from EDGAR
python3 fetch_corpus.py --cik 1414767 --start 2021-01-01 --end 2024-06-30

# score a run — deterministic layer needs no key
python3 score_run.py --run run.sample.json --citations-only
python3 score_run.py --run run.json            # full, needs GOOGLE_API_KEY
```

## Deploy

```bash
python3 preflight.py          # 10 checks; exits non-zero on a blocker
export GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=us-central1
./deploy.sh                   # deployed; see DEPLOY_RUNBOOK.md for what broke
```

Two things here will cost you a day each if you meet them the hard way.

**`--no-cpu-throttling` is not optional.** Under Cloud Run's default
request-based billing, CPU is allocated *only while a request is being
processed*. `POST /api/start` returns immediately and the investigation
continues on a background thread — precisely the work that gets frozen the
instant the response is sent. The board would show the mission start and then
nothing, and it would look like the fleet hung. `--min-instances=1` keeps the
in-flight investigation from being scaled to zero mid-run.

**The answer key never enters the image.** The Dockerfile copies the corpus and
nothing else; `complaint.pdf`, `complaint.txt` and `ground_truth.json` are all
excluded, and the build asserts their absence. Scoring is a separate step run
after the fleet stops. If the answer key is not in the container, "did the
agents peek?" stops being a question anyone has to take on trust.

`max-instances=1` is deliberate too: `pop_lead()` is read-then-update, not
transactional, so two orchestrators would claim the same lead. Better a
constraint you chose than a bug you shipped.

For an ADK-native deploy instead, `adk deploy cloud_run --trace_to_cloud
--otel_to_cloud` gives the OpenTelemetry observability the track asks for
essentially free — but check the CPU allocation flag either way.

## Establish a baseline first

Before building anything, run the harness with a **single Gemini call** as the
"fleet." Your headline number is then *fleet minus single-shot*. That is the
number that argues for the architecture rather than for Gemini.

## Layout

```
casezero/
  schemas.py        Evidence / Hypothesis / Verdict / Lead + JSON schemas
  state.py          MemoryStore (tested) + FirestoreStore (untested), audit log
  agents.py         the four agents — the prompts are the product
  orchestrator.py   InvestigationLoop (ADK-free, testable) + ADK dispatch layer
  resilience.py     JSON extraction, schema repair, backoff, CitationGuard
  board.py          Mission Control — FastAPI + SSE, demo mode included
  forensic.py       XBRL screens — accruals divergence, Beneish, derived quarters
  ledger.py         the books — engagement register, reconciliation, pricing
  passages.py       relevance windows — the notes are at the END of a filing
  consolidate.py    same-stance duplicate merge (guard; never fires in practice)
tests/test_loop.py        14 offline tests — loop, budget, audit, blocking
tests/test_passages.py    19 offline tests — windowed retrieval, head-cut regression
tests/test_consolidate.py 20 offline tests — stance gate, merge safety
tests/test_resilience.py  12 offline tests — parsing, repair, retry, quarantine, coverage
tests/test_firestore.py    7 offline tests — Firestore backend via a test double
tests/test_forensic.py     6 offline tests — accruals, Beneish, timeline derivation
tests/test_ledger.py      43 offline tests — register, reconciliation, pricing, citations
board.html          the live investigation board
Dockerfile          serving image — corpus in, answer key out
deploy.sh           Cloud Run deploy (unrun)
preflight.py        pre-deploy and pre-demo checks
corpus/             71 EDGAR filings + manifest
ground_truth.json   the answer key, tiered
score_run.py        two-layer scoring harness
fetch_corpus.py     EDGAR downloader
cold_prompt_test.py contamination test — RUN THIS FIRST
architecture.html   architecture diagram
BENCHMARK.md        benchmark design and what the corpus supports
CANDIDATES.md       why this case, and the ~20 that failed
complaint.pdf/.txt  the withheld answer key — never put this in the fleet's context
```
