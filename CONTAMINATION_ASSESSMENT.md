# Contamination test — result and what it actually means

**Ran:** 2026-08-18 · `gemini-3.5-flash` · 5 scored probes, 2 diagnostic
**Final verdict:** `FRAUD_BLIND` · identity `KNOWN` · **0 fraud hits / 5 scored probes**
Preflight now passes with 0 failures.

Getting here took three runs, and the two false starts are worth recording
because they are the same mistake in different clothes — measuring the probe
instead of the model.

* **Run 1 — "CONTAMINATED", 8 hits.** Three hits were `netcapital advisors` and
  `portfolio compan`: the company's own publicly disclosed business model,
  described in its filings since 2021. Flagging those measures nothing.
* **Run 2 — "CONTAMINATED", 3 hits.** One was *"a material misstatement of the
  company's financial statements"* — boilerplate from the definition of a
  material weakness. The other two were the model echoing the probe's own words
  (*"restated"*, *"misstating"*) back **inside its denial**. The test was
  scoring the model for repeating the question.
* **Run 3 — `FRAUD_BLIND`.** Flags now require case-specific phrasing, and any
  match inside a denial sentence is discarded. Zero hits.

---

## What the model genuinely knows (real, public before Jan 2025)

| Fact | Status |
|---|---|
| Netcapital is an equity-crowdfunding company | real, public |
| Netcapital Advisors takes **equity instead of cash** for services | real, public |
| Those clients are called **"portfolio companies"** | real, public |
| **John Fanning** is co-founder / former chairman | real, public |
| **Cecilia Lenk** is an executive | real, public |
| Recurring going-concern warnings | real, public |

Three of the eight "hits" were `netcapital advisors` and `portfolio compan` —
the company's own publicly disclosed business model, described in its filings
since 2021. Those are false positives and I should not have scored them.

## What the model does NOT know — the fraud itself

The most direct probe — *"has Netcapital ever restated its financials, been
accused of misstating revenue, or faced securities litigation?"* — returned a
**flat denial in 207 characters**. No hedging, no partial recall.

Nothing anywhere in the transcript about: the 345% overstatement, the ~$13.9M,
sham or backdated consulting agreements, forged signatures, the identical
2,853,659-unit transfers, or the August 2026 complaint.

**The accounting-fraud benchmark is intact.**

## What the model HALLUCINATES — and this is the important part

Asked about enforcement actions, the model produced a detailed, confident,
entirely fabricated case:

> "SEC Civil Enforcement Action — Individual Charged: **John Fanning** — Date
> Filed: **September 2023** — Court: District of Massachusetts — the SEC alleged
> that from at least 2018 through 2021, John Fanning engaged in a fraudulent
> scheme to sell unregistered shares... charged with violating Sections 5 and
> 17(a) of the Securities Act, and Section 10(b) and Rule 10b-5..."

**This case does not exist.** I checked. The only September 2023 Massachusetts
litigation release in that range is [LR-25871](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-25871),
which is *John Feloni / Stock Squirrel* — a different person, a different
company, unrelated facts. No pre-2026 SEC action against John Fanning regarding
Netcapital exists in the litigation-release record.

The model invented a court, a date, a fact pattern and four statute citations.
(It also asserts a May 2023 FINRA action against the funding portal — I have not
verified that one either way; treat it as unconfirmed.)

---

## So what breaks

**The perpetrator half of the benchmark is dead.** The pitch was "John Fanning
appears in none of the 71 filings, so the fleet cannot name him." That is still
true of the *corpus* — but it is no longer true of the *model*. Gemini already
associates Fanning with Netcapital, and already associates him with securities
fraud. If the fleet outputs his name, that is parametric recall dressed up as
inference, and any judge who runs this same cold prompt will see it immediately.

Do not ship the claim "it independently identified the family connection."

**The accounting half survives cleanly**, and that is the larger half: 11 TIER_A
findings, the arithmetic that reconstructs the SEC's own $13.9M / $17.95M split,
the identical-terms fingerprint, the concentration disclosure.

---

## The reframe that turns this into an asset

The original story was *"the fleet can't name him, because the corpus doesn't."*
The available story is stronger:

> **The model knows the answer. We can prove it knows — here is the cold prompt
> where it volunteers Fanning unprompted, and here is it inventing an SEC case
> that never happened. The fleet still refuses to name him, because the corpus
> doesn't support it.**

That is a controlled experiment in evidence discipline rather than a lucky gap in
the training data. It tests the architecture instead of testing the calendar —
and it is robust to a judge poking at it, because the poking *is* the demo.

The hallucinated September 2023 case becomes the single best argument for the
whole design: this is a model that will confabulate a detailed, plausible,
citation-bearing enforcement action about this exact company. The CitationGuard
and the Skeptic are the reason that never reaches a finding.

## Cost of the run

7 calls, ~24k output tokens, roughly $0.11. Free-tier limits were not a factor.
