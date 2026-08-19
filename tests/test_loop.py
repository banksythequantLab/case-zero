"""Offline tests for the fleet loop. No API key, no GCP, no network.

These cover the behaviours that actually decide whether the investigation is
trustworthy: does it stop honestly, does the skeptic really move confidence,
does an unsupported identification get blocked, does one dead agent kill the run.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from casezero.state import MemoryStore
from casezero.orchestrator import InvestigationLoop, Budget


def loop(dispatch, **b):
    return InvestigationLoop(store=MemoryStore(), dispatch=dispatch, budget=Budget(**b))


# ---------------------------------------------------------------- scripted fleet
def scripted(script):
    """dispatch that returns canned results per agent, in order."""
    calls = {"n": 0}

    def d(agent, lead, ctx):
        calls["n"] += 1
        seq = script.get(agent, [])
        if not seq:
            return {}
        return seq.pop(0) if len(seq) > 1 else seq[0]
    d.calls = calls
    return d


def test_stops_when_lead_finds_nothing():
    d = scripted({
        "evidence": [{"evidence": [{"id": "E-1", "summary": "revenue is non-cash",
                                    "tier": "DIRECT", "citations": []}]}],
        "lead": [{"leads": []}],
    })
    lp = loop(d)
    rep = lp.run("what happened")
    assert rep["stop_reason"] == "lead_agent_found_nothing_further", rep["stop_reason"]
    assert rep["counts"]["evidence"] == 1
    print("PASS  stops honestly when Lead returns no leads")


def test_budget_stops_runaway():
    # Lead always invents more work; budget must be what stops it.
    d = scripted({
        "evidence": [{"evidence": [{"id": "E-x", "summary": "s", "tier": "DIRECT"}]}],
        "lead": [{"leads": [{"id": None, "question": "more", "priority": 0.9,
                             "assign_to": "evidence", "rationale": "r"}]}],
    })
    lp = loop(d, max_dispatches=10, max_rounds=100)
    rep = lp.run("mission")
    assert rep["stop_reason"] == "budget_exhausted", rep["stop_reason"]
    assert lp.budget.spent <= 11, lp.budget.spent
    print(f"PASS  budget halts a runaway loop (spent={lp.budget.spent})")


def test_skeptic_lowers_confidence_and_refutes():
    d = scripted({
        "evidence": [{"evidence": [{"id": "E-1", "summary": "s", "tier": "DIRECT",
                                    "citations": [{"file": "f.txt", "quote": "q"}]}]}],
        "hypothesis": [{"hypotheses": [{"id": "H-1", "claim": "revenue was fabricated",
                                        "supporting": ["E-1"], "contradicting": [],
                                        "confidence": 0.81, "unresolved": []}]}],
        "skeptic": [{"verdicts": [{"hypothesis_id": "H-1", "survives": False,
                                   "confidence_after": 0.34, "attack": "ordinary practice",
                                   "unsupported_leap": False, "reasoning": "r"}]}],
        "lead": [
            {"leads": [{"id": "L-1", "question": "form hypotheses", "priority": 0.9,
                        "assign_to": "hypothesis", "rationale": "r"}]},
            {"leads": [{"id": "L-2", "question": "attack them", "priority": 0.9,
                        "assign_to": "skeptic", "rationale": "r"}]},
            {"leads": []},
        ],
    })
    lp = loop(d)
    rep = lp.run("mission")
    h = lp.store.get("hypotheses", "H-1")
    assert h["confidence"] == 0.34, h
    assert h["refuted"] is True
    assert "H-1" in rep["refuted"]
    assert all(f["id"] != "H-1" for f in rep["findings"])
    changes = [e for e in lp.store.events() if e["kind"] == "confidence_change"]
    assert changes and changes[0]["payload"]["before"] == 0.81
    print("PASS  skeptic moves confidence 0.81 -> 0.34 and refutes; audit event recorded")


def test_unsupported_identification_is_blocked():
    """The Fanning case: naming a person the corpus never names must not reach
    the final findings, even at high confidence."""
    d = scripted({
        "evidence": [{"evidence": [{"id": "E-1", "summary": "s", "tier": "DIRECT"}]}],
        "hypothesis": [{"hypotheses": [{"id": "H-9", "claim": "John Fanning controlled them",
                                        "supporting": ["E-1"], "contradicting": [],
                                        "confidence": 0.92, "unresolved": []}]}],
        "skeptic": [{"verdicts": [{"hypothesis_id": "H-9", "survives": True,
                                   "confidence_after": 0.92, "attack": "not named in corpus",
                                   "unsupported_leap": True, "reasoning": "r"}]}],
        "lead": [
            {"leads": [{"id": "L-1", "question": "hypothesise", "priority": 0.9,
                        "assign_to": "hypothesis", "rationale": "r"}]},
            {"leads": [{"id": "L-2", "question": "attack", "priority": 0.9,
                        "assign_to": "skeptic", "rationale": "r"}]},
            {"leads": []},
        ],
    })
    rep = loop(d).run("mission")
    assert "H-9" in rep["blocked_as_unsupported"], rep
    assert all(f["id"] != "H-9" for f in rep["findings"]), rep["findings"]
    print("PASS  high-confidence unsupported identification blocked from findings")


def test_agent_crash_does_not_kill_run():
    state = {"first": True}

    def d(agent, lead, ctx):
        if agent == "evidence" and state["first"]:
            state["first"] = False
            raise RuntimeError("model timeout")
        if agent == "lead":
            return {"leads": []}
        return {"evidence": [{"id": "E-2", "summary": "recovered", "tier": "DIRECT"}]}

    lp = loop(d)
    rep = lp.run("mission")
    errs = [e for e in lp.store.events() if e["kind"] == "error"]
    assert errs, "crash should be logged"
    assert rep["stop_reason"] in ("no_open_leads", "lead_agent_found_nothing_further")
    print("PASS  a crashed agent is logged and the investigation continues")


def test_leads_pop_highest_priority_first():
    s = MemoryStore()
    for p, i in [(0.2, "low"), (0.9, "high"), (0.5, "mid")]:
        s.push_lead({"id": i, "priority": p})
    assert [s.pop_lead()["id"] for _ in range(3)] == ["high", "mid", "low"]
    print("PASS  lead queue is priority-ordered")


def test_audit_log_is_complete():
    d = scripted({
        "evidence": [{"evidence": [{"id": "E-1", "summary": "s", "tier": "DIRECT"}]}],
        "lead": [{"leads": []}],
    })
    lp = loop(d)
    lp.run("determine what happened")
    kinds = [e["kind"] for e in lp.store.events()]
    for required in ("mission", "dispatch", "evidence", "stop"):
        assert required in kinds, f"missing {required} in {kinds}"
    assert all(e["ts"] > 0 and e["actor"] for e in lp.store.events())
    print(f"PASS  audit log complete ({len(kinds)} events, every one attributed and timestamped)")



def test_starvation_override_forces_progress():
    """Live-run regression: Lead requested evidence 14x and never hypothesised."""
    seen = []

    def d(agent, lead, ctx):
        seen.append(agent)
        if agent == "evidence":
            n = len([x for x in seen if x == "evidence"])
            return {"evidence": [{"id": f"E-{n}-{i}", "tier": "DIRECT", "summary": "s"}
                                 for i in range(4)]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": "H-1", "claim": "c", "confidence": 0.6,
                                    "supporting": [], "contradicting": []}]}
        # Lead is deliberately myopic: it only ever asks for more evidence.
        return {"leads": [{"id": None, "question": "more evidence", "priority": 0.9,
                           "assign_to": "evidence", "rationale": "r"}]}

    lp = loop(d, max_dispatches=30, max_rounds=20)
    lp.run("mission")
    assert "hypothesis" in seen, f"never advanced past evidence: {seen}"
    assert lp.store.counts()["hypotheses"] >= 1
    ov = [e for e in lp.store.events() if e["kind"] == "starvation_override"]
    assert ov and ov[0]["payload"]["stage"] == "hypothesis"
    print(f"PASS  starvation override forced hypothesis after {seen.index('hypothesis')} "
          f"evidence-only dispatches, and logged the intervention")


def test_no_override_when_pipeline_is_healthy():
    def d(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"}]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": "H-1", "claim": "c", "confidence": 0.6,
                                    "supporting": [], "contradicting": []}]}
        return {"leads": []}

    lp = loop(d)
    lp.run("mission")
    assert not [e for e in lp.store.events() if e["kind"] == "starvation_override"]
    print("PASS  no override fires when the fleet is progressing on its own")



def test_phase_cap_redirects_budget_to_judgement():
    """Benchmark regression: evidence consumed the whole allowance, so only
    1-2 hypotheses ever reached the Skeptic and findings didn't reproduce.

    Starvation guard can't help here — hypotheses and verdicts both already
    exist, so nothing is starved. The planner is simply myopic: it keeps
    asking for more evidence forever. The cap is the second line of defence.
    """
    seen = []

    def d(agent, lead, ctx):
        seen.append(agent)
        if agent == "evidence":
            return {"evidence": [{"id": f"E-{len(seen)}", "tier": "DIRECT",
                                  "summary": "s"}]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": f"H-{len(seen)}", "claim": "c",
                                    "confidence": 0.6, "supporting": [],
                                    "contradicting": []}]}
        if agent == "skeptic":
            return {"verdicts": [{"hypothesis_id": f"H-{len(seen)}", "survives": True,
                                  "confidence_after": 0.7, "attack": "a",
                                  "unsupported_leap": False, "reasoning": "r"}]}
        return {"leads": [{"id": None, "question": "more evidence", "priority": 0.9,
                           "assign_to": "evidence", "rationale": "r"}]}

    lp = loop(d, max_dispatches=24, max_rounds=60)
    # Pre-seed so neither starvation rule applies — isolate the cap.
    lp.store.put("hypotheses", "H-0", {"id": "H-0", "claim": "seed", "confidence": 0.5})
    lp.store.put("verdicts", "V-0", {"hypothesis_id": "H-0", "survives": True})
    lp.run("mission")

    ev = seen.count("evidence")
    assert ev <= 24 * 0.45 + 1, f"evidence exceeded its cap: {ev} of {len(seen)}"
    caps = [e for e in lp.store.events() if e["kind"] == "phase_cap"]
    assert caps, "cap should have fired and been logged"
    assert any(a in seen for a in ("hypothesis", "skeptic")), "budget never reached judgement"
    print(f"PASS  phase cap held evidence to {ev}/{len(seen)} dispatches, "
          f"fired {len(caps)}x, budget redirected downstream")


def test_phase_cap_does_not_fire_on_a_balanced_run():
    def d(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"}]}
        return {"leads": []}

    lp = loop(d)
    lp.run("mission")
    assert not [e for e in lp.store.events() if e["kind"] == "phase_cap"]
    print("PASS  no phase cap on a short balanced run")


def test_demo_script_reaches_the_blocking_verdict():
    """The demo exists to show the fleet REFUSING to name a man the filings
    never name. The scripted dispatcher used to advance its cursor past every
    non-matching entry, so a stale queued evidence lead would silently swallow
    the skeptic batch behind it. The demo then ran to completion with
    "John Fanning Sr. ... controls the counterparties" standing at 79% ACTIVE -
    asserting on camera the exact accusation the system exists to refuse.

    Every scripted verdict must land, and H-05 must be blocked.
    """
    from casezero.board import demo_dispatch

    lp = InvestigationLoop(store=MemoryStore("demo"), dispatch=demo_dispatch(0.0),
                           budget=Budget(max_dispatches=60, max_rounds=40))
    lp.run("mission")

    hyps = {h["id"]: h for h in lp.store.all("hypotheses")}
    assert len(lp.store.all("verdicts")) == 5, \
        f"scripted verdicts were swallowed: {len(lp.store.all('verdicts'))} of 5"
    assert hyps["H-05"]["unsupported_leap"] is True, "the named-individual claim was not blocked"
    assert hyps["H-05"]["refuted"] is True
    assert hyps["H-01"]["confidence"] == 0.91, "surviving hypotheses must still be strengthened"
    assert not hyps["H-04"].get("unsupported_leap"), \
        "the deliberately unnamed hypothesis must survive"
    print("PASS  demo reaches the blocking verdict — H-05 blocked, H-04 survives unnamed")



def test_verdict_for_an_absorbed_hypothesis_lands_on_the_survivor():
    """The subtle way consolidation could break everything.

    If H-2 is merged into H-1 and the Skeptic later issues its verdict against
    H-2, a naive implementation drops the verdict on the floor - the attack
    silently disappears and the claim keeps its confidence unchallenged. An
    alias map routes it to the survivor instead.
    """
    CLAIM_A = ("The repeated $1,170,000 valuations across CountSharp LLC represent "
               "an artificial scheme with non-arm's length valuations used to "
               "inflate revenues.")
    CLAIM_B = ("The repeated $1,170,000 valuations across CountSharp LLC are an "
               "artificial scheme, using non-arm's length valuations to inflate "
               "reported revenues.")
    step = {"i": 0}

    def d(agent, lead, ctx):
        step["i"] += 1
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"}],
                    "leads": [{"id": "L-h", "assign_to": "hypothesis", "priority": 0.9,
                               "question": "form hypotheses"}]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": "H-1", "claim": CLAIM_A, "confidence": 0.4},
                                   {"id": "H-2", "claim": CLAIM_B, "confidence": 0.3}],
                    "leads": [{"id": "L-s", "assign_to": "skeptic", "priority": 0.9,
                               "question": "attack"}]}
        if agent == "skeptic":
            # Addressed to the ABSORBED id.
            return {"verdicts": [{"hypothesis_id": "H-2", "survives": False,
                                  "confidence_after": 0.05,
                                  "attack": "the valuations are circular"}]}
        return {"leads": []}

    lp = loop(d)
    lp.run("mission")

    merges = [e for e in lp.store.events() if e["kind"] == "hypothesis_merged"]
    assert merges, "the two near-identical wrongdoing claims should have merged"
    assert merges[0]["payload"]["kept"] == "H-1"

    survivor = lp.store.get("hypotheses", "H-1")
    assert survivor["confidence"] == 0.05, \
        f"verdict for the absorbed id must reach the survivor, got {survivor['confidence']}"
    assert survivor["refuted"] is True
    print("PASS  verdict addressed to an absorbed hypothesis routes to the survivor")


def test_consolidation_never_merges_competing_explanations():
    """End-to-end version of the safety property: the innocent explanation and
    the fraud explanation of the same figures must both survive ingest."""
    FRAUD = ("The identical $1,170,000 valuations across CountSharp LLC and CupCrew "
             "LLC represent an artificial revenue scheme using non-arm's length "
             "valuations to inflate revenues.")
    INNOCENT = ("The identical $1,170,000 valuations across CountSharp LLC and CupCrew "
                "LLC are the result of standardized, routine commercial consulting "
                "agreements priced by ordinary practice.")

    def d(agent, lead, ctx):
        if agent == "evidence":
            return {"evidence": [{"id": "E-1", "tier": "DIRECT", "summary": "s"}],
                    "leads": [{"id": "L-h", "assign_to": "hypothesis", "priority": 0.9,
                               "question": "q"}]}
        if agent == "hypothesis":
            return {"hypotheses": [{"id": "H-f", "claim": FRAUD, "confidence": 0.5},
                                   {"id": "H-i", "claim": INNOCENT, "confidence": 0.5}]}
        return {"leads": []}

    lp = loop(d)
    lp.run("mission")
    ids = {h["id"] for h in lp.store.all("hypotheses")}
    assert ids == {"H-f", "H-i"}, f"competing explanations were collapsed: {ids}"
    assert not [e for e in lp.store.events() if e["kind"] == "hypothesis_merged"]
    print("PASS  fraud and innocent readings of identical figures both survive ingest")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"\n{len(fns)}/{len(fns)} passed")
