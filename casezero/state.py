"""Investigation state + work queue.

Two backends behind one interface:
  MemoryStore    - no dependencies, used by tests and local runs
  FirestoreStore - Cloud Run / Firestore, satisfies the hackathon's
                   "at least one Google Cloud infrastructure service"

The queue is deliberately part of the STATE, not a side channel. Agents create
work for other agents by appending leads; the orchestrator only ever reads the
queue. That is what makes the fleet asynchronous rather than a fixed pipeline,
and it is the property the Fortified Enterprise Fleet track is asking for.

Every mutation appends to an immutable event log. The log IS the audit trail and
the live board's event stream - one structure, two consumers.
"""
from __future__ import annotations
import json, os, time, uuid
from typing import Any, Dict, Iterator, List, Optional


def _now() -> float:
    return time.time()


class Store:
    """Interface. Both backends implement exactly this."""

    def append_event(self, actor: str, kind: str, payload: dict) -> dict: ...
    def events(self, since: float = 0.0) -> List[dict]: ...
    def put(self, coll: str, doc_id: str, data: dict) -> None: ...
    def get(self, coll: str, doc_id: str) -> Optional[dict]: ...
    def all(self, coll: str) -> List[dict]: ...
    def push_lead(self, lead: dict) -> None: ...
    def pop_lead(self) -> Optional[dict]: ...
    def counts(self) -> Dict[str, int]: ...


class MemoryStore(Store):
    def __init__(self, case_id: str = "0001"):
        self.case_id = case_id
        self._log: List[dict] = []
        self._coll: Dict[str, Dict[str, dict]] = {}
        self._leads: List[dict] = []

    def append_event(self, actor, kind, payload):
        ev = dict(id=str(uuid.uuid4()), ts=_now(), actor=actor, kind=kind, payload=payload)
        self._log.append(ev)
        return ev

    def events(self, since=0.0):
        return [e for e in self._log if e["ts"] > since]

    def put(self, coll, doc_id, data):
        self._coll.setdefault(coll, {})[doc_id] = data

    def get(self, coll, doc_id):
        return self._coll.get(coll, {}).get(doc_id)

    def all(self, coll):
        return list(self._coll.get(coll, {}).values())

    def push_lead(self, lead):
        # highest priority first; stable for equal priority
        self._leads.append(lead)
        self._leads.sort(key=lambda l: -float(l.get("priority", 0.5)))

    def pop_lead(self):
        return self._leads.pop(0) if self._leads else None

    def counts(self):
        return {
            "evidence": len(self._coll.get("evidence", {})),
            "hypotheses": len(self._coll.get("hypotheses", {})),
            "verdicts": len(self._coll.get("verdicts", {})),
            "open_leads": len(self._leads),
            "events": len(self._log),
        }


def _where(query, field: str, op: str, value):
    """Compatibility shim.

    google-cloud-firestore >= 2.11 warns on positional where() and wants
    `filter=FieldFilter(...)`. Emulators and test doubles generally only
    implement the positional form. Prefer the modern API, fall back quietly.
    """
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        return query.where(filter=FieldFilter(field, op, value))
    except Exception:
        return query.where(field, op, value)


class FirestoreStore(Store):
    """Same interface, backed by Firestore.

    Exercised against an in-memory Firestore double (tests/test_firestore.py) -
    that catches API-shape bugs but NOT real-service behaviour: security rules,
    composite-index requirements, or contention. Verify against a real project
    before the demo.
    """

    def __init__(self, case_id: str = "0001", project: Optional[str] = None, db=None):
        if db is None:
            from google.cloud import firestore  # import cost stays local
            db = firestore.Client(project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.case_id = case_id
        self.db = db
        self.root = self.db.collection("cases").document(case_id)

    def _c(self, name):
        return self.root.collection(name)

    def append_event(self, actor, kind, payload):
        ev = dict(id=str(uuid.uuid4()), ts=_now(), actor=actor, kind=kind, payload=payload)
        self._c("events").document(ev["id"]).set(ev)
        return ev

    def events(self, since=0.0):
        q = _where(self._c("events"), "ts", ">", since).order_by("ts")
        return [d.to_dict() for d in q.stream()]

    def put(self, coll, doc_id, data):
        self._c(coll).document(doc_id).set(data)

    def get(self, coll, doc_id):
        d = self._c(coll).document(doc_id).get()
        return d.to_dict() if d.exists else None

    def all(self, coll):
        # Skip empty documents. In Firestore a document can exist as a pure
        # parent of a subcollection with no fields of its own; such a phantom
        # is not an investigation object and must not be counted as one.
        return [d for d in (doc.to_dict() for doc in self._c(coll).stream()) if d]

    def push_lead(self, lead):
        self._c("leads").document(lead["id"]).set({**lead, "status": "open"})

    def pop_lead(self):
        """Claim the highest-priority open lead.

        Deliberately NOT `where(...).order_by(...)`. That combination requires a
        hand-built composite index in real Firestore, and the first production
        deploy died on exactly that: `400 The query requires an index`. An
        in-memory test double will never catch it, because doubles don't
        enforce indexes.

        The lead queue holds tens of documents, not millions, so filtering
        server-side and ordering in Python costs nothing and removes a
        deploy-time dependency. If this ever grows to thousands of open leads,
        add the composite index and restore the server-side sort.

        Read-then-update is not atomic. With one orchestrator that is fine, and
        one orchestrator is the current design (max-instances=1). Two workers
        would need a transaction or they will claim the same lead.
        """
        docs = [(d.id, d.to_dict()) for d in
                _where(self._c("leads"), "status", "==", "open").stream()]
        docs = [(i, v) for i, v in docs if v]
        if not docs:
            return None
        doc_id, lead = max(docs, key=lambda kv: float(kv[1].get("priority", 0.5)))
        self._c("leads").document(doc_id).update({"status": "taken"})
        return lead

    def counts(self):
        n = lambda c: len(self.all(c))  # noqa: E731  (shares the phantom filter)
        open_leads = sum(1 for d in _where(self._c("leads"), "status", "==", "open").stream()
                         if d.to_dict())
        return {"evidence": n("evidence"), "hypotheses": n("hypotheses"),
                "verdicts": n("verdicts"), "open_leads": open_leads, "events": n("events")}


def make_store(case_id: str = "0001") -> Store:
    """Firestore when running on Cloud Run, memory otherwise."""
    if os.environ.get("CASEZERO_BACKEND", "").lower() == "firestore":
        return FirestoreStore(case_id)
    return MemoryStore(case_id)
