# Benchmarking an autonomous investigator on a case the model can't know

Every "AI investigates documents" demo has the same hole in it, and once you see
it you can't unsee it: **the model already knows the answer.**

Point an agent at the Enron filings and watch it "independently discover" the
special purpose entities. It didn't discover anything. Enron is in every training
set on earth. What you measured was recall, dressed up as investigation.

So we built a benchmark where that's impossible, pointed an autonomous agent
fleet at it, and published what happened — including the parts that make us look
bad, of which there are several.

---

## The hard filter isn't "recent." It's "never was public."

The obvious move is to find an SEC enforcement action filed after the model's
training cutoff. Gemini 3.5's data ends January 2025, so anything charged in 2026
qualifies, right?

No. And this is the part that eliminated about twenty candidates.

There is a structural 2–4 year lag between a fraud *surfacing* and the SEC
*charging* it. By the time a complaint is filed, the story has usually been
public for years — a restatement, a non-reliance 8-K, an auditor resignation, a
short-seller report. The model knows all of that. The complaint is new; the fraud
isn't.

What you actually need is a case where **nothing was public before the complaint
dropped.** No restatement. No 8-K. No press. That is a much smaller set, and it
is nearly empty by construction.

We found one. On **August 10, 2026** the SEC sued Netcapital Inc. (NASDAQ: NCPL)
for overstating revenue by 345% through sham consulting agreements. Nothing about
it had ever been disclosed. The corpus is 71 real EDGAR filings from 2021–2024 —
all public, all pre-cutoff, all available to anyone. The complaint is the answer
key, and it never enters the system.

---

## Test the blindness. Don't assert it.

Here's where most benchmark write-ups quietly cheat: they claim the model is
blind and move on.

We ran five open-ended probes at the model with no tools and no grounding, and
published the full transcript. The verdict was `FRAUD_BLIND` — **zero
case-specific hits across five scored probes.** Asked directly whether Netcapital
had ever restated its financials or been accused of misstating revenue, it denied
knowledge in 207 characters.

**But it knows the company, and it knows the officers.** Netcapital is public;
its executives are public. Asked openly, the model volunteers the CFO's spouse by
name, unprompted.

We report that instead of burying it, for a boring reason: claiming *total*
blindness invites a judge to disprove you with one prompt. Showing exactly what
the model knows and what it doesn't is unfalsifiable, because it's just true. So
the fraud is blind, the cast is not, and only the accounting findings get scored.

One more thing the probes turned up, which we did not expect. Asked about
enforcement actions, the model fabricated an entire case:

> *"SEC Civil Enforcement Action — [name redacted] — Filed September 2023 —
> District of Massachusetts"*

with a fact pattern and four statute citations. It does not exist. The only
Massachusetts litigation release in that window involves an unrelated defendant.
The model invented a court, a date, and the law — about this exact company.

*(We redact the name here. It's a real person in a real enforcement action, and
the sentence around it is a fabrication. Republishing an invented legal claim
against a named individual would be a strange thing to do in a post about
evidence discipline.)*

That single hallucination is the argument for everything downstream.

---

## The interesting question isn't "can it guess?" It's "will it refuse?"

The corpus proves the revenue wasn't real. It never names the man behind it —
that name appears in **none of the 71 filings.** The only thread is a
related-party disclosure naming his *son*, plus two live traps: an unrelated
famous person with the same surname in boilerplate, and a different executive
publicly titled "Founder."

The model can produce the right name in three seconds. We proved that above.

So the correct output isn't the name. It's:

> The customers are almost certainly under common control with an insider, the
> revenue is almost certainly not real, and the filings do not tell us who.

A fleet that confidently names him has **failed**, not succeeded — and because
the model demonstrably *can* name him, that's a controlled experiment in evidence
discipline rather than a lucky gap in a training set. A Skeptic agent blocks any
claim naming a person the filings never name, regardless of confidence. There's
an offline test asserting a hypothesis at 0.92 confidence never reaches the
output when that flag is set.

**Result: across five scored runs, zero of five calibration traps were ever
asserted.** Not once.

---

## Arithmetic doesn't get an agent

Here's the finding we didn't expect to be the headline.

Across ten live runs, the fleet never recovered the case's central arithmetic. A
deterministic pass rebuilds it in 4.5 seconds:

```
Reported revenue, 2021-10 to 2024-01                        $16,754,071
Settled in counterparty equity  (disclosed, 10 parties)     $11,905,000   71.1%
Named concentration customers   (derived,    3 parties)      $2,671,099
────────────────────────────────────────────────────────────────────────
Revenue attributable to named counterparties                $14,576,099   87.0%

Company's own published rate card    $5,000 – $10,000 engagement fee
Equity-settled engagements           $712,500 – $2,100,000
>> 117x the published price for the same service
```

Two extraction routes, and neither is sufficient alone: the Investments note
describes eight counterparties in dollars, while the revenue-concentration tables
name three more that the note never describes, giving only a percentage. Multiply
those percentages against the revenue reported for the same window and the ledger
closes. **The union of the two routes is exactly the eleven companies the SEC
charged**, with no misses.

Never having seen the complaint, the module lands within **5.9%** of the SEC's
dollar figure.

No model. No prompt. No variance. This class of check has exactly one right
answer, and the same fleet whose hypotheses reproduced 1 run in 3 has no business
computing it. **Knowing which questions to refuse to ask a model is architecture,
not laziness.**

---

## The bug that explains everything else

We spent two days chasing why recovery was stuck at ~18%. We tried four things:
citing the seeded evidence, a guard for false absence claims, hypothesis
consolidation, and more budget. Nothing moved it.

Then we measured the context the agents were actually receiving.

The dispatcher was sending each document as `read()[:40000]` — **the first**
40,000 characters. SEC filings put the financial statement notes at the **end**.
In the FY2023 10-K, a 320,968-character document, the sentence naming the
decisive figure begins at character **302,971**.

The fleet had never seen it. Not once, at any budget, in any run. It was
structurally incapable of reaching the central evidence in the case.

Which means an earlier run deserves a correction. It had reported, at 0.95
confidence:

> *"Verbatim sentences containing '2,853,659' cannot be directly extracted from
> the body text of the filings because the text is truncated after Note 3."*

We logged that as a hallucination and built a guard to catch its class. **It was
not a hallucination.** It was an accurate report of the agent's own context
window, down to naming the note where truncation bit. The agent was right and we
were wrong.

**When an agent says it can't find something, check your retrieval before you
check its honesty.**

Switching to relevance-windowed excerpts — same character budget, windows around
matches instead of the head, elisions marked inline so the agent can tell
truncated text from complete text — doubled the findings at *half* the budget and
produced 108 citations with zero quarantined.

---

## The honest scoreboard

```
Ground-truth findings recovered   2 / 16   (+3 partial)
Recovery score                    21.9%
Evidence citation accuracy        100.0%  (108 citations)
Unsupported claims (hallucinated) 0 / 5
Human interventions               0
```

Both halves matter, so here are both.

The discipline result is as good as it can be: every calibration control was
correctly withheld in every scored run, and every citation verifies
deterministically against the corpus.

The recovery result is poor. 21.9% is not good, and we publish it rather than a
number we can't defend. Four interventions and recovery stayed in a 12.5–21.9%
band throughout. Fixing retrieval made the fleet dramatically better *grounded*
without making it better at matching the SEC's specific findings. **Whatever caps
it at ~22% is not retrieval, and we have not identified it.**

We also got things wrong along the way and think that's worth writing down:

- **We thought the fleet was fragmenting** one finding across several weak
  hypotheses. Built the merge, then measured: across 56 hypothesis pairs from six
  runs, **zero merged.** They were competing *stances* — the fraud reading, the
  innocent reading, the arithmetic reading — not duplicates. Merging them would
  have deleted the disagreement the architecture exists to create, while
  improving every metric we track.
- **We thought more budget would help.** Going from 40 to 90 dispatches *lowered*
  recovery and never once reached a natural stopping point. It's a termination
  problem, not a budget one.
- **The citation guard caught our own error** before it caught the model's — a
  real quote attributed to the wrong filing.

---

## The method is the reusable part

You can run this on any company. The recipe:

1. Find an enforcement action where **nothing was public before the complaint**,
   not merely one filed after the cutoff.
2. Build the corpus from pre-complaint public filings only.
3. **Probe the model cold and publish the transcript.** Report what it *does*
   know, not just what it doesn't.
4. Score against the complaint, and include **calibration controls** — true
   claims the corpus cannot support. Asserting one counts against the system, not
   for it.
5. Put the arithmetic in code, and say so.
6. Publish the number that embarrasses you.

That last one isn't moralising. A judge who finds your weak number after you hid
it discounts everything else you said. A judge who hears you volunteer it trusts
the rest.

---

*Code, corpus, full transcripts and every scored run are in the repository. The
answer key is deliberately excluded — the Dockerfile asserts it is absent from
the serving image, and the build fails if that assertion is removed.*
