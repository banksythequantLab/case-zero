# CASE ZERO — Blind Case Candidates

**Design:** feed the fleet a public company's *contemporaneous* SEC filings. Withhold the
SEC's enforcement complaint — that is the answer key, written by the SEC, not by us.
Gemini 3.5's training cutoff is **January 2025**, so any matter whose facts first became
public after that date is blind by construction. No corpus is built; it is downloaded.

**The hard filter is not "charged after Jan 2025" — it is "first became public after Jan 2025."**
Most 2026 enforcement actions concern frauds that surfaced in 2021–2024, which the model
already knows. That single distinction eliminated ~20 otherwise-plausible cases.

---

## PRIMARY — Netcapital Inc. (NASDAQ: NCPL) ✅

| | |
|---|---|
| **Action** | SEC v. Fanning, Kraysler, Riss, Kay, Lenk & Netcapital Inc. (D. Mass.) |
| **Release** | [LR-26607](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26607) · [Complaint PDF](https://www.sec.gov/files/litigation/complaints/2026/comp26607.pdf) |
| **Filed** | **August 10, 2026** — seven days ago |
| **Fraud period** | October 2021 – January 2024 (ten consecutive quarters) |
| **Allegation** | ~$13.9M of consulting revenue recognized against ~$4.05M of legitimate revenue — a **345% overstatement** — from eleven sham/backdated agreements with "Portfolio Companies" secretly controlled by John Fanning, an undisclosed de facto officer married to CFO Coreen Kraysler. At least four agreements bore forged signatures. ~$5.1M booked in quarters before any agreement existed. Related-party status never disclosed. |
| **First public** | **Aug 10, 2026 — the complaint itself.** No restatement, no Item 4.02 non-reliance 8-K, no auditor resignation, no short-seller report, no accounting press coverage. The July 29, 2026 NT 10-K cited only "additional time to complete supporting documentation." |
| **Profile** | Nano-cap. Coverage limited to trade press (Reuters, Bloomberg Law, InvestmentNews) — all after Aug 10, 2026. |

**Corpus — verified, downloaded, measured:**

```
DOCUMENTS      71   (10-K ×3, 10-Q ×9, 8-K ×40, DEF 14A ×4, S-1/S-1A ×15)
WINDOW         2021-01-01 → 2024-06-30
CHARACTERS     6,341,092
EST. TOKENS    1,585,273
COST / PASS    $1.19    (Gemini 3.5 Flash input @ $0.75/M)
CACHED READ    $0.12    (@ $0.075/M)
```

At $1.19 a pass you can run this **125 times inside the $150 credit** — and with context
caching, effectively without limit. The corpus is small enough to iterate on all day and
large enough that no human reads it in a demo slot.

**Why the fraud is findable from filings alone** — these are the signals a competent fleet
should surface, and they are your scoring rubric:

1. Revenue overwhelmingly **non-cash** — paid in equity of the portfolio companies
2. Extreme **customer concentration** in those same entities
3. **Spousal relationship** between Fanning and the CFO, traceable through proxies
4. Fanning acting as an **undisclosed officer** while not listed as one
5. **Fair-value marks** on received equity that move suspiciously
6. Revenue recognized in quarters **predating** the agreements that supposedly generated it

Six ground-truth findings. That is your metrics table, and every one is checkable against
the complaint.

---

## SECONDARY — RYVYL, Inc. (NASDAQ: RVYL, f/k/a GreenBox POS) ⚠️

[LR-26541](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26541) · filed Apr 27, 2026 · CIK 0001419275

Claimed proprietary blockchain "settlement engine" that never processed a transaction;
concealed that its principal product was sold almost exclusively to cannabis dispensaries.
The concealed concentration first surfaced in RYVYL's **May 20, 2025** filing — after the
cutoff.

**Caveat:** RYVYL restated its 2022 interim financials in **January 2023**, triggering class
actions. The *charged conduct* is post-cutoff but the *company* has pre-cutoff accounting
baggage. Use as a harder second case only, and disclose the caveat.

---

## Rejected (do not re-research)

| Company | Why |
|---|---|
| **Archer-Daniels-Midland** | Segment-reporting issue public Jan 2024. Also a household name. |
| **AMMO / Outdoor Holding** | Great fact pattern, but Sept 2024 8-K disclosed the investigation. |
| **Lottery.com** | Surfaced Jul 2022. |
| **Near Intelligence** | Non-reliance Oct 2023; company defunct, EDGAR incomplete. |
| **Key Tronic** | Surfaced Feb 2021; books-and-records only, no fraud charge. |
| **Elanco** | Channel-stuffing allegations back to 2020. |
| **FAT Brands** | Probe disclosed 2021. |
| **Spero Therapeutics** | Surfaced May 2022; disclosure, not accounting. |
| **GrubMarket** | Private — no EDGAR periodic reports. |
| **Compass Diversified (CODI)** | Ideal timing (surfaced May 2025) but **no SEC action yet** — no answer key. Re-check later. |
| **AppLovin** | Probe confirmed active Feb 2026, no charges. No answer key. |

Structural note: there is a 2–4 year lag between a fraud surfacing and the SEC charging it.
That is why the intersection of "surfaced after Jan 2025" and "already charged" is nearly
empty — and why Netcapital, charged seven days ago on conduct never before disclosed, is
an unusually lucky find rather than one of many options.

---

## Before you commit

Run `cold_prompt_test.py` against Gemini 3.5. **I could not run it — no API key in my
environment — so treat the blindness claim as unverified until you do.** It sends five
probes and greps for red-flag terms. If it returns CLEAN, you have your case; if it hits,
fall back to RYVYL.

Then run it again **on camera** as the opening beat of the demo video.

```bash
export GOOGLE_API_KEY=...
python3 cold_prompt_test.py --company "Netcapital Inc." --ticker NCPL

# rebuild the corpus any time:
python3 fetch_corpus.py --cik 1414767 --start 2021-01-01 --end 2024-06-30
```

## Scoring harness

Extract the six signals above from the complaint into `ground_truth.json`, then score each
fleet run on: findings recovered (of 6), named actors recovered (of 5 charged), unsupported
allegations made, citation accuracy against source filings, and human interventions (0).
That table is what wins the 40% category.
