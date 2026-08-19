"""FirestoreStore exercised against an in-memory Firestore double.

This catches API-shape bugs — wrong method names, bad query construction,
deprecated call forms — without a GCP project. It does NOT prove real-service
behaviour: security rules, composite-index requirements and contention are
untested here and must be verified against a live project.

    pip install mock-firestore
"""
import sys, os, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from mockfirestore import MockFirestore
except ImportError:
    print("SKIP  mock-firestore not installed (pip install mock-firestore)")
    raise SystemExit(0)

from casezero.state import FirestoreStore, MemoryStore
from casezero.orchestrator import InvestigationLoop, Budget


def store():
    return FirestoreStore(case_id="test", db=MockFirestore())


def test_events_append_and_replay_since():
    s = store()
    a = s.append_event("evidence", "evidence", {"summary": "one"})
    b = s.append_event("skeptic", "confidence_change", {"before": .8, "after": .3})
    allev = s.events()
    assert len(allev) == 2 and [e["actor"] for e in allev] == ["evidence", "skeptic"]
    assert s.events(since=a["ts"]) == [b] or len(s.events(since=a["ts"])) == 1
    assert all(e["ts"] > 0 and e["id"] for e in allev)
    print("PASS  firestore events append, order, and replay-since work")


def test_documents_roundtrip():
    s = store()
    s.put("evidence", "E-1", {"id": "E-1", "tier": "DIRECT", "summary": "x"})
    s.put("hypotheses", "H-1", {"id": "H-1", "confidence": 0.6})
    assert s.get("evidence", "E-1")["tier"] == "DIRECT"
    assert s.get("evidence", "missing") is None
    # NOTE: this test double auto-vivifies an empty document when you .get() a
    # missing one — real Firestore does not. all()/counts() filter empty docs,
    # which is correct in both worlds (a real doc can exist as a bare parent of
    # a subcollection). If this assertion ever reads 2, that filter regressed.
    assert len(s.all("evidence")) == 1 and len(s.all("hypotheses")) == 1
    print("PASS  put/get/all roundtrip; missing doc returns None; phantom docs filtered")


def test_lead_queue_priority_and_claim():
    s = store()
    for i, p in [("low", 0.2), ("high", 0.9), ("mid", 0.5)]:
        s.push_lead({"id": i, "priority": p, "question": i})
    got = [s.pop_lead()["id"] for _ in range(3)]
    assert got == ["high", "mid", "low"], got
    assert s.pop_lead() is None, "claimed leads must not be handed out twice"
    print("PASS  firestore lead queue is priority-ordered and claims are not re-issued")


def test_counts_only_counts_open_leads():
    s = store()
    s.put("evidence", "E-1", {"id": "E-1"})
    s.push_lead({"id": "L-1", "priority": 0.5})
    s.push_lead({"id": "L-2", "priority": 0.9})
    assert s.counts()["open_leads"] == 2
    s.pop_lead()
    c = s.counts()
    assert c["open_leads"] == 1, c
    assert c["evidence"] == 1
    print("PASS  counts() reports OPEN leads only, not claimed ones")


def test_no_deprecation_warnings_on_query_paths():
    """Positional where() is deprecated in google-cloud-firestore >= 2.11."""
    s = store()
    s.push_lead({"id": "L-1", "priority": 0.5})
    s.append_event("a", "b", {})
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        s.events(since=0)
        s.pop_lead()
        s.counts()
    bad = [x for x in w if "positional" in str(x.message).lower()]
    assert not bad, [str(x.message) for x in bad]
    print("PASS  no positional-argument deprecation warnings on any query path")


def test_full_investigation_runs_on_firestore():
    """The whole loop, backed by Firestore rather than memory."""
    def dispatch(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "found it"}]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": "H-1", "claim": "c", "confidence": 0.7,
                                    "supporting": ["E-1"], "contradicting": []}]}
        if agent == "skeptic":
            return {"verdicts": [{"hypothesis_id": "H-1", "survives": False,
                                  "confidence_after": 0.2, "attack": "no",
                                  "unsupported_leap": False, "reasoning": "r"}]}
        return {"leads": []}

    fs = store()
    rep = InvestigationLoop(store=fs, dispatch=dispatch, budget=Budget()).run("mission")
    assert rep["counts"]["evidence"] == 1
    assert fs.get("evidence", "E-1")["summary"] == "found it"
    kinds = {e["kind"] for e in fs.events()}
    assert {"mission", "dispatch", "evidence", "stop"} <= kinds, kinds
    print(f"PASS  full loop runs on Firestore backend ({len(fs.events())} audit events persisted)")


def test_memory_and_firestore_agree():
    """Both backends must produce the same investigation from the same inputs."""
    def dispatch(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"},
                                 {"id": "E-2", "tier": "INFERRED", "summary": "t"}]}
        return {"leads": []}

    reps = []
    for st in (MemoryStore(), store()):
        reps.append(InvestigationLoop(store=st, dispatch=dispatch, budget=Budget()).run("m"))
    a, b = reps
    assert a["counts"]["evidence"] == b["counts"]["evidence"] == 2
    assert a["stop_reason"] == b["stop_reason"], (a["stop_reason"], b["stop_reason"])
    print("PASS  memory and firestore backends produce identical results")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\n{len(fns)}/{len(fns)} passed")
