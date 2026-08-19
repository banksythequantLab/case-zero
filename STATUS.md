# CASE ZERO — what needs to happen

**13 days to the Aug 31 deadline. Credit request closes Aug 28, 12:00 PT.**

Preflight: 8 pass · 2 warn · 0 fail · 121 offline tests green.

---

## BLOCKED ON YOU — nothing moves until these happen

| # | Task | Why it's yours | Est |
|---|---|---|---|
| **B1** | **Create GCP project + link billing** | Your Google account; I can't reach the console from this sandbox | 15 min |
| **B2** | **Request the $150 credits** | **HARD DEADLINE Aug 28, 12:00 PT** — earlier than submission | 5 min |
| **B3** | Run `./deploy.sh`, work through it line by line | Never executed. Expect breakage on first run | 1–2 hr |
| **B4** | Record the 4-min video | `VIDEO.md` is shot-by-shot and timing-verified | 2–3 hr |
| **B5** | Paste `SUBMISSION.md` into Devpost, attach repo + diagram + video | — | 30 min |

Use **shell.cloud.google.com** for B1–B3: gcloud pre-installed, pre-authenticated.

---

## MINE — quality work, no GCP needed

| # | Task | Why it matters | Status |
|---|---|---|---|
| **M1** | **Fix run-to-run variance** | Only **1 of 3** distinct claims appears in every run. This is the biggest quality problem | **starting now** |
| **M2** | Score a real run against `ground_truth.json` | `score_run.py` has never been run on live output. This produces the submission's headline metric | queued |
| **M3** | Fold benchmark numbers into README/SUBMISSION | Currently cite the single-run figures | queued |
| **M4** | Target the consulting-revenue line in the aggregator | Would reconcile exactly to the SEC's $13.9M instead of ~7% off | optional |

---

## Benchmark: 3 runs × 36 dispatches, ~15 min each

```
findings           1.67  (min 1, max 2, sd 0.58)
refuted            0.67  (min 0, max 1)
blocked            0.67  (min 0, max 2)
citation accuracy  93.2% (min 84.4%, max 100%)
errors             0     schema retries 0
stop reason        budget_exhausted × 3
```

**The good:** zero errors, zero schema retries across ~108 live dispatches. The
resilience layer is holding under real load.

**The problem:** one claim in three reproduces across all runs — the persistent
operating-cash-flow gap, at 0.43 confidence. Everything else is a coin flip. A
demo that depends on a specific finding appearing is a demo that fails on camera.

**Diagnosis:** all three runs died on budget with the queue still full. The fleet
spends nearly its whole allowance gathering evidence and only 1–2 hypotheses
ever reach the Skeptic. It is not converging — it is being cut off mid-gather.
