"""Offline tests for the dispatch resilience layer. No API key, no network."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel
from casezero.resilience import (CoverageGuard, extract_json, repair_loop, retry_with_backoff,
                                 is_transient, CitationGuard)


# ------------------------------------------------------------- extract_json
def test_extract_json_handles_real_model_output():
    cases = [
        ('{"a":1}', {"a": 1}),
        ('```json\n{"a":1}\n```', {"a": 1}),
        ('```\n{"a":1}\n```', {"a": 1}),
        ('Sure! Here is the JSON you asked for:\n\n{"a":1}\n\nHope that helps.', {"a": 1}),
        ('{"a":[1,2,],}', {"a": [1, 2]}),                       # trailing commas
        ('{"a":{"b":{"c":[1,{"d":2}]}}}', {"a": {"b": {"c": [1, {"d": 2}]}}}),
        ('{"q":"a } brace inside a string"}', {"q": "a } brace inside a string"}),
        ('{"q":"escaped \\" quote"}', {"q": 'escaped " quote'}),
        ("no json at all", None),
        ("", None),
    ]
    for raw, want in cases:
        got = extract_json(raw)
        assert got == want, f"{raw!r} -> {got!r}, wanted {want!r}"
    print(f"PASS  extract_json survives {len(cases)} real-world response shapes")


# -------------------------------------------------------------- repair_loop
class Shape(BaseModel):
    name: str
    count: int


def test_repair_loop_recovers_from_schema_violation():
    responses = [
        "I'd be happy to help! Let me think about this...",   # prose, no JSON
        '{"name":"evidence","count":"seven"}',                 # wrong type
        '{"name":"evidence","count":7}',                       # correct
    ]
    seen = []

    def call(prompt):
        seen.append(prompt)
        return responses[len(seen) - 1]

    events = []
    out, errs = repair_loop(call, "extract the evidence", Shape, attempts=3,
                            on_event=lambda k, p: events.append((k, p)))
    assert out is not None and out.count == 7, out
    assert len(errs) == 2, errs
    assert "rejected" in seen[1] and "rejected" in seen[2], "error not fed back"
    assert len(events) == 2 and events[0][0] == "schema_retry"
    print("PASS  repair_loop recovers from prose + type error in 3 calls, feeding errors back")


def test_repair_loop_gives_up_cleanly():
    out, errs = repair_loop(lambda p: "never json", "x", Shape, attempts=2)
    assert out is None and len(errs) == 2
    print("PASS  repair_loop gives up cleanly rather than raising")


# ---------------------------------------------------------------- backoff
def test_retry_only_retries_transient():
    slept = []

    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503 Service Unavailable")
        return "ok"

    assert retry_with_backoff(flaky, sleep=slept.append) == "ok"
    assert calls["n"] == 3 and len(slept) == 2
    assert all(0 < s <= 30 for s in slept), slept

    hard = {"n": 0}
    def bad_request():
        hard["n"] += 1
        raise ValueError("400 invalid argument: schema field unknown")

    try:
        retry_with_backoff(bad_request, sleep=slept.append)
        assert False, "should have raised"
    except ValueError:
        pass
    assert hard["n"] == 1, "a deterministic 400 must not be retried"
    assert is_transient(RuntimeError("429 rate limit")) is True
    assert is_transient(ValueError("400 bad request")) is False
    print(f"PASS  backoff retries transients ({len(slept)-0} sleeps) and never retries a 400")


# ----------------------------------------------------------- citation guard
CORPUS = {
    "2023-07-26_10-K.txt": (
        "The components of revenue are as follows: consulting services for equity "
        "securities, which recorded an increase in fees of $3,730,000, or 111% to "
        "$7,105,000 in fiscal 2023 as compared to $3,375,000 in fiscal 2022."),
    "2023-12-18_S-1A.txt": (
        "We had no prior direct or indirect ownership in these issuers prior to "
        "their offerings on the funding portal."),
}


def test_guard_accepts_real_quotes_and_quarantines_fabrications():
    g = CitationGuard(CORPUS)
    events = []
    result = {"evidence": [
        {"id": "E-01", "tier": "DIRECT", "summary": "real",
         "citations": [{"file": "2023-07-26_10-K.txt",
                        "quote": "an increase in fees of $3,730,000, or 111% to $7,105,000"}]},
        {"id": "E-02", "tier": "DIRECT", "summary": "whitespace drift is tolerated",
         "citations": [{"file": "2023-12-18_S-1A.txt",
                        "quote": "We had no prior   direct or indirect ownership\nin these issuers"}]},
        {"id": "E-03", "tier": "DIRECT", "summary": "fabricated quote",
         "citations": [{"file": "2023-07-26_10-K.txt",
                        "quote": "the agreements were backdated and signatures forged"}]},
        {"id": "E-04", "tier": "DIRECT", "summary": "invented source file",
         "citations": [{"file": "2024-99-99_10-Q.txt", "quote": "anything"}]},
    ]}
    g.screen(result, on_event=lambda k, p: events.append((k, p)))
    ev = {e["id"]: e for e in result["evidence"]}

    assert ev["E-01"]["citations"] and ev["E-01"]["tier"] == "DIRECT"
    assert ev["E-02"]["citations"] and ev["E-02"]["tier"] == "DIRECT", "whitespace should not fail"
    # fabrication: citation stripped, claim downgraded, flagged, kept for audit
    assert ev["E-03"]["citations"] == []
    assert ev["E-03"]["tier"] == "INFERRED"
    assert ev["E-03"]["integrity_flag"] == "unverifiable_citation"
    assert ev["E-03"]["quarantined_citations"][0]["_verdict"] == "NOT_FOUND"
    assert ev["E-04"]["quarantined_citations"][0]["_verdict"] == "BAD_FILE"

    assert len(events) == 2 and all(k == "citation_quarantine" for k, _ in events)
    r = g.report()
    assert r["checked"] == 4 and r["quarantined"] == 2 and r["accuracy"] == 0.5
    print("PASS  guard passes real quotes (incl. whitespace drift), quarantines "
          "fabricated quote + invented file, downgrades DIRECT->INFERRED")


def test_guard_does_not_touch_uncited_evidence():
    g = CitationGuard(CORPUS)
    res = {"evidence": [{"id": "E-1", "tier": "INFERRED", "summary": "an inference"}]}
    g.screen(res)
    assert "integrity_flag" not in res["evidence"][0]
    assert g.report()["checked"] == 0
    print("PASS  uncited INFERRED evidence passes through untouched")



# ------------------------------------------------- guard inside the real loop
def test_guard_quarantines_inside_the_investigation_loop():
    """End-to-end: a fabricating Evidence agent must not poison the graph."""
    from casezero.state import MemoryStore
    from casezero.orchestrator import InvestigationLoop, Budget

    def dispatch(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [
                {"id": "E-GOOD", "tier": "DIRECT", "summary": "supported claim",
                 "citations": [{"file": "2023-12-18_S-1A.txt",
                                "quote": "no prior direct or indirect ownership in these issuers"}]},
                {"id": "E-FAKE", "tier": "DIRECT", "summary": "invented claim",
                 "citations": [{"file": "2023-12-18_S-1A.txt",
                                "quote": "the chief executive admitted the scheme in writing"}]},
            ]}
        return {"leads": []}

    lp = InvestigationLoop(store=MemoryStore(), dispatch=dispatch,
                           guard=CitationGuard(CORPUS), budget=Budget())
    lp.run("what happened")

    good = lp.store.get("evidence", "E-GOOD")
    fake = lp.store.get("evidence", "E-FAKE")
    assert good["tier"] == "DIRECT" and good["citations"], good
    assert fake["tier"] == "INFERRED", "fabrication must be downgraded"
    assert fake["integrity_flag"] == "unverifiable_citation"
    assert fake["citations"] == [], "fabricated citation must not persist"

    q = [e for e in lp.store.events() if e["kind"] == "citation_quarantine"]
    assert len(q) == 1 and q[0]["payload"]["evidence"] == "E-FAKE", q
    assert q[0]["payload"]["downgraded"] is True
    print("PASS  loop quarantines a fabricated citation at ingest and logs it to the audit trail")



def test_coverage_guard_ignores_claims_with_no_absence_language():
    g = CoverageGuard({"a.txt": "CountSharp LLC received units."})
    assert g.check("CountSharp LLC received 2,853,659 units.") == []
    assert g.check("") == []


def test_coverage_guard_catches_a_false_absence():
    """Measured: at a 90-dispatch budget the fleet asserted the FY2022 and
    FY2023 10-Ks were absent. Both are in the corpus. It then used that claim
    to attack the true hypothesis, and recovery fell from 18.8% to 12.5%."""
    g = CoverageGuard({"2022-08-08_10-K_000497.txt": "annual report text",
                       "2023-07-26_10-K_000560.txt": "annual report text"})
    hits = g.check("The Form 10-K filings for the fiscal years ended April 30, "
                   "2022 and 2023 are absent from the corpus.")
    hard = [h for h in hits if h["severity"] == "HARD"]
    assert hard, "a flatly false absence claim must be caught"
    assert hard[0]["count"] == 2
    print("PASS  coverage guard catches a false absence claim about Form 10-K")


def test_coverage_guard_does_not_flag_a_true_absence():
    """'The details of the offerings for CountSharp LLC are absent' is TRUE -
    the offering documents are outside this corpus - even though CountSharp
    appears in eleven filings. A guard that flags this is lying in exactly the
    way it exists to prevent, so a referent inside a qualifying phrase is SOFT."""
    g = CoverageGuard({"a.txt": "CountSharp LLC received units."})
    hits = g.check("The details of the crowdfunding offerings for CountSharp LLC "
                   "are entirely absent from the provided corpus.")
    assert all(h["severity"] == "SOFT" for h in hits), hits
    assert g.report()["contradicted"] == 0
    print("PASS  coverage guard leaves a genuinely true absence claim alone")


def test_coverage_guard_leaves_hedged_language_alone():
    """Hedging is the fleet being careful. Punishing it would train out exactly
    the behaviour the project wants."""
    g = CoverageGuard({"2022-08-08_10-K_000497.txt": "annual report"})
    assert g.check("It is unclear whether the Form 10-K is included.") == []
    assert g.check("The corpus may not include every Form 10-K.") == []
    print("PASS  coverage guard ignores hedged uncertainty")


def test_contradicted_hypothesis_is_blocked_from_findings():
    from casezero.orchestrator import InvestigationLoop, Budget
    from casezero.state import MemoryStore

    def d(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"}],
                    "leads": [{"id": "L-h", "assign_to": "hypothesis",
                               "priority": 0.9, "question": "form hypotheses"}]}
        if agent == "hypothesis":
            return {"hypotheses": [
                {"id": "H-bad", "claim": "The Form 10-K filings are absent from "
                                         "the corpus.", "confidence": 0.9},
                {"id": "H-ok", "claim": "Revenue was settled in equity.",
                 "confidence": 0.6}]}
        return {"leads": []}

    lp = InvestigationLoop(
        store=MemoryStore(), dispatch=d, budget=Budget(max_dispatches=6, max_rounds=4),
        coverage=CoverageGuard({"2022-08-08_10-K_000497.txt": "annual report"}))
    rep = lp.run("mission")
    ids = {f["id"] for f in rep["findings"]}
    assert "H-bad" not in ids, "a corpus-contradicted claim must not reach the findings"
    assert "H-ok" in ids, "an unrelated claim must survive"
    assert rep["blocked_as_contradicted"] == ["H-bad"]
    assert [e for e in lp.store.events() if e["kind"] == "coverage_contradiction"]
    print("PASS  corpus-contradicted hypothesis blocked at 0.90 confidence, and logged")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\n{len(fns)}/{len(fns)} passed")
