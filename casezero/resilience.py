"""Failure handling for the dispatch layer.

Four things go wrong when you point a multi-agent fleet at a real model, and
they cost more build time than the agents themselves:

  1. The model returns prose, or JSON wrapped in markdown, or JSON with a
     preamble. -> extract_json
  2. The JSON parses but violates the schema. -> repair_loop feeds the actual
     validation error back and asks for a correction, rather than discarding
     an expensive call.
  3. The API rate-limits or 5xxs. -> retry_with_backoff, with jitter, and it
     does NOT retry deterministic 4xx failures that will fail identically.
  4. THE IMPORTANT ONE: the model fabricates a quote. -> CitationGuard checks
     every citation against the corpus at INGEST time, before the evidence can
     become a hypothesis.

(4) is the one that matters architecturally. Verifying citations only at
scoring time means a fabricated quote has already propagated through the
hypothesis graph and shaped the investigation. Checking at ingest means a
hallucination is quarantined where it happens, and the quarantine is an audit
event the fleet can show you.
"""
from __future__ import annotations
import json, random, re, time
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple


# ------------------------------------------------------------------ 1. JSON
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def extract_json(text: str) -> Optional[dict]:
    """Get a JSON object out of whatever the model actually said."""
    if not text:
        return None
    if isinstance(text, dict):
        return text

    candidates: List[str] = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1))
    candidates.append(text)

    # widest balanced {...} span in each candidate
    for c in candidates:
        c = c.strip()
        start = c.find("{")
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(c)):
            ch = c[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blob = c[start:i + 1]
                    for attempt in (blob, re.sub(r",\s*([}\]])", r"\1", blob)):
                        try:
                            return json.loads(attempt)
                        except Exception:
                            continue
                    break
    return None


# ---------------------------------------------------------------- 2. repair
def repair_loop(call: Callable[[str], str], prompt: str, model_cls,
                attempts: int = 3, on_event=None) -> Tuple[Optional[Any], List[str]]:
    """Call, validate against a pydantic model, and on failure feed the real
    validation error back for a correction. Returns (validated_or_None, errors)."""
    errors: List[str] = []
    p = prompt
    for i in range(attempts):
        raw = call(p)
        data = extract_json(raw)
        if data is None:
            err = "response was not valid JSON"
        else:
            try:
                return model_cls.model_validate(data), errors
            except Exception as e:
                err = str(e)[:900]
        errors.append(err)
        if on_event:
            on_event("schema_retry", {"attempt": i + 1, "error": err[:300]})
        p = (f"{prompt}\n\nYour previous response was rejected:\n{err}\n\n"
             f"Return ONLY a JSON object matching the schema. No prose, no markdown "
             f"fences, no explanation before or after.")
    return None, errors


# ----------------------------------------------------------------- 3. retry
TRANSIENT = ("429", "500", "502", "503", "504", "deadline", "timeout",
             "unavailable", "resource_exhausted", "overloaded", "connection")


def is_transient(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(t in s for t in TRANSIENT)


def retry_with_backoff(fn: Callable, attempts: int = 4, base: float = 1.5,
                       cap: float = 30.0, on_event=None, sleep=time.sleep):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if not is_transient(e) or i == attempts - 1:
                raise
            delay = min(cap, base * (2 ** i)) * (0.6 + 0.8 * random.random())
            if on_event:
                on_event("backoff", {"attempt": i + 1, "sleep": round(delay, 2),
                                     "error": str(e)[:200]})
            sleep(delay)
    raise last  # pragma: no cover


# ------------------------------------------------------- 4. citation guard
class CitationGuard:
    """Verifies quotes against the corpus at ingest time.

    Evidence whose citations cannot be found is not silently dropped - it is
    DOWNGRADED and flagged, because 'the model asserted this without support'
    is itself a finding worth keeping in the audit trail.
    """

    def __init__(self, docs: Dict[str, str], fuzzy: float = 0.85):
        # docs: filename -> normalised full text
        self.docs = {k: self._norm(v) for k, v in docs.items()}
        self.fuzzy = fuzzy
        self.stats = {"checked": 0, "exact": 0, "fuzzy": 0, "bad_file": 0,
                      "not_found": 0, "quarantined": 0}

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip().lower()

    def check(self, citation: dict) -> Tuple[str, str]:
        fn = (citation.get("file") or "").split("/")[-1]
        q = self._norm(citation.get("quote", ""))
        self.stats["checked"] += 1
        if fn not in self.docs:
            self.stats["bad_file"] += 1
            return "BAD_FILE", f"no corpus document named {fn!r}"
        if not q:
            self.stats["not_found"] += 1
            return "NOT_FOUND", "empty quote"
        hay = self.docs[fn]
        if q in hay:
            self.stats["exact"] += 1
            return "EXACT", ""
        best = 0.0
        step = max(1, len(q) // 2)
        for i in range(0, max(1, len(hay) - len(q)), step):
            r = SequenceMatcher(None, q, hay[i:i + len(q)]).ratio()
            if r > best:
                best = r
            if best >= self.fuzzy:
                break
        if best >= self.fuzzy:
            self.stats["fuzzy"] += 1
            return "FUZZY", f"{best:.0%}"
        self.stats["not_found"] += 1
        return "NOT_FOUND", f"best {best:.0%}"

    def screen(self, result: dict, on_event=None) -> dict:
        """Screen an agent's output. Mutates evidence in place; returns result."""
        for ev in result.get("evidence", []) or []:
            cites = ev.get("citations") or []
            if not cites:
                continue
            kept, rejected = [], []
            for c in cites:
                verdict, detail = self.check(c)
                (kept if verdict in ("EXACT", "FUZZY") else rejected).append(
                    {**c, "_verdict": verdict, "_detail": detail})
            ev["citations"] = kept
            if rejected:
                ev["quarantined_citations"] = rejected
                # A DIRECT claim with no surviving citation is not DIRECT.
                if not kept and ev.get("tier") == "DIRECT":
                    ev["tier"] = "INFERRED"
                    ev["integrity_flag"] = "unverifiable_citation"
                self.stats["quarantined"] += len(rejected)
                if on_event:
                    on_event("citation_quarantine", {
                        "evidence": ev.get("id"),
                        "rejected": len(rejected),
                        "detail": [f"{r['_verdict']}: {r.get('file','')}" for r in rejected],
                        "downgraded": ev.get("integrity_flag") == "unverifiable_citation",
                    })
        return result

    def report(self) -> dict:
        c = self.stats["checked"]
        good = self.stats["exact"] + self.stats["fuzzy"]
        return {**self.stats, "accuracy": (good / c) if c else None}


def load_corpus_docs(corpus_dir: str = "corpus") -> Dict[str, str]:
    import os
    out = {}
    for fn in os.listdir(corpus_dir):
        if fn.endswith(".txt"):
            out[fn] = open(os.path.join(corpus_dir, fn), errors="replace").read()
    return out


class CoverageGuard:
    """The inverse of CitationGuard: checks what the model says ISN'T there.

    CitationGuard catches a fabricated quote. It cannot catch the opposite
    failure, and the opposite failure is just as damaging.

    We measured it. Raising the dispatch budget from 40 to 90 - expecting the
    fleet to finally reach its own stopping point - instead DROPPED recovery
    against the withheld complaint from 18.8% to 12.5%, and produced findings
    like:

        "The Form 10-K filings for the fiscal years ended April 30, 2022, 2023
         and 2024 are absent from the corpus."   (confidence 0.30, 0 citations)

    The FY2022 and FY2023 10-Ks are in the corpus. The fleet is shown 8 of 71
    documents per call, so with more dispatches it accumulates more "I looked
    and did not find it" and eventually states absence as fact. The Skeptic then
    uses those claims to attack the true hypothesis: the correct core conclusion
    fell from 0.75 to 0.35 while the innocent explanation rose to 0.60. More
    budget bought more confident ignorance.

    A claim of absence is checkable against the corpus index for free, so it
    should never be taken on trust. Findings are FLAGGED rather than deleted -
    "the fleet asserted an absence that is contradicted by the record" belongs
    in the audit trail, exactly like a quarantined citation.

    A CORRECTION, recorded because it changes how much credit this guard
    deserves. We later found the dispatcher was sending each document as
    `read()[:40000]` - the FIRST 40,000 characters - while SEC filings put the
    financial notes at the END. The fleet's complaint was therefore half right:
    the DOCUMENTS were in the corpus, so "absent from the corpus" was false and
    this guard is correct to flag it, but the CONTENT genuinely was not in its
    context window. Its sibling claim, "the text is truncated after Note 3", was
    an accurate report we logged as a hallucination. See casezero/passages.py.

    The lesson we would keep: when an agent reports that it cannot find
    something, check your retrieval before you check its honesty.
    """

    # Only explicit absence assertions. Hedged language ("may not include",
    # "unclear whether") is a legitimate expression of uncertainty and is left
    # alone; flagging it would punish the fleet for being appropriately careful.
    ABSENCE = re.compile(
        r"\b(?:are|is|were|was)\s+(?:entirely\s+|completely\s+)?absent\b"
        r"|\bnot\s+(?:present|included|available|found)\s+in\b"
        r"|\b(?:do|does|did)\s+not\s+(?:appear|exist)\s+in\b"
        r"|\bcannot\s+be\s+(?:found|located|extracted)\b"
        r"|\bmissing\s+from\s+the\s+(?:corpus|filings|record)\b"
        r"|\bno\s+(?:such\s+)?(?:filing|document)s?\s+(?:exist|are\s+present)\b",
        re.I)

    # Artefacts a claim of absence usually names.
    FORM = re.compile(r"\bForm\s+(10-K|10-Q|8-K|S-1(?:/A)?|DEF\s*14A)\b", re.I)
    FISCAL = re.compile(r"fiscal year(?:s)?\s+ended\s+([A-Z][a-z]+ \d{1,2},\s*\d{4})", re.I)
    NAMED = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?: [A-Z][A-Za-z0-9]{2,}){0,2}) "
                       r"(LLC|Inc\.?|Corp\.?)(?![A-Za-z])")

    def __init__(self, docs: Dict[str, str]):
        self.filenames = list(docs)
        self.docs = {k: re.sub(r"\s+", " ", v).lower() for k, v in docs.items()}
        self.stats = {"checked": 0, "absence_claims": 0, "contradicted": 0}

    # A referent inside a qualifying phrase is NOT the thing being called absent.
    # "The details of the offerings for CountSharp LLC are absent" is TRUE - the
    # offering details really are outside this corpus - even though CountSharp
    # itself appears in eleven filings. Flagging that would make the guard a
    # liar in exactly the way it exists to prevent. Only the subject head, the
    # text before the first qualifying preposition, yields a hard contradiction.
    QUALIFIER = re.compile(r"\b(?:of|for|regarding|concerning|about|associated with|"
                           r"including|relating to|related to)\b", re.I)

    def _subject_head_end(self, text: str) -> int:
        m = self.QUALIFIER.search(text)
        return m.start() if m else len(text)

    def _present(self, needle: str) -> List[str]:
        n = needle.lower().strip()
        return [f for f, t in self.docs.items() if n in t]

    def check(self, text: str) -> List[dict]:
        """Contradictions between an absence claim and the corpus index."""
        self.stats["checked"] += 1
        if not text or not self.ABSENCE.search(text):
            return []
        self.stats["absence_claims"] += 1

        head_end = self._subject_head_end(text)
        out = []
        for m in self.FORM.finditer(text):
            form = re.sub(r"\s+", "", m.group(1)).upper()
            hits = [f for f in self.filenames
                    if form.replace("/", "") in f.upper().replace("/", "")]
            if hits:
                out.append({"kind": "form", "referent": m.group(0),
                            "severity": "HARD" if m.start() < head_end else "SOFT",
                            "found_in": sorted(hits)[:4], "count": len(hits)})
        for m in self.NAMED.finditer(text):
            name = f"{m.group(1)} {m.group(2)}"
            hits = self._present(name)
            if hits:
                out.append({"kind": "entity", "referent": name,
                            "severity": "HARD" if m.start() < head_end else "SOFT",
                            "found_in": sorted(hits)[:4], "count": len(hits)})

        # De-duplicate by referent; one claim naming the same thing twice is one
        # contradiction, not two.
        seen, uniq = set(), []
        for o in out:
            k = o["referent"].lower()
            if k not in seen:
                seen.add(k); uniq.append(o)
        if any(o["severity"] == "HARD" for o in uniq):
            self.stats["contradicted"] += 1
        return uniq

    def report(self) -> dict:
        a = self.stats["absence_claims"]
        return {**self.stats,
                "contradiction_rate": (self.stats["contradicted"] / a) if a else None}
