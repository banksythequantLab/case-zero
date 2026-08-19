# Devpost submission text

**Category:** Fortified Enterprise Fleet
*(One project is eligible for one prize. Pick this track and design for it — do
not hedge across categories.)*

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
is the kind of work that eats analyst-months. The obvious AI answer is retrieval:
ask questions, get answers. But that requires someone who already knows what to
ask. The actual bottleneck is the opposite. Nobody knows what happened yet.

CASE ZERO takes a corpus and one instruction — *find out what happened* — and
runs an investigation with no human in the loop.

### Why you can trust the demo

Every "AI investigates documents" demo has the same fatal flaw: the model
already knows. Enron is in every training set, so "it independently discovered
the fraud" measures recall, not investigation.

We picked a case whose *fraud* the model cannot know, and then we tested that
claim instead of asserting it.

Gemini 3.5's training data ends **January 2025**. On **August 10, 2026**, the SEC
sued Netcapital Inc. (NASDAQ: NCPL) and five individuals for overstating revenue
by 345% through sham consulting agreements. Nothing about the fraud was public
before that filing — no restatement, no non-reliance 8-K, no auditor resignation,
no press.

`cold_prompt_test.py` puts five open-ended probes to the model with no tools and
no grounding. The result, and we publish the full transcript:

**`FRAUD_BLIND` — 0 case-specific hits across 5 scored probes.** Asked directly
whether Netcapital has ever restated its financials or been accused of
misstating revenue, the model denies knowledge in 207 characters. Nothing about
the 345%, the $13.9M, the sham agreements, or the August 2026 complaint.

**But the model does know the company and its officers**, and we report that
rather than bury it. Netcapital is a public company; its executives are public.
Asked about it openly, the model volunteers John Fanning's name unprompted.

So we tested the *fraud*, not the *cast*, and we scope our claims to what the
test actually established. An investigation naming a charged individual would be
demonstrating recall. Only the accounting findings are scored.

**One more thing the probes turned up.** Asked about enforcement actions, the
model fabricated an entire case: *"SEC Civil Enforcement Action — John Fanning —
Filed September 2023 — District of Massachusetts"*, with a fact pattern and four
statute citations. It does not exist. The only Massachusetts litigation release
in that window is LR-25871, an unrelated defendant. The model invented a court,
a date, and the law — about this exact company.

That is the argument for everything downstream.

### The architecture

Four ADK `LlmAgent`s with enforced structured output:

- **Evidence** — extracts cited facts. Prioritises numbers, relationships, and
  repeated structure across supposedly independent parties.
- **Hypothesis** — forms *competing* explanations, always including an innocent one.
- **Skeptic** — opposing counsel. Graded on what it demolishes, not what it approves.
- **Lead** — reads the investigation graph and decides what runs next.

A custom `BaseAgent` orchestrator drains a priority queue. Agents create work for
other agents, so the execution topology is decided at runtime rather than wired
in. The fleet stops when the Lead agent returns no leads — not on a step count.

The live board streams the **same immutable event log** that serves as the audit
trail. One structure, two consumers: what judges watch scroll past is exactly
what an auditor reads back later.

### The result that matters

The corpus proves the revenue was not real. It never names the man behind it —
"John Fanning" appears in none of the 71 filings.

The model, however, does know him. We can prove it: the cold prompt above has it
volunteering the name unprompted, and inventing an SEC case against him that
never happened.

**So the question stops being "can it guess?" and becomes "will it refuse?"**

The Skeptic agent's `unsupported_leap` flag exists for exactly this: a claim
naming a person or entity the filings never name is blocked from the findings
regardless of how confident the fleet is. There is an offline test asserting a
hypothesis at 0.92 confidence never reaches the output when that flag is set.

The correct ceiling is:

> The customers are almost certainly under common control with an insider, the
> revenue is almost certainly not real, and the filings do not tell us who.

An agent that names him has failed, not succeeded — and because the model
demonstrably *can* name him, that is a controlled experiment in evidence
discipline rather than a lucky gap in the training data. It tests the
architecture instead of testing the calendar, and it survives a judge poking at
it, because the poking is the demo.

### The part that isn't an agent, and why

Across four documented live runs the fleet never recovered the case's central
arithmetic. A deterministic pass rebuilds it in seconds, and we think that
result is more interesting than if the fleet had gotten there.

`casezero/ledger.py` does what an accountant does: it rebuilds the customer
ledger from the filings, totals it, and reconciles it against reported revenue.
No model, no prompt, no variance.

```
RECONCILIATION vs REPORTED REVENUE
  Reported revenue, 2021-10-01 to 2024-01-31                  $16,754,071
  Settled in counterparty equity  (disclosed, 10 parties)     $11,905,000   71.1%
  Named concentration customers   (derived,    3 parties)      $2,671,099
  ─────────────────────────────────────────────────────────────────────────
  Revenue attributable to named counterparties                $14,576,099   87.0%
  Settled in arm's-length cash                                    $160,000    1.0%
  Revenue remaining once it is removed                          $2,177,972

PRICING — the same service, two prices
  Company's own published rate card     $5,000 – $10,000 engagement fee
  Arm's-length cash engagements         $40,000 – $120,000
  Equity-settled engagements            $712,500 – $2,100,000  (median $1,170,000)
  >> 117x the published price for the same service
```

**Two extraction routes, and neither is sufficient alone.** The Investments note
describes eight counterparties in dollars. The revenue-concentration tables name
three more that the note never describes, giving only a percentage. Multiply
those percentages against the revenue reported for the same window — taking the
longest window per customer, because a six-month disclosure contains the
three-month one — and the ledger closes. The union of the two routes is
**exactly the eleven Portfolio Companies the SEC charged**, with no misses.

**How close does it get?** The module never sees the complaint.

| | SEC complaint | CASE ZERO |
|---|---|---|
| Improper revenue | $13,969,013 | $14,576,099 |
| Share of reported revenue | ~77% | 87.0% |
| Counterparties | 11 | 11 recovered, 2 extra |

The entire gap is two counterparties — ScanHash and Hiveskill — that settled in
equity exactly like the others but which the SEC chose not to charge. Exclude
them and the module reports **$13,151,099 (78.5%)**: within **5.9%** of the SEC's
dollar figure and 1.5 points of its percentage, derived from nothing but filed
documents.

**The correction that mattered.** The first version of this module hunted
anomalies instead of building books, and it ranked a $50,000 figure recurring
across many customers as WEAK noise. That figure is not noise — it is the
**control group**, what arm's-length customers paid for the same service. The
whole pricing comparison above was sitting in the discard pile. An accountant
totals the ledger before hunting anomalies in it; we had that backwards.

Two smaller corrections, both measured: the association unit went from a ±300
character window (39 hits, no signal) to the paragraph, and short-form aliases
had to be harvested at their definition sites — one wrapped sentence naming two
companies by abbreviation and none in full fabricated an entire three-party
cluster on its own.

**Seeding a fact without its evidence is worse than saying nothing.** We
learned this by shipping it. The first cited version handed the fleet
`2,853,659 is tied to four counterparties` with no quote. The fleet sees 8 of 71
documents per call, went looking for the sentence, missed it, and produced this
as its single 0.95-confidence finding:

> *"Verbatim sentences containing '2,853,659' cannot be directly extracted from
> the body text of the filings."* — zero citations

The sentences are in the corpus. A whole run went into a confident report of the
fleet's own retrieval failure. Attaching the verbatim source sentence to every
seeded fact — normalised exactly as `CitationGuard` normalises the corpus, so all
31 verify — was a controlled four-run experiment:

| | uncited seed | cited seed |
|---|---|---|
| Core hypothesis confidence | 0.35 | **0.75** |
| Citations behind it | 2 | **30** |
| "cannot be extracted" finding | present at 0.95 | **gone** |

**The honest scoreboard.** `score_run.py` against the withheld complaint:

```
Ground-truth findings recovered   1 / 16   (+4 partial)
Recovery score                    18.8%
Evidence citation accuracy        100.0%  (66 citations)
Unsupported claims (hallucinated) 0 / 5
```

Both halves matter. Every calibration control — true claims the corpus cannot
support — was correctly withheld, and every citation verifies. But 18.8% is poor,
and two of the misses are instructive: the identical-amounts finding and the
pricing spread were *both seeded with verified citations* and the fleet still did
not promote them into findings. Both runs hit `budget_exhausted` with open leads,
so it never consolidates. That is a budget problem, and it is the next fix.

We report 18.8% rather than grading only the findings we seeded, because that
second number would measure the screen and call it the fleet.

**Then we raised the budget from 40 to 90 dispatches, and learned three things.**

Every run still ended `budget_exhausted`, never `lead_agent_found_nothing_further`.
Budget is not the termination problem: a planner with no notion of sufficiency
does not converge, it just runs longer.

Recovery across the three configurations went 18.8% → 12.5% → 21.9%. **That is
noise, not a trend** — n=1 per cell in a system whose run-to-run variance we
already publish as high. We are not going to draw a curve through three points.

What *did* show a consistent pattern is the failure mode. At the higher budget
the fleet finally engages with the identical-figures fingerprint — and splits it
across four overlapping hypotheses, none clearing 0.55:

| budget | separate claims about the same fingerprint | max confidence |
|---|---|---|
| 40 | 0 | — |
| 90 | 3 | 0.40 |
| 90 + guard | 4 | 0.55 |

A human analyst writes that finding once. The fleet writes it four times and
half-believes each. Confidence never accumulates because the evidence disperses
across hypotheses that never merge, and the Skeptic attacks each weakened
fragment separately. **Hypothesis consolidation is the identified next fix** —
merge near-duplicates before the Skeptic sees them — and it is not built.

### CoverageGuard: checking what the model says *isn't* there

The budget experiment surfaced a failure `CitationGuard` structurally cannot
catch. At 90 dispatches the fleet asserted:

> *"The Form 10-K filings for the fiscal years ended April 30, 2022, 2023, and
> 2024 are absent from the corpus."* — confidence 0.30, **zero citations**

Two of those three are in the corpus. The fleet sees 8 of 71 documents per call,
so more dispatches means more "I looked and didn't find it," which hardens into
stated fact — and then the Skeptic uses it to attack the true hypothesis.

`CitationGuard` verifies what the model claims *is* there. `CoverageGuard` is its
inverse: an absence claim is checked against the corpus index, for free, at
ingest. A contradicted claim is flagged and blocked from the findings, never
deleted — the assertion belongs in the audit trail.

Precision mattered more than recall. *"The details of the offerings for
CountSharp LLC are absent"* is **true** — those documents genuinely are outside
this corpus — even though CountSharp appears in eleven filings. A guard that
flagged that would be lying in exactly the way it exists to prevent. Only a
referent in the subject head is a HARD contradiction; one inside a qualifying
phrase is advisory.

**We do not claim the guard improved the score.** It fired zero times in the run
that scored best. It is a correct safety net that run did not happen to need.

### The bug underneath all of it, and the correction we owe the fleet

We then measured the context the agents were actually receiving, which we should
have done days earlier. The dispatcher sent each document as
`read()[:40000]` — the **first** 40,000 characters. SEC filings put the financial
statement notes at the **end**. In the FY2023 10-K, 320,968 characters long, the
sentence naming `2,853,659` begins at character **302,971**.

**The fleet had never seen it.** Not once, at any budget, in any run. It was
structurally incapable of reaching the central evidence in the case.

Which means this, from an earlier run, deserves a correction:

> *"Verbatim sentences containing '2,853,659' cannot be directly extracted from
> the body text of the filings because the text is truncated after Note 3."*

We logged that as a hallucination and built a guard to catch its class. **It was
not a hallucination.** It was an accurate report of the agent's own context
window, down to naming the note where truncation bit. The agent was right and we
were wrong. The lesson we would keep from this whole project: *when an agent says
it cannot find something, check your retrieval before you check its honesty.*

`casezero/passages.py` now selects **windows around matches** rather than the
head, inside the same budget, with elisions marked inline so the agent can tell
truncated text from complete text. Selectors come from the lead and from figures
already in state — `2,853,659` finds the decisive paragraph in one hop where
"revenue" matches five hundred places.

| config | budget | findings | recovery | citations | quarantined |
|---|---|---|---|---|---|
| head cut | 40 | 4 | 18.8% | 66 @ 100% | — |
| head cut | 90 | 7 | 12.5% | 56 @ 98% | — |
| head cut + guard | 90 | 8 | 21.9% | 41 @ 100% | — |
| **windowed** | **40** | **8** | **21.9%** | **108 @ 100%** | **0 of 45** |

At **half** the budget it matches the best recovery we have recorded, doubles the
findings for that budget, and produces 2.6x the citations with **zero
quarantined** — the first perfect-citation run in the project.

**And recovery still did not move beyond noise.** Four interventions — cited
seeds, coverage guard, consolidation, windowed retrieval — and recovery has
stayed in a 12.5–21.9% band throughout. Fixing retrieval made the fleet far
better *grounded* without making it better at matching the SEC's specific
findings. Whatever caps recovery at ~22% is not retrieval, and we have not
identified it. We would rather ship that sentence than a number we cannot
defend.

The discipline metrics, meanwhile, have been perfect in every scored run:
**0 of 5 calibration traps asserted, every time.**

### Built with

Gemini 3.5 Flash · Google ADK 2.7 · Cloud Run · Firestore · Vertex AI ·
OpenTelemetry → Cloud Trace · FastAPI + SSE · Python 3.12

### Data sources

- **SEC EDGAR** — 71 filings (10-K, 10-Q, 8-K, DEF 14A, S-1/A) for Netcapital
  Inc., CIK 0001414767, Jan 2021 – Jun 2024. Public, free, machine-readable.
  `fetch_corpus.py` rebuilds the corpus from scratch.
- **SEC litigation release LR-26607** and the underlying complaint — the withheld
  answer key. Never in the fleet's context.

### What we learned

**The hard filter wasn't "charged after the cutoff" — it was "became public
after the cutoff."** Almost every 2026 enforcement action concerns a fraud that
surfaced years earlier via a restatement or short-seller report, which the model
knows. That eliminated roughly twenty candidates, including some far more famous
ones. There's a structural 2–4 year lag between a fraud surfacing and the SEC
charging it, so the usable window is nearly empty by construction.

**Verifying citations at scoring time is too late.** A fabricated quote has
already propagated through the hypothesis graph and steered the investigation.
We moved verification to *ingest*: every citation is checked against the corpus
before evidence can become a hypothesis. Fabrications are quarantined where they
happen — citation stripped, DIRECT claim downgraded to INFERRED, event written to
the audit trail. Nothing is silently dropped, because "the model asserted this
without support" is itself worth recording.

The first thing that guard caught was our own mistake: a real quote attributed to
the wrong filing. Genuine quote, wrong source, and only a mechanical check found it.

**Cloud Run throttles CPU after the response returns.** Our orchestrator runs on
a background thread, so under default request-based billing it froze the instant
`POST /api/start` responded — the board showed the mission start and then nothing.
`--no-cpu-throttling` is load-bearing for this architecture, and preflight now
fails the build if that flag goes missing.

**Four things only production taught us.** The offline suite was green and the
fleet ran locally for hours before any of these appeared:

1. **Vertex AI does not serve `gemini-3.5-flash` in us-central1** for a fresh
   project — `404 Publisher model not found`. The Gemini API does. The rules
   permit either, so we ship on the API. Same model, different surface, and
   only a real deploy reveals the difference.
2. **Firestore composite indexes.** `pop_lead` filtered on `status` and ordered
   by `priority` — legal in every test double, a hard `400 The query requires an
   index` in production. We removed the dependency instead of adding the index:
   the queue holds tens of documents, so ordering in Python costs nothing and
   removes a deploy-time prerequisite. A test double cannot catch this class of
   bug, because doubles do not enforce indexes.
3. **The forensic seed was wired into the benchmark harness but not the web
   path.** Deployed, the fleet started from prose rather than arithmetic — and
   went chasing two SBA loans that happened to share a principal amount instead
   of the revenue-versus-cash gap. Same agents, same corpus, materially worse
   investigation. It is the clearest argument we have for the deterministic
   screens.
4. **Firestore persists between runs.** Without an explicit reset, every run
   accumulates onto the last, including failed ones. We added `POST /api/reset`.

None of these were visible in 121 passing offline tests. All four were found in
the first hour against a real project.

**Six agents was vanity.** We cut to four. Timeline became a field on Evidence;
Judge became the Skeptic's final pass. Four agents that genuinely disagree beat
six that politely hand off.

### What's tested, and what isn't

The orchestration loop is deliberately ADK-free — it takes a dispatch callable —
so termination, prioritisation, budget and audit behaviour are testable with zero
API calls. **121 offline tests** cover the loop, the resilience layer, the
Firestore backend and both deterministic screens, including one asserting a
high-confidence unsupported identification never reaches the findings.

The fleet runs live against Gemini 3.5. Latest run: 39 evidence objects, 4
hypotheses, **92.9% citation accuracy**, 4 fabricated quotes caught and
quarantined at ingest. The Skeptic discriminated rather than destroyed —
refuting one hypothesis 0.70 → 0.15 while letting another stand at 0.45.

Not established, and we say so rather than implying otherwise: real Firestore
service behaviour (rules, composite indexes, contention); Cloud Run deployment
under load; and the decisive arithmetic findings, which the fleet has not yet
recovered on its own. Run-to-run variance is high — one run produced the correct
core hypothesis at 0.70 and the next did not generate it at all, same corpus,
same prompts. We report that as a result, because it is one.

### Try it

```bash
pip install -r requirements.txt
python3 preflight.py                    # 10 checks
python3 -m casezero.board --demo        # scripted fleet, no API key needed
```

Demo mode is clearly labelled as scripted — the quotes in it are real and
corpus-verified, but the reasoning is canned. The submitted video is a live run.

---

## Bonus submissions (max +0.6, ~0.2 each)

Worth roughly one-tenth of one point each. Do these **only** if the build is
finished and the video is uploaded. A blog post cannot rescue a broken demo, and
time spent here is time not spent on the 70% that's actually scored.

1. **Blog post** — "Benchmarking an autonomous investigator on a case the model
   can't know." The training-cutoff method is genuinely novel and reusable; that
   is the post worth writing.
2. **Social** — #AllThingsAgenticHackathon, with the blocked-identification clip.
   That 20 seconds is the most shareable thing here.
3. **Additional Google model** — only if Gemma genuinely serves as a cheap
   first-pass triage classifier over the corpus. Do not bolt one on for 0.2;
   judges can tell, and it reads as padding.
