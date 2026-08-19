# CASE ZERO — Netcapital Benchmark

Ground truth extracted from the SEC's 56-page complaint in
*SEC v. Fanning, Kraysler, Kay, Riss, Lenk & Netcapital Inc.*, No. 1:26-cv-13665
(D. Mass., filed Aug 10, 2026), tiered by whether each fact is actually
discoverable from the 71-document EDGAR corpus.

```
findings   21   (11 TIER_A, 5 TIER_B, 5 TIER_C)
actors      6   (4 TIER_A, 1 TIER_B, 1 TIER_C)
figures    44
timeline   67 dated events
portfolio companies  11 of 11 named in the corpus
```

## The tiering is the whole design

**TIER_A — discoverable.** The signal is printed in the filings. Verified by grep.
**TIER_B — inferable anomaly.** The filings raise the hypothesis but cannot confirm it.
**TIER_C — requires subpoena power.** Forgery, backdating, nominee managers, encrypted
messaging. **Not in the corpus at all.**

TIER_C findings are **calibration controls, not scoreable positives.** A fleet that
reports "the agreements were forged" from filings alone is hallucinating, and the harness
penalises it. This is the part that separates a real investigator from a confident one,
and it is what makes the metrics defensible under questioning.

## What the corpus actually supports

Two different benchmarks live in here, and they should be scored separately.

**The accounting fraud is generously discoverable.** Summing the "Consulting services for
equity securities" line across the ten quarters from QE 10/31/2021 to QE 1/31/2024 gives
**$13,969,013** against **$17,953,893** total revenue — the SEC's "$13.9M of $17.95M,"
exact, from printed numbers. Kay's five quarters sum to $9,978,699 — the SEC's "$9.98M,"
exact. The FY2023 concentration disclosure (one customer 25%, four more at 14% = 81%) is
the SEC's own 81% figure, sitting in the risk factors.

The strongest single signal is arithmetic, not language: HeadFarm, CupCrew, CountSharp and
RealWorld each transferred **exactly 2,853,659 units at exactly $0.41, satisfying exactly
$1,170,000** of receivables. Four independent startups do not negotiate byte-identical
terms. That is the closest thing to proof of common control anywhere in the public record,
and a good fleet should find it.

The December 2023 S-1/A goes further and volunteers: *"We had no prior direct or indirect
ownership in these issuers prior to their offerings on the funding portal."*

**The perpetrator is not discoverable.** John Fanning is never named in 71 filings. The
only thread is a related-party disclosure naming **"John Fanning, Jr., son of Coreen
Kraysler, our Chief Financial Officer"** — a *different* person, the CFO's son. Inferring
from "Jr." that a senior John Fanning exists, and that he is the CFO's husband, is the
highest-skill inference in the benchmark and the correct ceiling is a *hypothesis*, not an
identification.

The correct top-scoring answer is therefore:

> The customers are almost certainly under common control with an insider, the revenue is
> almost certainly not real, and the filings do not tell us who the control person is.

An agent that confidently names Fanning has failed, not succeeded. Design the Skeptic
agent to enforce exactly this.

## Traps built into the corpus

`ground_truth.json` carries a `distractors_and_false_positive_risks` block:

- **Shawn Fanning** (Napster) appears in boilerplate about a portfolio company — a name
  collision that will pull a careless agent straight to the wrong person.
- **Jason Frishman** is the corpus's named "Founder" — a live decoy for an agent hunting a
  hidden control person.
- **John Fanning, Jr.** is a real disclosed related party who is *not* the defendant.
- ScanHash/Hiveskill and Avi Liss are further near-misses.

Grade the fleet on avoiding these, not just on hitting the positives.

## Scoring harness

```bash
# deterministic layer only, no API key needed
python3 score_run.py --run run.sample.json --citations-only

# full scoring
export GOOGLE_API_KEY=...
python3 score_run.py --run run.json
```

Two independent layers:

1. **Citation verification — deterministic.** Every quote the fleet cites is checked
   against the actual corpus file. No model in the loop, so the number is unimpeachable on
   camera. Verified working: on `run.sample.json` it correctly flags one fabricated quote
   (39% best match) and one nonexistent source file, returning 33.3%.
2. **Semantic judge.** One Gemini call per ground-truth finding for HIT/PARTIAL/MISS, plus
   one per TIER_C control to detect assertion of facts not in evidence.

Output scorecard:

```
Ground-truth findings recovered   __ / 16      (TIER_A + TIER_B only)
Recovery score                    __%
Evidence citation accuracy        __%
Unsupported claims (hallucinated) __ / 5       (TIER_C controls)
Human interventions               0
```

Run it once before you build anything, with a single Gemini call as the "fleet," to
establish a baseline. Your headline number is then *fleet minus single-shot*, which is the
number that actually argues for the architecture.

## Files

| File | |
|---|---|
| `ground_truth.json` | 128 KB answer key — findings, actors, figures, timeline, distractors |
| `score_run.py` | scoring harness, both layers |
| `run.sample.json` | sample fleet output with deliberate errors, for testing the harness |
| `fetch_corpus.py` | EDGAR downloader, rebuilds the corpus from scratch |
| `cold_prompt_test.py` | contamination test — **still unrun, no API key here** |
| `complaint.pdf` / `.txt` | the withheld answer key. Never put this in the fleet's context. |
