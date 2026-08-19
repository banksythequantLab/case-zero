"""The fleet loop.

The orchestration logic lives in InvestigationLoop, which knows nothing about
ADK or Gemini - it takes a `dispatch` callable. That separation is deliberate:
it means the loop's termination, prioritisation and audit behaviour are testable
offline with zero API calls (see tests/test_loop.py), and only the dispatch
layer needs credentials.

Control flow, which is the point of the whole project:

    seed lead -> EVIDENCE -> HYPOTHESIS -> SKEPTIC -> LEAD -> new leads
                    ^                                            |
                    +--------------------------------------------+

Nothing here is a fixed pipeline. The Lead agent reads the current graph and
decides what runs next; the loop only drains a priority queue. Agents create
work for other agents. The fleet stops when Lead returns no leads, when the
queue empties, or when a budget is hit - never on a fixed step count.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .state import Store, MemoryStore

Dispatch = Callable[[str, dict, dict], dict]


@dataclass
class Budget:
    max_dispatches: int = 60
    max_rounds: int = 12
    spent: int = 0
    rounds: int = 0

    def exhausted(self) -> bool:
        return self.spent >= self.max_dispatches or self.rounds >= self.max_rounds


@dataclass
class InvestigationLoop:
    store: Store
    dispatch: Dispatch
    budget: Budget = field(default_factory=Budget)
    stop_reason: Optional[str] = None
    guard: Optional[object] = None      # resilience.CitationGuard
    coverage: Optional[object] = None   # resilience.CoverageGuard
    consolidate_hypotheses: bool = True  # merge same-stance duplicates at ingest
    # absorbed hypothesis id -> surviving id, so a later verdict still lands
    _alias: Dict[str, str] = field(default_factory=dict)

    MAX_LEADS_PER_CALL = 3

    # -------------------------------------------------------------- helpers
    def _log(self, actor: str, kind: str, **payload):
        return self.store.append_event(actor, kind, payload)

    def _ingest(self, agent: str, result: dict) -> int:
        """Persist whatever an agent produced. Returns count of new objects.

        Citations are screened HERE, before evidence can become a hypothesis -
        a fabricated quote is quarantined where it happens rather than being
        discovered later at scoring time, after it has already shaped the
        investigation.
        """
        if self.guard is not None and result:
            self.guard.screen(result, on_event=lambda k, p: self._log(agent, k, **p))
        n = 0
        for ev in result.get("evidence", []) or []:
            eid = ev.get("id") or f"E-{uuid.uuid4().hex[:6]}"
            ev["id"] = eid
            self.store.put("evidence", eid, ev)
            self._log(agent, "evidence", id=eid, summary=ev.get("summary", ""),
                      tier=ev.get("tier"), entities=ev.get("entities", []),
                      figures=ev.get("figures", []))
            n += 1

        for h in result.get("hypotheses", []) or []:
            hid = h.get("id") or f"H-{uuid.uuid4().hex[:6]}"
            h["id"] = hid
            # A claim that something is ABSENT from the corpus is checkable for
            # free against the corpus index, and the fleet gets it wrong: at a
            # 90-dispatch budget it asserted the FY2022 and FY2023 10-Ks were
            # missing when both are present, then used that to attack the true
            # hypothesis. Flagged, never deleted - the assertion itself is worth
            # keeping in the audit trail.
            if self.coverage is not None:
                bad = [c for c in self.coverage.check(h.get("claim", ""))
                       if c.get("severity") == "HARD"]
                if bad:
                    h["coverage_contradiction"] = bad
                    self._log(agent, "coverage_contradiction", id=hid,
                              claim=h.get("claim", "")[:160],
                              referents=[c["referent"] for c in bad],
                              found_in=bad[0]["found_in"])
            # Consolidation: fold a new claim into an existing one ONLY when
            # they share a stance, share figures, and are lexically close. The
            # stance gate is the whole point - merging a wrongdoing claim into
            # the innocent explanation of the same facts would improve every
            # metric we track while deleting the disagreement this architecture
            # exists to produce. Measured on six live runs it fires zero times;
            # it is a guard, not a fix.
            if self.consolidate_hypotheses:
                absorbed_into = self._try_consolidate(agent, hid, h)
                if absorbed_into:
                    n += 1
                    continue
            prior = self.store.get("hypotheses", hid)
            self.store.put("hypotheses", hid, h)
            self._log(agent, "hypothesis", id=hid, claim=h.get("claim", ""),
                      confidence=h.get("confidence"),
                      prior_confidence=(prior or {}).get("confidence"))
            n += 1

        for v in result.get("verdicts", []) or []:
            hid = self._alias.get(v.get("hypothesis_id"), v.get("hypothesis_id"))
            self.store.put("verdicts", f"{hid}-{uuid.uuid4().hex[:4]}", v)
            h = self.store.get("hypotheses", hid)
            if h:
                before = h.get("confidence")
                h["confidence"] = v.get("confidence_after", before)
                h["refuted"] = not v.get("survives", True)
                h["unsupported_leap"] = bool(v.get("unsupported_leap"))
                self.store.put("hypotheses", hid, h)
                self._log(agent, "confidence_change", id=hid, before=before,
                          after=h["confidence"], survives=v.get("survives"),
                          unsupported_leap=h["unsupported_leap"],
                          attack=v.get("attack", ""))
            n += 1

        # Cap leads per call. Live run: Lead emitted faster than the fleet could
        # drain, ending with 30 open leads and a budget spent on gathering. A
        # planner that can enqueue without limit will always out-run its own
        # workers. Highest-priority survive; the rest are dropped and logged,
        # never silently.
        leads = sorted(result.get("leads", []) or [],
                       key=lambda l: -float(l.get("priority", 0.5)))
        if len(leads) > self.MAX_LEADS_PER_CALL:
            self._log(agent, "leads_truncated", emitted=len(leads),
                      kept=self.MAX_LEADS_PER_CALL,
                      dropped=[l.get("question", "")[:60] for l in leads[self.MAX_LEADS_PER_CALL:]])
            leads = leads[:self.MAX_LEADS_PER_CALL]

        for l in leads:
            lid = l.get("id") or f"L-{uuid.uuid4().hex[:6]}"
            l["id"] = lid
            self.store.push_lead(l)
            self._log(agent, "lead", id=lid, question=l.get("question", ""),
                      priority=l.get("priority"), assign_to=l.get("assign_to"))
            n += 1
        return n

    def _try_consolidate(self, agent: str, hid: str, h: dict) -> Optional[str]:
        """Fold `h` into an existing hypothesis if they are true duplicates.

        Returns the surviving id, or None. An alias is recorded so a later
        verdict addressed to the absorbed id still lands on the survivor -
        without that, merging would silently swallow the Skeptic's attack.
        """
        from .consolidate import should_merge, merge as _merge
        if self.store.get("hypotheses", hid):     # a restatement of itself
            return None
        for existing in self.store.all("hypotheses"):
            if existing.get("id") == hid:
                continue
            ok, why = should_merge(existing, h)
            if not ok:
                continue
            merged = _merge(existing, h)
            self.store.put("hypotheses", existing["id"], merged)
            self._alias[hid] = existing["id"]
            self._log(agent, "hypothesis_merged", kept=existing["id"], absorbed=hid,
                      reason=why, kept_claim=existing.get("claim", "")[:160],
                      absorbed_claim=h.get("claim", "")[:160],
                      confidence=merged.get("confidence"))
            return existing["id"]
        return None

    # ------------------------------------------------------- starvation guard
    # First live run: the Lead agent requested evidence 14 times in a row and
    # never once advanced to hypothesis. 38 evidence objects, zero hypotheses,
    # budget gone. Left to itself an LLM planner will keep gathering, because
    # gathering always looks defensible and committing to a claim does not.
    #
    # The fix is a scheduler property, not a prompt tweak: if a downstream stage
    # is starved while its input is plentiful, the orchestrator injects the lead
    # itself. Topology stays runtime-decided - this only guarantees liveness, the
    # way any scheduler must. Every injection is logged as an orchestrator
    # intervention rather than passed off as the planner's idea.
    STARVATION = (
        # (stage, needs, upstream, min_upstream, max_consecutive_skips)
        ("hypothesis", "hypotheses", "evidence", 8, 3),
        ("skeptic", "verdicts", "hypotheses", 2, 3),
    )

    # Share of total budget any single stage may consume. Three benchmark runs
    # all died budget_exhausted with the lead queue still full: the fleet spent
    # its whole allowance gathering and only 1-2 hypotheses ever reached the
    # Skeptic. Consequence was that just one claim in three reproduced across
    # runs - the rest were a coin flip, which is fatal for a live demo.
    #
    # Gathering is unbounded (there is always another document) while judgement
    # is what actually produces findings, so an unconstrained planner starves
    # the back half of its own pipeline. Capping evidence forces the budget
    # into hypothesis and skeptic, where convergence happens.
    PHASE_CAP = {"evidence": 0.45}

    def over_phase_cap(self, agent: str) -> bool:
        cap = self.PHASE_CAP.get(agent)
        if not cap or not self.budget.max_dispatches:
            return False
        used = sum(1 for e in self.store.events()
                   if e["kind"] == "dispatch" and e["payload"].get("agent") == agent)
        return used >= cap * self.budget.max_dispatches

    def starved_lead(self) -> Optional[dict]:
        counts = self.store.counts()
        recent = [e["payload"].get("agent") for e in self.store.events()
                  if e["kind"] == "dispatch"][-6:]
        for stage, produces, upstream, need, skips in self.STARVATION:
            if counts.get(produces, 0) == 0 and counts.get(upstream, 0) >= need \
                    and recent.count(stage) == 0 and len(recent) >= skips:
                self._log("orchestrator", "starvation_override", stage=stage,
                          upstream=upstream, upstream_count=counts.get(upstream),
                          note=f"{upstream} is plentiful and {stage} has produced nothing")
                return {
                    "id": f"L-force-{stage}",
                    "priority": 1.0,
                    "assign_to": stage,
                    "rationale": "orchestrator starvation override",
                    "question": {
                        "hypothesis": ("You have substantial evidence and no hypotheses. "
                                       "Form competing explanations NOW over the evidence "
                                       "already collected, including at least one innocent "
                                       "explanation. Do not request more evidence."),
                        "skeptic": ("Hypotheses are open and unchallenged. Attack every one "
                                    "of them now. Do not request more evidence."),
                    }[stage],
                }
        return None

    def _context(self) -> dict:
        """What the next agent gets to see. Hypotheses are ordered by how
        unsettled they are - an agent's attention should go where the
        uncertainty is, not where the confidence is."""
        hyps = self.store.all("hypotheses")
        hyps.sort(key=lambda h: abs(float(h.get("confidence", 0.5)) - 0.5))
        return {
            "counts": self.store.counts(),
            "hypotheses": hyps[:20],
            "recent_evidence": self.store.all("evidence")[-40:],
        }

    # ----------------------------------------------------------------- run
    def seed(self, mission: str, seed_evidence: Optional[List[dict]] = None):
        self._log("orchestrator", "mission", mission=mission)

        # Deterministic screens run BEFORE any model call, so the fleet starts
        # from arithmetic rather than from prose. Nothing here can hallucinate:
        # the forensic screens are computed from filed XBRL, the ledger screens
        # from the filing text itself.
        #
        # Each screen is ingested under its OWN actor. Attributing both to
        # "forensic" would make the audit trail claim an XBRL provenance for
        # findings that came from parsing prose - a small lie, but exactly the
        # kind this system exists to refuse.
        if seed_evidence:
            by_source: Dict[str, List[dict]] = {}
            for e in seed_evidence:
                by_source.setdefault(e.get("source", "forensic"), []).append(e)
            for source, items in sorted(by_source.items()):
                self._ingest(source, {"evidence": items})
                self._log(source, "seeded", count=len(items),
                          methods=sorted({e.get("method", "?") for e in items}))

        self.store.push_lead(dict(
            id="L-seed", priority=1.0, assign_to="evidence",
            question=("Survey the corpus. Extract the revenue composition, all named "
                      "counterparties, all related-party disclosures, and any figures "
                      "that repeat across supposedly independent parties."),
            rationale="initial sweep"))

    def run(self, mission: str, seed_evidence: Optional[List[dict]] = None) -> dict:
        self.seed(mission, seed_evidence)

        while True:
            if self.budget.exhausted():
                self.stop_reason = "budget_exhausted"
                break

            lead = self.starved_lead() or self.store.pop_lead()
            if lead is None:
                self.stop_reason = "no_open_leads"
                break

            self.budget.rounds += 1
            agent = lead.get("assign_to", "evidence")

            if self.over_phase_cap(agent):
                # Requeue at low priority rather than dropping: if the fleet
                # genuinely runs out of judgement work the lead is still there.
                self._log("orchestrator", "phase_cap", agent=agent,
                          lead=lead.get("id"),
                          note=f"{agent} has used its share of the budget; deferring")
                lead["priority"] = 0.01
                self.store.push_lead(lead)
                forced = self.starved_lead()
                if forced is None:
                    for stage in ("hypothesis", "skeptic"):
                        if self.store.counts().get(
                                {"hypothesis": "evidence", "skeptic": "hypotheses"}[stage], 0):
                            forced = {"id": f"L-cap-{stage}", "priority": 1.0,
                                      "assign_to": stage,
                                      "rationale": "phase cap redirect",
                                      "question": ("Work with the evidence already "
                                                   "collected. Do not request more.")}
                            break
                if forced is None:
                    self.stop_reason = "phase_cap_with_no_downstream_work"
                    break
                lead, agent = forced, forced["assign_to"]
            self._log("orchestrator", "dispatch", agent=agent, lead=lead.get("id"),
                      question=lead.get("question", ""))

            try:
                result = self.dispatch(agent, lead, self._context())
                self.budget.spent += 1
            except Exception as e:  # a dead agent must not kill the investigation
                self._log(agent, "error", lead=lead.get("id"), error=str(e))
                self.budget.spent += 1
                continue

            self._ingest(agent, result or {})

            # After substantive work, ask Lead what to do next. Lead returning
            # nothing is how the investigation ends honestly.
            if agent != "lead" and not self.budget.exhausted():
                try:
                    nxt = self.dispatch("lead", {"id": "L-auto", "question":
                                                 "What should the fleet investigate next?"},
                                        self._context())
                    self.budget.spent += 1
                    added = self._ingest("lead", nxt or {})
                    if added == 0 and self.store.counts()["open_leads"] == 0:
                        self.stop_reason = "lead_agent_found_nothing_further"
                        break
                except Exception as e:
                    self._log("lead", "error", error=str(e))
                    self.budget.spent += 1

        self._log("orchestrator", "stop", reason=self.stop_reason,
                  **self.store.counts())
        return self.report()

    # -------------------------------------------------------------- report
    def report(self) -> dict:
        hyps = self.store.all("hypotheses")
        surviving = [h for h in hyps
                     if not h.get("refuted") and not h.get("unsupported_leap")
                     and not h.get("coverage_contradiction")]
        surviving.sort(key=lambda h: -float(h.get("confidence", 0)))
        return {
            "stop_reason": self.stop_reason,
            "counts": self.store.counts(),
            "human_interventions": 0,
            "findings": [
                {
                    "id": h["id"],
                    "title": h.get("claim", "")[:120],
                    "description": h.get("claim", ""),
                    "confidence": h.get("confidence"),
                    "evidence": [
                        c
                        for eid in h.get("supporting", [])
                        for c in (self.store.get("evidence", eid) or {}).get("citations", [])
                    ],
                }
                for h in surviving
            ],
            "refuted": [h["id"] for h in hyps if h.get("refuted")],
            "blocked_as_unsupported": [h["id"] for h in hyps if h.get("unsupported_leap")],
            "blocked_as_contradicted": [h["id"] for h in hyps
                                        if h.get("coverage_contradiction")],
        }


# ------------------------------------------------------- ADK dispatch layer
def adk_dispatch(fleet: dict, corpus_dir: str = "corpus", store: Optional[Store] = None,
                 docs_per_call: int = 8, char_cap: int = 60000) -> Dispatch:
    """Wire the loop to real ADK agents, with the resilience layer applied.

    Every call is wrapped in: transient-error backoff -> tolerant JSON
    extraction -> schema repair with the validation error fed back. Failures
    are logged as audit events rather than swallowed.

    NOT RUN against live Gemini in this environment - no GOOGLE_API_KEY here.
    The resilience helpers it uses ARE tested (tests/test_resilience.py); the
    ADK wiring itself is a scaffold. Verify before relying on it.
    """
    import asyncio, json, os, re
    from .passages import (query_terms as select_terms, select as select_passages,
                            score_document)
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from .resilience import extract_json, retry_with_backoff

    def _log(actor, kind, **p):
        if store is not None:
            store.append_event(actor, kind, p)

    def _call(agent_name: str, prompt: str) -> str:
        agent = fleet[agent_name]
        runner = InMemoryRunner(agent=agent, app_name="case_zero")

        async def _go():
            session = await runner.session_service.create_session(
                app_name="case_zero", user_id="fleet")
            out = ""
            async for ev in runner.run_async(
                    user_id="fleet", session_id=session.id,
                    new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
                if ev.content and ev.content.parts and ev.content.parts[0].text:
                    out = ev.content.parts[0].text
            return out

        return retry_with_backoff(
            lambda: asyncio.run(_go()),
            on_event=lambda k, p: _log(agent_name, k, **p))

    def _dispatch(agent_name: str, lead: dict, context: dict) -> dict:
        docs = ""
        if agent_name == "evidence":
            names = [n for n in sorted(os.listdir(corpus_dir)) if n.endswith(".txt")]
            # Do NOT take names[:N]. Filenames are date-prefixed, so slicing the
            # front feeds the fleet only the oldest filings - in the first live
            # runs it never once saw the FY2023 10-K, where the decisive numbers
            # actually are. Select by relevance to the lead, then spread the
            # remainder evenly across the whole period.
            # Selectors come from the lead AND from figures already in the
            # investigation state - a figure like 2,853,659 locates the decisive
            # paragraph in one hop where "revenue" matches five hundred places.
            terms = select_terms(lead.get("question", "") or "",
                                 json.dumps(context, default=str)[:20000])
            texts = {n: open(os.path.join(corpus_dir, n), errors="replace").read()
                     for n in names}
            # Score over the WHOLE document. Scoring on read(8000) ranked
            # filings by their cover page.
            scored = []
            for n in names:
                bulk = 2 if ("10-K" in n or "10-Q" in n) else 0   # substance over 8-Ks
                scored.append((score_document(texts[n], terms) + bulk, n))
            scored.sort(key=lambda x: -x[0])
            top = [n for _, n in scored[:max(1, docs_per_call // 2)]]
            rest = [n for n in names if n not in top]
            stride = max(1, len(rest) // max(1, docs_per_call - len(top)))
            picked = top + rest[::stride][:docs_per_call - len(top)]

            chunks, shown_chars, total_chars = [], 0, 0
            for n in picked:
                # Windows around matches, NOT the head. The financial statement
                # notes are at the END of an SEC filing: in the FY2023 10-K the
                # sentence naming 2,853,659 begins at character 302,971 of
                # 320,968, so every head-cut run was structurally incapable of
                # seeing the central evidence.
                excerpt, st = select_passages(texts[n], terms, budget=char_cap)
                chunks.append(f"=== {n} ({st['mode']}: {st['chars']:,} of "
                              f"{st['of']:,} chars, {st['matches']} term matches) ===\n"
                              + excerpt)
                shown_chars += st["chars"]
                total_chars += st["of"]
            docs = "\n\n".join(chunks)
            if len(names) > len(picked) or shown_chars < total_chars:
                _log(agent_name, "coverage_note",
                     shown=len(picked), total=len(names),
                     chars_shown=shown_chars, chars_total=total_chars,
                     note="relevance-windowed excerpts - elisions are marked inline")

        base = (f"QUESTION: {lead.get('question','')}\n\n"
                f"CURRENT STATE:\n{json.dumps(context, default=str)[:20000]}\n\n"
                f"{('DOCUMENTS:' + chr(10) + docs) if docs else ''}")

        prompt = base
        for attempt in range(3):
            try:
                raw = _call(agent_name, prompt)
            except Exception as e:
                _log(agent_name, "dispatch_failed", error=str(e)[:300])
                return {}
            data = extract_json(raw)
            if isinstance(data, dict):
                return data
            _log(agent_name, "schema_retry", attempt=attempt + 1,
                 error="response was not parseable JSON",
                 head=(raw or "")[:160])
            prompt = (base + "\n\nYour previous response could not be parsed as JSON. "
                             "Return ONLY a JSON object matching the schema - no prose, "
                             "no markdown fences, nothing before or after the object.")
        _log(agent_name, "gave_up", reason="no parseable JSON after 3 attempts")
        return {}

    return _dispatch


def new_loop(store: Optional[Store] = None, dispatch: Optional[Dispatch] = None,
             **budget) -> InvestigationLoop:
    return InvestigationLoop(store=store or MemoryStore(),
                             dispatch=dispatch or (lambda *a: {}),
                             budget=Budget(**budget))
