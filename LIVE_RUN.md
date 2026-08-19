# Live fleet runs — what actually happened

Four runs against real `gemini-3.5-flash`. ~30 minutes of wall clock, roughly
$3 of tokens. Every number below is from a real run, not a projection.

## Bugs the live runs found (none were visible offline)

**1. `KeyError: 'Tier'` — died on the very first call.**
The batch schemas were hand-built dicts wrapping `Model.model_json_schema()`.
That puts pydantic's `$defs` at the *inner* schema's top level while the
google-genai transformer resolves `$ref` against the *outer* one, so the enum
definition was unreachable. Fixed by declaring real pydantic wrapper models
(`EvidenceBatch`, etc.) so refs and defs stay at the same level.

**2. The Lead agent never advanced the investigation.**
Run 1: 14 consecutive evidence dispatches, **38 evidence objects, zero
hypotheses**, budget gone. An LLM planner keeps gathering, because gathering
always looks defensible and committing to a claim does not. Fixed with a
starvation guard in the orchestrator — if a downstream stage is starved while
its input is plentiful, the scheduler injects the lead itself and logs it as an
intervention. Liveness is a scheduler's job, not a prompt's.

**3. Document selection was feeding the fleet the wrong half of the corpus.**
`names[:docs_per_call]` — and filenames are date-prefixed, so slicing the front
returns only the *oldest* filings. Across three runs the fleet never once saw
the FY2023 10-K, which is where the decisive numbers are. Replaced with
relevance scoring against the lead's question plus an even stride across the
remaining period. This was the most damaging bug and the least visible.

**4. The Skeptic refuted everything.**
Run 3 ended with **zero surviving findings** — every hypothesis marked
`unsupported_leap`, including the innocent explanation. The flag was written
broadly ("anything the corpus cannot establish") and the model read it as
licence for general doubt. Narrowed to its actual purpose: naming a person or
entity the filings never name, or asserting a specific unrecorded act.
Refuting everything is as useless as approving everything.

Also fixed: Lead out-ran its own workers (30 open leads), now capped at 3 per
call with drops logged.

## Final run

```
569s · 39 evidence · 4 hypotheses · 2 verdicts · 127 audit events
citation accuracy 92.9%  (51 exact, 1 fuzzy, 4 quarantined)
```

Findings that survived the Skeptic, with graded confidence:

| conf | finding |
|---|---|
| 0.70 | Zelgor Inc. was a major source of non-cash equity-based consulting revenue |
| 0.45 | the income/cash divergence is an innocent consequence of the business model |
| 0.25 | four named entities acted as sources of non-cash revenue |

And it discriminated rather than destroyed: **H1 refuted 0.70 → 0.15**, **H2
survived at 0.45**, no spurious `unsupported_leap`. That is the behaviour the
architecture is supposed to produce.

## What is still not right

- **Budget-bound.** All four runs ended `budget_exhausted` with ~29 open leads.
  The fleet has never yet run to its own natural stopping point.
- **Run-to-run variance is high.** Run 2 produced the correct core hypothesis
  ("artificially inflated revenues through non-cash related-party transactions")
  at 0.70. Run 4 did not generate it at all. Same corpus, same prompts.
- **The decisive TIER_A findings have not been recovered yet** — not the
  $13,969,013 sum, not the 2,853,659-unit fingerprint. The fleet is finding
  genuine related-party structure but not yet the arithmetic that proves it.
- **Citation accuracy is 92.9%, not 100%.** Four fabricated quotes across the
  run, all caught and quarantined at ingest. Working as designed, but it means
  roughly one in fourteen citations from this model is invented.

## Next, in order

1. Raise the budget to ~60 dispatches and let one run reach its own terminus.
2. Seed the Lead agent with the arithmetic question directly — "sum the
   equity-consulting line across all ten quarters" — rather than hoping it
   derives the idea.
3. Run 3–5 times and report the distribution. A single run is an anecdote, and
   the variance above is itself an honest, interesting result.
4. Only then score against `ground_truth.json`.

---

# Production deployment — Cloud Run, 2026-08-18

Deployed to Cloud Run in project `gen-lang-client-0491046828`. Four failures the
offline suite could never have caught, in the order they appeared:

### 1. Vertex AI 404
```
Publisher model projects/.../locations/us-central1/publishers/google/models/gemini-3.5-flash
was not found or your project does not have access to it.
```
`deploy.sh` set `GOOGLE_GENAI_USE_VERTEXAI=True`, so the container authenticated
to Vertex. But every local run — four benchmark suites — used the **Gemini API**.
Different surface, different per-region model availability, and Vertex had never
been exercised. Fixed by dropping the Vertex flag and passing `GOOGLE_API_KEY`.
The rules permit either.

Worth noting: `retry_with_backoff` did **not** retry the 404. A 404 is
deterministic and would fail identically forever. The retry policy made the
right call unprompted.

### 2. Firestore composite index
```
400 The query requires an index.
```
`pop_lead` did `where(status == "open").order_by("priority", DESC)`. Every test
double accepts that; real Firestore demands a hand-built composite index. Fixed
by removing the ordering from the query and sorting in Python — the queue holds
tens of documents, so it costs nothing and removes a deploy-time prerequisite.

**A test double cannot catch this**, and the README said so before the deploy:
"catches API-shape bugs but NOT composite-index requirements." That caveat was
written blind and turned out to name the exact failure.

### 3. The forensic seed was missing from the web path
`api_start()` called `loop.run(mission)` without `seed_evidence`. The benchmark
harness passed it; the deployed service did not.

The consequence is the best evidence for the whole design. Without the seed the
fleet started from prose, latched onto the first concrete anomaly it found —
**two SBA loans sharing a principal of $1,885,800** — and spent the run there. A
real anomaly, and entirely beside the point. With the seed it opens holding
"net income $2.95M against operating cash flow of −$4.6M, a gap of 89% of
revenue" as computed fact.

Same agents, same corpus, same prompts. Materially worse investigation.

### 4. Firestore state accumulates
No reset meant every run piled onto the previous one, failed attempts included.
After four attempts the board showed 110 evidence objects that were the union of
everything. Added `POST /api/reset`.

## What ran well

Before the seed fix, on the old build, the fleet still produced:

- Zelgor Inc. identified as a related-party customer via its controlling shareholder
- The CFO's personal guarantee of a $500,000 obligation
- **Identical prepaid stock-compensation figures across two supposedly
  independent consultants** — structurally the same signal as the identical-terms
  fingerprint in the ground truth
- Netcapital Systems LLC's majority ownership

19 verdicts issued. The Skeptic drove `hypo_sba_loans_duplicate` to **0.0** and
`hypo_consultant_clerical_error` to **0.02** — killing its own theories on
production data, unprompted.


---

# The citation experiment (Aug 19)

A controlled comparison, four live runs, same corpus, same prompts, same budget.
The only variable: whether the deterministic ledger seed shipped the **source
sentence** for each fact it asserted.

## What went wrong without citations

The ledger handed the fleet `2,853,659 is tied to four counterparties` and no
quote. The fleet is only shown 8 of 71 documents per call, so it went looking for
the sentence, did not find it in its sample, and concluded:

> *"Verbatim sentences containing '2,853,659' or '2,856,659' cannot be directly
> extracted from the body text of the filings in the corpus because the text is
> truncated after Note 3."* — confidence **0.95**, **zero citations**

That is false. The sentences are in the corpus. An entire run was spent producing
a confident finding about the fleet's own retrieval failure.

The other run got the right answer but discounted it, and the Skeptic invented an
innocent explanation for the fingerprint precisely because it could not see the
source: *"the matching figures... are the result of clerical XBRL tagging errors."*

## The fix

`ledger.quote_span()` captures the verbatim sentence around every extracted fact.
Whitespace is normalised the same way `CitationGuard` normalises the corpus, so
the quotes verify exactly. **31/31 emitted citations verify against the corpus.**

## Measured effect

| | uncited seed | cited seed |
|---|---|---|
| Core hypothesis confidence | **0.35** | **0.75** |
| Citations behind it | 2 | **30** |
| "cannot be extracted" meta-finding | present, 0.95 | **gone** |
| Findings per run | 1.5 | 2.5 |
| Citation accuracy | 95.4% | 96.0% |

The lesson generalises past this project: **a deterministic screen that asserts a
fact without its evidence is worse than one that says nothing.** It does not just
fail to help — it sends the fleet on a verification errand it cannot complete,
and the fleet reports the failed errand as a finding.

## Scored against the withheld complaint

`score_run.py`, run against real fleet output for the first time:

```
Ground-truth findings recovered   1 / 16   (+4 partial)
Recovery score                    18.8%
Evidence citation accuracy        100.0%  (66 citations)
Unsupported claims (hallucinated) 0 / 5
Human interventions               0
```

**Read both halves.** The discipline result is as good as it can be: all five
calibration controls — claims that are true but not supported anywhere in the
corpus — were correctly withheld, and every citation in the output verifies.

The recovery result is poor, and two of the misses are damning in a useful way.
**F03** (four startups paying byte-identical amounts) and **F05** (portfolio
companies charged 10x-50x the going rate) were *both* seeded, with verified
citations, at the start of the run. The fleet had them handed over and did not
promote either into a finding.

Why: both runs ended `budget_exhausted` at 40 dispatches with open leads
remaining. The fleet has still never reached its own natural stopping point, so
it never consolidates. That is the next thing to fix, and it is a budget problem
rather than a reasoning one.

We report 18.8% rather than the number we would get by grading only what we
seeded, because the second number would measure the screen and call it the fleet.


---

# The budget experiment (Aug 19)

We raised the dispatch budget from 40 to 90, expecting the fleet to finally reach
its own stopping point. It did not, and the result is more interesting than
success would have been.

| config | findings | recovery | citations | traps asserted | stop reason |
|---|---|---|---|---|---|
| 40, cited seed | 4 | 18.8% | 100% | 0/5 | `budget_exhausted` |
| 90, no coverage guard | 7 | 12.5% | 98% | 0/5 | `budget_exhausted` |
| 90 + coverage guard | 8 | **21.9%** | 100% | 0/5 | `budget_exhausted` |

**Read the recovery column as noise, not a trend.** Three runs, n=1 per cell, in
a system whose run-to-run variance we have already measured as high. 18.8 → 12.5
→ 21.9 is not a curve. Anyone reporting the third number as an improvement over
the second is reading tea leaves, and we are not going to.

Three things the experiment did establish.

## 1. Budget is not the termination problem

Every run at both budgets ended `budget_exhausted`, never
`lead_agent_found_nothing_further`. More than doubling the allowance bought 30
minutes and did not bring the fleet one step closer to deciding it was finished.
The Lead agent will generate leads indefinitely; a planner with no notion of
sufficiency does not converge, it just runs.

## 2. The fleet fragments instead of consolidating

This is the clearest structural finding, and it tracks budget monotonically:

| config | separate claims about the identical-figures fingerprint | max confidence |
|---|---|---|
| budget 40 | 0 | — |
| budget 90 | 3 | 0.40 |
| budget 90 + guard | 4 | 0.55 |

At the higher budget the fleet *does* engage with the fingerprint — and then
splits it across three or four overlapping hypotheses, none of which clears 0.55:

> *"The identical valuations of $1,170,000 and nearly identical unit counts..."* — 0.55
> *"The crowdfunding campaigns for HeadFarm LLC... had an implied..."* — 0.50
> *"The repeating unit counts of 2,853,659 and 2,856,659 and the flat $1,170,000..."* — 0.35
> *"The identical figures of 2,856,659 units and $1,170,000 valuations..."* — 0.20

A human analyst writes that once. The fleet writes it four times and believes
each version a little. Confidence never accumulates because the evidence is
spread across four hypotheses that never merge, and the Skeptic attacks each
weakened fragment separately.

**Identified next fix: hypothesis consolidation.** Merge near-duplicate claims
before the Skeptic sees them, so evidence pools instead of dispersing. This is
the single highest-value change we know of and it is not built.

## 3. A new failure mode, and a mechanical check for it

At budget 90 without a guard the fleet asserted:

> *"The Form 10-K filings for the fiscal years ended April 30, 2022, 2023, and
> 2024 are absent from the corpus."* — confidence 0.30, **0 citations**

`2022-08-08_10-K_000497.txt` and `2023-07-26_10-K_000560.txt` are in the corpus.
The fleet sees 8 of 71 documents per call, so with more dispatches it accumulates
more "I looked and did not find it" and eventually states absence as fact — then
the Skeptic uses that to attack the true hypothesis.

`CitationGuard` cannot catch this. It verifies what the model says IS there; it
has nothing to say about what the model claims ISN'T. So `CoverageGuard` is the
inverse: an absence claim is checked against the corpus index, which is free.

Precision mattered more than recall here. *"The details of the offerings for
CountSharp LLC are absent"* is **true** — those documents really are outside this
corpus — even though CountSharp appears in eleven filings. A guard that flagged
that would be lying in exactly the way it exists to prevent. So only a referent
in the subject head yields a HARD contradiction; one inside a qualifying phrase
is SOFT and advisory. On the budget-90 run that split four absence claims into
two genuinely false (HARD, both about Form 10-K) and two defensible (SOFT).

**We are not claiming the guard caused the 21.9%.** It fired zero times in that
run. It is a correct safety net that this particular run did not need, and the
run scored well for reasons we cannot isolate at n=1. Reporting it as the cause
would be the same overreach the whole project is built to refuse.


---

# The head-cut bug (Aug 19) — the one that explains the rest

We found it by measuring context rather than behaviour, which we should have
done days earlier.

The dispatcher sent each selected document to the agent as
`open(f).read()[:char_cap]` — **the first 40,000 characters**. SEC filings put
the financial statement notes at the END. In the FY2023 10-K, a 320,968-character
document, the sentence

> *"In April 2023, the Company received 2,853,659 units of HeadFarm LLC as a
> payment for services rendered..."*

begins at character **302,971**.

**The fleet had never seen it.** Not in one run, not at budget 40, not at budget
90, not once across every live run in this file. It was structurally incapable of
reaching the central evidence in the case.

Relevance selection had the same defect from the other end: documents were ranked
by matching the query against `read(8000)`, so a filing was judged on its
letterhead rather than its contents.

Even reading all 71 documents, a 40,000-character head cut exposes only **20.7%**
of the corpus — and systematically the wrong 20.7%, since it is the front matter
of every filing.

## The correction we owe the fleet

Two days ago a run produced this as its single 0.95-confidence finding:

> *"Verbatim sentences containing '2,853,659' cannot be directly extracted from
> the body text of the filings in the corpus because the text is truncated after
> Note 3."*

We logged it as a hallucination and built `CoverageGuard` to catch its class.
**It was not a hallucination.** It was an accurate report of the agent's own
context window, down to naming the note where the truncation bit. The agent was
right and we were wrong, and we only found out by instrumenting the retrieval we
had never questioned.

The guard is still correct — the *documents* were in the corpus, so "absent from
the corpus" was a false statement — but the complaint underneath it was
legitimate. The lesson worth keeping: **when an agent says it cannot find
something, check your retrieval before you check its honesty.**

## The fix

`casezero/passages.py` selects **windows around matches** instead of the head,
within the same character budget, with elisions marked inline so the agent can
tell truncated text from complete text. Selectors are drawn from the lead
question and from figures already in the investigation state — a figure like
2,853,659 locates the decisive paragraph in one hop where "revenue" matches five
hundred places.

Same 40,000-character budget on the FY2023 10-K:

| | head cut | windowed |
|---|---|---|
| `2,853,659` present | ✗ | ✓ |
| `1,170,000` present | ✗ | ✓ |
| `HeadFarm LLC` present | — | ✓ |
| chars used | 40,000 | 40,000 |

## Measured effect, at HALF the budget

| config | budget | findings | recovery | citations | quarantined |
|---|---|---|---|---|---|
| head cut, cited seed | 40 | 4 | 18.8% | 66 @ 100% | — |
| head cut | 90 | 7 | 12.5% | 56 @ 98% | — |
| head cut + coverage guard | 90 | 8 | 21.9% | 41 @ 100% | — |
| head cut + coverage + consolidation | 90 | 2 | 18.8% | 43 @ 100% | — |
| **windowed passages** | **40** | **8** | **21.9%** | **108 @ 100%** | **0 of 45** |

At **half** the budget the windowed run matches the best recovery we have ever
recorded, doubles the findings for that budget, and produces **2.6x the
citations with not one quarantined** — the first perfect-citation run in the
project.

**Recovery did not move beyond noise.** It sits at ~22%, same as the best
head-cut run. That is worth stating plainly: fixing retrieval made the fleet
dramatically better *grounded* — more findings, far more citations, zero
fabrications — without making it better at matching the SEC's specific findings.
Whatever caps recovery at ~22% is not retrieval, and we have not identified it.

Four interventions now — cited seeds, coverage guard, consolidation, windowed
passages — and recovery has stayed in an 12.5-21.9% band throughout. The
discipline metrics, by contrast, have been perfect in every single scored run:
**0 of 5 calibration traps asserted, every time.**
