#!/usr/bin/env python3
"""Run the fleet N times and report the distribution.

One run is an anecdote. The variance between runs is itself a finding, and
hiding it would be the same failure mode the whole project is built to avoid:
reporting a confident number the evidence doesn't support.

    python3 benchmark.py --runs 3 --budget 40
"""
import argparse, json, statistics, sys, time
from collections import Counter

sys.path.insert(0, ".")
from casezero.state import MemoryStore                      # noqa: E402
from casezero.orchestrator import InvestigationLoop, Budget, adk_dispatch  # noqa: E402
from casezero.agents import build_fleet                     # noqa: E402
from casezero.resilience import CitationGuard, CoverageGuard, load_corpus_docs  # noqa: E402
from casezero.forensic import screen, as_evidence, revenue_timeline, timeline_evidence  # noqa: E402
from casezero.ledger import audit as ledger_audit, as_evidence as ledger_evidence  # noqa: E402

MISSION = ("Determine whether this company misrepresented its financial condition, "
           "and identify who is responsible.")
CIK = "1414767"
WINDOW = ("2021-10-01", "2024-01-31")


def one_run(i, seed, docs, budget, docs_per_call):
    store = MemoryStore()
    guard = CitationGuard(docs)
    lp = InvestigationLoop(
        store=store,
        coverage=CoverageGuard(docs),
        dispatch=adk_dispatch(build_fleet(), store=store, docs_per_call=docs_per_call,
                              char_cap=40000),
        guard=guard,
        budget=Budget(max_dispatches=budget, max_rounds=budget))
    t0 = time.time()
    rep = lp.run(MISSION, seed_evidence=seed)
    cg = guard.report()
    ev = store.events()
    return {
        "run": i,
        "seconds": round(time.time() - t0),
        "stop_reason": rep["stop_reason"],
        "counts": rep["counts"],
        # Full findings, not just title+confidence: score_run.py needs the
        # description and the citations to grade a run at all.
        "findings": rep["findings"],
        "n_findings": len(rep["findings"]),
        "n_refuted": len(rep["refuted"]),
        "n_blocked": len(rep["blocked_as_unsupported"]),
        "n_contradicted": len(rep.get("blocked_as_contradicted", [])),
        "n_merged": sum(1 for e in ev if e["kind"] == "hypothesis_merged"),
        "citation_accuracy": cg["accuracy"],
        "citations_checked": cg["checked"],
        "quarantined": cg["quarantined"],
        "overrides": [e["payload"]["stage"] for e in ev
                      if e["kind"] == "starvation_override"],
        "errors": sum(1 for e in ev if e["kind"] in ("error", "dispatch_failed", "gave_up")),
        "schema_retries": sum(1 for e in ev if e["kind"] == "schema_retry"),
        "events": len(ev),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--budget", type=int, default=40)
    ap.add_argument("--docs-per-call", type=int, default=8)
    ap.add_argument("--out", default="benchmark_results.json")
    ap.add_argument("--save-run", default=None,
                    help="write the best run as a score_run.py-compatible JSON")
    ap.add_argument("--no-ledger", action="store_true",
                    help="ablation: withhold the ledger seed")
    ap.add_argument("--no-forensic", action="store_true",
                    help="ablation: withhold the forensic seed")
    args = ap.parse_args()

    docs = load_corpus_docs("corpus")
    seed = []
    if not args.no_forensic:
        seed += as_evidence(screen(CIK))
    tl = revenue_timeline(CIK, WINDOW[0], WINDOW[1])
    if not args.no_forensic:
        seed += timeline_evidence(tl)
    n_forensic = len(seed)

    n_ledger = 0
    if not args.no_ledger:
        rep = ledger_audit("corpus", reported_revenue=tl["total"],
                           window=list(WINDOW), quarters=tl["quarters"])
        led = ledger_evidence(rep)
        seed += led
        n_ledger = len(led)
        rc = rep["reconciliation"]
        print(f"ledger: {len(rep['counterparties'])} counterparties · "
              f"${rc['attributed_total']:,.0f} attributable "
              f"({rc['attributed_share_pct']}% of reported revenue)")
    print(f"seed: {n_forensic} forensic + {n_ledger} ledger = {len(seed)} objects\n")

    results = []
    for i in range(1, args.runs + 1):
        print(f"--- run {i}/{args.runs} ---", flush=True)
        r = one_run(i, seed, docs, args.budget, args.docs_per_call)
        results.append(r)
        print(f"  {r['seconds']}s · {r['stop_reason']} · {r['n_findings']} findings · "
              f"{r['n_refuted']} refuted · {r['n_blocked']} blocked · "
              f"citations {r['citation_accuracy']:.1%}", flush=True)
        json.dump(results, open(args.out, "w"), indent=2, default=str)

    # ------------------------------------------------------------- summary
    def dist(key):
        vals = [r[key] for r in results]
        return (f"{statistics.mean(vals):.2f} "
                f"(min {min(vals)}, max {max(vals)}"
                + (f", sd {statistics.stdev(vals):.2f}" if len(vals) > 1 else "") + ")")

    print(f"\n{'='*74}\nDISTRIBUTION over {len(results)} runs\n{'='*74}")
    for k in ("n_findings", "n_refuted", "n_blocked", "n_contradicted", "n_merged",
              "seconds",
              "citations_checked",
              "quarantined", "errors", "schema_retries"):
        print(f"  {k:<20} {dist(k)}")
    acc = [r["citation_accuracy"] for r in results if r["citation_accuracy"] is not None]
    if acc:
        print(f"  {'citation_accuracy':<20} {statistics.mean(acc):.1%} "
              f"(min {min(acc):.1%}, max {max(acc):.1%})")
    print(f"  {'stop_reasons':<20} {dict(Counter(r['stop_reason'] for r in results))}")

    print(f"\n{'='*74}\nFINDING STABILITY — how often each claim recurs\n{'='*74}")
    # crude but honest: cluster on shared significant words in the claim
    def key(t):
        stop = {"the", "and", "for", "that", "with", "from", "this", "were", "was",
                "inc", "netcapital", "its", "are", "has", "have", "not"}
        return frozenset(w for w in t.lower().split() if len(w) > 3 and w not in stop)

    clusters = []
    for r in results:
        for f in r["findings"]:
            k = key(f["title"])
            for c in clusters:
                if len(k & c["key"]) >= 4:
                    c["runs"].add(r["run"]); c["confs"].append(f["confidence"]); break
            else:
                clusters.append({"key": k, "title": f["title"], "runs": {r["run"]},
                                 "confs": [f["confidence"]]})
    for c in sorted(clusters, key=lambda c: -len(c["runs"])):
        cf = [x for x in c["confs"] if isinstance(x, (int, float))]
        mean = f"{statistics.mean(cf):.2f}" if cf else "n/a"
        print(f"  {len(c['runs'])}/{len(results)} runs · conf {mean} · {c['title'][:88]}")

    reproducible = sum(1 for c in clusters if len(c["runs"]) == len(results))
    print(f"\n  {reproducible}/{len(clusters)} distinct claims appeared in EVERY run.")
    print(f"  wrote {args.out}")

    if args.save_run:
        # The run with the most surviving findings, so the scorer grades the
        # fleet's best effort rather than an unlucky draw. Which run it was is
        # recorded, because "we picked the best of N" is a material caveat.
        best = max(results, key=lambda r: r["n_findings"])
        json.dump({"mission": MISSION, "source_run": best["run"],
                   "of_runs": len(results), "stop_reason": best["stop_reason"],
                   "findings": best["findings"]},
                  open(args.save_run, "w"), indent=2, default=str)
        print(f"  wrote {args.save_run} (run {best['run']} of {len(results)}, "
              f"{best['n_findings']} findings)")


if __name__ == "__main__":
    main()
