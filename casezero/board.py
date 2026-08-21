"""Mission Control — the live investigation board.

The board is not a separate reporting layer. It streams the SAME immutable event
log that serves as the audit trail: one structure, two consumers. Whatever the
judges watch scroll past is exactly what an auditor would later read back.

    GET  /              the board
    GET  /api/events    Server-Sent Events, replays history then tails live
    GET  /api/state     current snapshot (counts + hypotheses)
    POST /api/start     begin an investigation (returns immediately)

Run:
    python3 -m casezero.board --demo     # scripted fleet, no API key
    python3 -m casezero.board            # live fleet, needs GOOGLE_API_KEY
"""
from __future__ import annotations
import argparse, asyncio, json, os, threading, time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from .state import MemoryStore, make_store
from .orchestrator import InvestigationLoop, Budget

HERE = Path(__file__).resolve().parent.parent
BOARD_HTML = HERE / "board.html"

app = FastAPI(title="CASE ZERO — Mission Control")

CIK = os.environ.get("CASEZERO_CIK", "1414767")
CORPUS_DIR = os.environ.get("CASEZERO_CORPUS", "corpus")
# The SEC's "Relevant Period" in Netcapital's fiscal calendar.
WINDOW = (os.environ.get("CASEZERO_START", "2021-10-01"),
          os.environ.get("CASEZERO_END", "2024-01-31"))

STATE = {"store": None, "loop": None, "started": False, "thread": None}


def attach(store, loop):
    STATE["store"], STATE["loop"] = store, loop


@app.get("/", response_class=HTMLResponse)
def index():
    return BOARD_HTML.read_text()


@app.get("/api/state")
def api_state():
    s = STATE["store"]
    if s is None:
        return JSONResponse({"counts": {}, "hypotheses": []})
    hyps = s.all("hypotheses")
    hyps.sort(key=lambda h: -float(h.get("confidence", 0)))
    return {"counts": s.counts(), "hypotheses": hyps, "started": STATE["started"]}


@app.post("/api/reset")
def api_reset():
    """Clear the case so a run starts from empty.

    Firestore persists between runs, so without this every BEGIN piles onto the
    previous attempt - including failed ones. On camera that reads as the fleet
    finding things it found an hour ago.
    """
    s = STATE["store"]
    if s is None:
        return {"ok": False, "reason": "no store"}
    wiped = {}
    if hasattr(s, "_c"):                      # Firestore
        for coll in ("events", "evidence", "hypotheses", "verdicts", "leads"):
            n = 0
            for d in s._c(coll).stream():
                d.reference.delete(); n += 1
            wiped[coll] = n
    else:                                     # MemoryStore
        s._log.clear(); s._coll.clear(); s._leads.clear()
        wiped = {"memory": "cleared"}
    STATE["started"] = False
    return {"ok": True, "wiped": wiped}


@app.get("/api/events")
async def api_events():
    """Replay everything, then tail. Reconnecting mid-demo loses nothing."""
    async def gen():
        seen = 0.0
        idle = 0
        while True:
            s = STATE["store"]
            if s is not None:
                evs = s.events(since=seen)
                for e in evs:
                    seen = max(seen, e["ts"])
                    yield f"data: {json.dumps(e, default=str)}\n\n"
                if evs:
                    idle = 0
                else:
                    idle += 1
            # heartbeat keeps proxies from closing the stream
            if idle and idle % 40 == 0:
                yield ": ping\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/start")
def api_start(mission: str = "Determine whether this company misrepresented its "
                             "financial condition, and identify who is responsible."):
    if STATE["started"]:
        return {"ok": False, "reason": "already running"}
    STATE["started"] = True
    loop = STATE["loop"]
    # A fresh BEGIN gets a fresh budget. The loop object lives as long as the
    # container process — and --min-instances=1 keeps that process alive for
    # days — so without this reset every run after the first hits
    # budget.exhausted() on its opening check and dies in seconds with
    # "budget_exhausted" and zero dispatches.
    loop.budget.spent = 0
    loop.budget.rounds = 0

    def _run():
        try:
            # Deterministic forensic screens FIRST. The web path used to skip
            # these - only the benchmark harness passed them - so the deployed
            # fleet started from prose instead of arithmetic and went chasing
            # incidental anomalies (identical SBA loan amounts) rather than the
            # revenue-versus-cash gap the screens hand it for free.
            seed = []
            # Two independent screens, deliberately kept separate. Forensic works
            # on XBRL aggregates - the company's own reported totals. The ledger
            # works on the filing text - who was paid what, and in what form.
            # They fail differently, so one going dark does not silently take the
            # other with it.
            timeline = None
            try:
                from .forensic import (screen, as_evidence,
                                       revenue_timeline, timeline_evidence)
                seed = as_evidence(screen(CIK))
                timeline = revenue_timeline(CIK, WINDOW[0], WINDOW[1])
                seed += timeline_evidence(timeline)
            except Exception as e:
                STATE["store"].append_event(
                    "forensic", "error", {"error": f"seed unavailable: {e}"})
            try:
                from .ledger import audit, as_evidence as ledger_evidence
                # The reconciliation is the ledger's headline, and it needs the
                # reported-revenue denominator. Passed in rather than fetched, so
                # the ledger stays offline-testable and a network failure here
                # degrades to a register without a reconciliation instead of
                # taking the whole screen down.
                report = audit(CORPUS_DIR,
                               reported_revenue=timeline["total"] if timeline else None,
                               window=list(WINDOW),
                               quarters=timeline["quarters"] if timeline else None)
                led = ledger_evidence(report)
                seed += led
                rec = report["reconciliation"]
                STATE["store"].append_event("ledger", "screen", {
                    "counterparties": len(report["counterparties"]),
                    "equity_parties": rec["equity_counterparties"],
                    "equity_total": rec["equity_total"],
                    "derived_total": rec["derived_total"],
                    "attributed_total": rec["attributed_total"],
                    "attributed_share_pct": rec["attributed_share_pct"],
                    "overstatement_pct": rec["overstatement_pct"],
                    "reported_revenue": rec["reported_revenue"],
                    "repeated_strong": report["strong_count"],
                    "seeded": len(led),
                })
            except Exception as e:
                STATE["store"].append_event(
                    "ledger", "error", {"error": f"ledger unavailable: {e}"})
            loop.run(mission, seed_evidence=seed)
        except Exception as e:  # keep the board alive so the failure is visible
            STATE["store"].append_event("orchestrator", "error", {"error": str(e)})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    STATE["thread"] = t
    return {"ok": True, "mission": mission}


# --------------------------------------------------------------- demo fleet
def demo_dispatch(pace: float = 0.7):
    """A scripted investigation that mirrors the real Netcapital findings.

    No API key, no cost, deterministic. This is the rehearsal harness: use it to
    practise the demo and to check the board renders before you spend a cent on
    tokens. Every quote below is real and appears in the corpus.
    """
    script = [
        ("evidence", {"evidence": [
            {"id": "E-01", "tier": "DIRECT",
             "summary": "Revenue is dominated by a non-cash line: consulting services paid in equity",
             "citations": [{"file": "2023-07-26_10-K_000560.txt",
                            "quote": "consulting services for equity securities, which recorded an "
                                     "increase in fees of $3,730,000, or 111% to $7,105,000 in fiscal 2023"}],
             "figures": ["$7,105,000", "111%"]},
            {"id": "E-02", "tier": "DIRECT",
             "summary": "Eleven named counterparties supply nearly all revenue",
             "entities": ["Dark LLC", "Reper LLC", "NetWire LLC", "CustCorp", "HeadFarm LLC",
                          "CupCrew LLC", "CountSharp LLC", "RealWorld LLC"]},
        ]}),
        ("hypothesis", {"hypotheses": [
            {"id": "H-01", "claim": "Reported revenue does not correspond to any inflow of cash",
             "supporting": ["E-01"], "contradicting": [], "confidence": 0.62,
             "unresolved": ["Is equity-for-services an accepted practice at this scale?"]},
            {"id": "H-02", "claim": "Innocent explanation: early-stage clients legitimately pay in equity",
             "supporting": ["E-01"], "contradicting": [], "confidence": 0.45, "unresolved": []},
        ]}),
        ("evidence", {"evidence": [
            {"id": "E-03", "tier": "DIRECT",
             "summary": "Four supposedly independent startups transferred IDENTICAL unit counts "
                        "at IDENTICAL prices settling IDENTICAL receivables",
             "figures": ["2,853,659 units", "$0.41", "$1,170,000"],
             "entities": ["HeadFarm LLC", "CupCrew LLC", "CountSharp LLC", "RealWorld LLC"]},
        ]}),
        ("hypothesis", {"hypotheses": [
            {"id": "H-03", "claim": "The counterparties are under common control — independent "
                                    "parties do not converge on byte-identical terms",
             "supporting": ["E-03"], "contradicting": [], "confidence": 0.84, "unresolved": []},
        ]}),
        ("skeptic", {"verdicts": [
            {"hypothesis_id": "H-02", "survives": False, "confidence_after": 0.12,
             "attack": "Unrelated clients paid ~$50,000 cash for comparable services. These paid "
                       "$1.17M-$2.1M in paper. The innocent reading cannot survive that spread.",
             "unsupported_leap": False, "reasoning": "refuted by the filings' own comparison"},
        ]}),
        ("evidence", {"evidence": [
            {"id": "E-04", "tier": "DIRECT",
             "summary": "Company affirmatively denies any prior ownership in these issuers",
             "citations": [{"file": "2023-12-18_S-1A_045158.txt",
                            "quote": "We had no prior direct or indirect ownership in these issuers "
                                     "prior to their offerings on the funding portal"}]},
            {"id": "E-05", "tier": "DIRECT",
             "summary": "A related-party consultant is disclosed as the CFO's son",
             "citations": [{"file": "2023-10-06_DEF14A_000774.txt",
                            "quote": "John Fanning, Jr., son of Coreen Kraysler, our Chief Financial Officer"}],
             "entities": ["John Fanning, Jr.", "Coreen Kraysler"]},
            # Deliberate fabrication: the Evidence agent invents a quote that is
            # not in the corpus. The CitationGuard catches it at ingest and
            # downgrades the claim. Leave this in — a fleet that can be seen
            # catching its own hallucination is worth more than one that claims
            # it never has them.
            {"id": "E-06", "tier": "DIRECT",
             "summary": "Board minutes record approval of the related-party arrangement",
             "citations": [{"file": "2023-07-26_10-K_000560.txt",
                            "quote": "the board reviewed and approved the related party consulting "
                                     "arrangements with entities controlled by the chairman"}]},
        ]}),
        ("hypothesis", {"hypotheses": [
            {"id": "H-04", "claim": "An insider related to the CFO controls the counterparties",
             "supporting": ["E-03", "E-05"], "contradicting": ["E-04"], "confidence": 0.58,
             "unresolved": ["The filings name a 'Jr.' — they never name a senior."]},
            {"id": "H-05", "claim": "John Fanning Sr., husband of the CFO, controls the counterparties",
             "supporting": ["E-05"], "contradicting": [], "confidence": 0.79, "unresolved": []},
        ]}),
        ("skeptic", {"verdicts": [
            {"hypothesis_id": "H-05", "survives": False, "confidence_after": 0.79,
             "attack": "No person of that name appears in any of the 71 filings. 'Jr.' implies a "
                       "senior exists; it does not tell us who he is, or that he is the CFO's spouse. "
                       "This is an accusation the corpus cannot support.",
             "unsupported_leap": True, "reasoning": "identity not established by the record"},
            {"hypothesis_id": "H-01", "survives": True, "confidence_after": 0.91,
             "attack": "Could the equity be genuinely valuable? No — the filings mark it using the "
                       "same offerings it funded. The valuation is circular.",
             "unsupported_leap": False, "reasoning": "survives; strengthened"},
            {"hypothesis_id": "H-03", "survives": True, "confidence_after": 0.88,
             "attack": "Coincidence of terms? Four exact matches on three independent quantities "
                       "is not a coincidence any reasonable reading survives.",
             "unsupported_leap": False, "reasoning": "survives"},
            {"hypothesis_id": "H-04", "survives": True, "confidence_after": 0.74,
             "attack": "The relationship is real but the specific individual is not identified.",
             "unsupported_leap": False, "reasoning": "survives as stated — deliberately unnamed"},
        ]}),
        ("lead", {"leads": []}),
    ]
    step = {"i": 0}

    QUESTION = {
        "evidence": "Extract further evidence bearing on the open hypotheses.",
        "hypothesis": "Form competing explanations over the new evidence.",
        "skeptic": "Attack every open hypothesis.",
    }

    def d(agent, lead, ctx):
        time.sleep(pace)
        if step["i"] >= len(script):
            return {"leads": []} if agent == "lead" else {}
        who, payload = script[step["i"]]

        if agent == "lead":
            if who == "lead":
                step["i"] += 1
                return payload
            # Steer the fleet to whichever agent the script needs next.
            return {"leads": [{"id": f"L-{step['i']}", "priority": 0.9,
                               "assign_to": who, "rationale": "continue",
                               "question": QUESTION.get(who, "continue")}]}

        if who != agent:
            # Consume NOTHING. An earlier version advanced the cursor past every
            # non-matching entry, so a stale queued evidence lead would silently
            # eat the skeptic batch behind it - including the verdict that blocks
            # the named-individual hypothesis. The demo then ended with that
            # hypothesis standing at 79%, asserting on camera the exact
            # accusation this system exists to refuse. It is the one moment the
            # demo is built around, and it was being swallowed by a cursor bug.
            return {}

        step["i"] += 1
        return payload

    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="scripted fleet, no API key")
    # Cloud Run injects $PORT and the container MUST listen on it.
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    ap.add_argument("--pace", type=float, default=0.7)
    ap.add_argument("--autostart", action="store_true")
    args = ap.parse_args()

    store = MemoryStore() if args.demo else make_store()
    if args.demo:
        dispatch = demo_dispatch(args.pace)
    else:
        from .agents import build_fleet
        from .orchestrator import adk_dispatch
        dispatch = adk_dispatch(build_fleet(), store=store)

    # Citations are screened at ingest in both modes - a fabricated quote is
    # quarantined before it can become a hypothesis.
    guard = coverage = None
    try:
        from .resilience import CitationGuard, CoverageGuard, load_corpus_docs
        _docs = load_corpus_docs(CORPUS_DIR)
        guard = CitationGuard(_docs)
        coverage = CoverageGuard(_docs)
    except Exception as e:
        print(f"  [warn] citation guard disabled: {e}")

    loop = InvestigationLoop(store=store, dispatch=dispatch, guard=guard,
                             coverage=coverage,
                             budget=Budget(max_dispatches=80, max_rounds=40))
    attach(store, loop)

    if args.autostart:
        threading.Timer(1.0, lambda: api_start()).start()

    import uvicorn
    print(f"\n  CASE ZERO — Mission Control on http://0.0.0.0:{args.port}"
          f"{'  [DEMO]' if args.demo else ''}\n")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
