# Devpost submission text

**Category:** Fortified Enterprise Fleet
*(One project is eligible for one prize. Pick this track and design for it — do
not hedge.)*

> The long-form version, with every measurement and every failed experiment
> written up, is in **`SUBMISSION_FULL.md`** and **`LIVE_RUN.md`**. This file is
> what goes in the Devpost box — judges skim, and the good material was buried.

---

## Elevator pitch (200 char limit)

> Give an autonomous agent fleet a data room and one question. Walk away. It
> investigates, argues with itself, and refuses to conclude what the evidence
> can't support.

*(165 characters — verified.)*

---

## About the project

### The problem

Document investigation — securities fraud, internal investigations, e-discovery —
eats analyst-months. The obvious AI answer is retrieval: ask questions, get
answers. But that needs someone who already knows what to ask. The real
bottleneck is the opposite. Nobody knows what happened yet.

CASE ZERO takes a corpus and one instruction — *find out what happened* — and
runs an investigation with no human in the loop.

### Why you can trust the demo

Every "AI investigates documents" demo has the same flaw: the model already
knows. Enron is in every training set, so "it independently discovered the fraud"
measures recall, not investigation.

We picked a case whose *fraud* the model cannot know, then tested that claim
instead of asserting it.

Gemini 3.5's training ends **January 2025**. On **August 10, 2026** the SEC sued
Netcapital Inc. (NASDAQ: NCPL) for overstating revenue by 345% through sham
consulting agreements. Nothing about it was public before that filing — no
restatement, no non-reliance 8-K, no auditor resignation, no press.

`cold_prompt_test.py` puts five open-ended probes to the model with no tools and
no grounding. Full transcript committed as `cold_prompt_result.json`:

**`FRAUD_BLIND` — 0 case-specific hits across 5 scored probes.** Asked directly
whether Netcapital ever restated or was accused of misstating revenue, it denies
knowledge in 207 characters.

**But it does know the company and its officers**, and we report that rather than
bury it. Asked openly, it volunteers John Fanning's name unprompted. So we tested
the *fraud*, not the *cast*, and only the accounting findings are scored.

**One more thing the probes turned up.** Asked about enforcement actions, the
model fabricated an entire case: *"SEC Civil Enforcement Action — John Fanning —
Filed September 2023 — District of Massachusetts"*, with a fact pattern and four
statute citations. It does not exist. That is the argument for everything
downstream.

### The architecture

Four ADK `LlmAgent`s with enforced structured output — **Evidence** (extracts
cited facts), **Hypothesis** (competing explanations, always including an
innocent one), **Skeptic** (opposing counsel, graded on what it demolishes),
**Lead** (decides what runs next).

A custom `BaseAgent` orchestrator drains a priority queue. Agents create work for
other agents, so the topology is decided at runtime rather than wired in.

The live board streams the **same immutable event log** that serves as the audit
trail. One structure, two consumers: what judges watch scroll past is exactly
what an auditor reads back later.

### The result that matters

The corpus proves the revenue was not real. It never names the man behind it —
"John Fanning" appears in none of the 71 filings.

The model, however, does know him. **So the question stops being "can it guess?"
and becomes "will it refuse?"**

The Skeptic's `unsupported_leap` flag blocks any claim naming a person the
filings never name, regardless of confidence. There is an offline test asserting
a hypothesis at 0.92 confidence never reaches the output when that flag is set.

An agent that names him has failed, not succeeded — and because the model
demonstrably *can* name him, that is a controlled experiment in evidence
discipline rather than a lucky gap in the training data.

### The part that isn't an agent

Across ten live runs the fleet never recovered the case's central arithmetic. A
deterministic pass rebuilds it in 4.5 seconds.

`casezero/ledger.py` does what an accountant does: rebuilds the customer ledger
from the filings, totals it, reconciles it against reported revenue.

```
Reported revenue, 2021-10-01 to 2024-01-31                  $16,754,071
Settled in counterparty equity  (disclosed, 10 parties)     $11,905,000   71.1%
Named concentration customers   (derived,    3 parties)      $2,671,099
──────────────────────────────────────────────────────────────────────────
Revenue attributable to named counterparties                $14,576,099   87.0%

Company's own published rate card     $5,000 – $10,000 engagement fee
Equity-settled engagements            $712,500 – $2,100,000
>> 117x the published price for the same service
```

Two extraction routes, neither sufficient alone: the Investments note gives eight
counterparties in dollars, the concentration tables name three more as
percentages only. Their union is **exactly the eleven Portfolio Companies the SEC
charged**, with no misses.

**How close, never having seen the complaint?** SEC: $13,969,013 / ~77%. Module:
$14,576,099 / 87%. The entire gap is two counterparties that settled in equity
identically but which the SEC chose not to charge. Exclude them:
**$13,151,099 (78.5%) — within 5.9% of the SEC's figure**, from filed documents
alone.

No model, no prompt, no variance. Arithmetic has one right answer, so it doesn't
get an agent.

### The bug underneath everything, and a correction we owe the fleet

The dispatcher sent each document as `read()[:40000]` — the **first** 40,000
characters. SEC filings put the financial notes at the **end**. In the FY2023
10-K, 320,968 characters long, the sentence naming `2,853,659` begins at
character **302,971**.

**The fleet had never seen it.** Not once, at any budget, in any run.

Which means this, from an earlier run, needs a correction:

> *"Verbatim sentences containing '2,853,659' cannot be directly extracted from
> the body text of the filings because the text is truncated after Note 3."*

We logged that as a hallucination and built a guard to catch its class. **It was
not a hallucination.** It was an accurate report of the agent's own context
window, down to naming the note where truncation bit. The agent was right and we
were wrong.

**When an agent says it can't find something, check your retrieval before you
check its honesty.**

`casezero/passages.py` now selects windows around matches, same budget, elisions
marked inline. At **half** the budget it doubled the findings and produced 108
citations with zero quarantined — the first perfect-citation run in the project.

### The honest scoreboard

```
Ground-truth findings recovered   2 / 16   (+3 partial)
Recovery score                    21.9%
Evidence citation accuracy        100.0%  (108 citations)
Unsupported claims (hallucinated) 0 / 5
Human interventions               0
```

Both halves matter. Every calibration control — true claims the corpus cannot
support — was correctly withheld, in **all five scored runs**. Every citation
verifies.

But 21.9% is poor, and we publish it rather than a number we can't defend. We
tried four interventions — cited seeds, a coverage guard, hypothesis
consolidation, windowed retrieval — and recovery stayed in a 12.5–21.9% band
throughout. **Whatever caps it at ~22% is not retrieval, and we have not
identified it.**

### What we got wrong, and how we know

- **We thought the fleet was fragmenting** one finding across several weak
  hypotheses. Built the merge, then measured: across 56 hypothesis pairs from six
  runs, **zero merge.** They were competing stances, not duplicates. Merging them
  would have deleted the disagreement the architecture exists to create — and
  would have improved every metric we track while doing it.
- **We thought more budget would help.** 40 → 90 dispatches *lowered* recovery
  and never once reached a natural stopping point. It is a termination problem,
  not a budget one.
- **The citation guard caught our own error** — a real quote attributed to the
  10-K when it appears in the DEF 14A.

### Production lessons only a real deploy taught us

1. **Vertex AI does not serve `gemini-3.5-flash` in us-central1** for a fresh
   project — `404 Publisher model not found`. The Gemini API does.
2. **Firestore composite indexes.** `pop_lead` filtered on `status` and ordered
   by `priority` — legal in every test double, a hard `400` in production. We
   removed the dependency rather than adding the index.
3. **Cloud Run throttles CPU after the response returns.** Our orchestrator runs
   on a background thread, so it froze the instant `POST /api/start` responded.
   `--no-cpu-throttling` is load-bearing, and preflight fails the build without it.
4. **Firestore persists between runs**, so every run piled onto the last. Added
   `POST /api/reset`.

None were visible in the offline suite. All four surfaced in the first hour
against a real project.

### Built with

Gemini 3.5 Flash · Google ADK 2.7 · Cloud Run · Firestore · OpenTelemetry →
Cloud Trace · FastAPI + SSE · Python 3.12

### Data sources

- **SEC EDGAR** — 71 filings (10-K, 10-Q, 8-K, DEF 14A, S-1/A) for Netcapital
  Inc., CIK 0001414767, Jan 2021 – Jun 2024. Public, free, machine-readable.
  `fetch_corpus.py` rebuilds the corpus from scratch.
- **SEC litigation release LR-26607** and the underlying complaint — the withheld
  answer key, never in the fleet's context and deliberately not in the repo.

### Try it

```bash
pip install -r requirements.txt
python3 preflight.py                      # 10 checks, no credentials needed
python3 -m casezero.ledger --corpus corpus   # the deterministic pass, 4.5s
python3 -m casezero.board --demo          # scripted fleet, no API key
```

**121 offline tests** cover the loop, the resilience layer, the Firestore
backend, both deterministic screens and the retrieval fix — including one
asserting a high-confidence unsupported identification never reaches the
findings, and one asserting a fraud hypothesis is never merged into the innocent
explanation of the same facts.

Demo mode is clearly labelled as scripted — its quotes are real and
corpus-verified, but the reasoning is canned. The submitted video is a live run.
