"""Hypothesis consolidation — pool evidence without collapsing disagreement.

THE PROBLEM, AND THE CORRECTION TO HOW WE FIRST DESCRIBED IT
---------------------------------------------------------------------------
At a 90-dispatch budget the fleet produced four separate hypotheses about the
same figures (2,853,659 / 2,856,659 / $1,170,000 across four counterparties),
none clearing 0.55. The obvious reading was "it says the same thing four times
and half-believes each," and the obvious fix was to merge them.

That reading was wrong, and it is worth recording why, because acting on it
would have broken the system. Read the four claims:

  0.55  "...are the result of standardized, templated commercial agreements"
  0.50  "...had an implied offering price of $0.41, calculated by dividing..."
  0.35  "...represent an artificial revenue generation scheme"
  0.30  "artificially inflated its reported revenues... repeated identical..."
  0.20  "...are clerical copy-paste errors made during preparation of the 10-Q"

Those are not duplicates. They are three INCOMPATIBLE explanations of one set of
facts — innocent, neutral-arithmetic, and wrongdoing — which is precisely what a
fleet with a dedicated innocent-explanation mandate is supposed to produce.
Merging them would have deleted the disagreement the architecture exists to
create, and it would have looked like an improvement on every metric we track.

Only the 0.35 and 0.30 claims share a stance, so those looked like the genuine
duplicate pair. They are not either. One is specific to four named clients; the
other is a broader claim that subsumes it as one of several supports. Lexical
similarity 0.09, zero shared figures.

So we measured the whole question instead of assuming it: across 56 hypothesis
pairs from six live runs, ZERO merge under this rule. The fleet is not
duplicating. It is producing distinct claims at different scopes and stances,
which is what an adversarial investigation looks like. The fragmentation
diagnosis was wrong.

This module ships anyway, as a guard rather than a fix. It costs nothing per
run, it is fully tested, and if a future prompt or budget change does start
producing true duplicates we would rather they be merged deliberately than
discovered on camera. Its actual value so far has been the negative result and
the stance gate below - a reminder in code of the merge that must never happen.

THE RULE
---------------------------------------------------------------------------
Two hypotheses merge only if ALL of:

  1. Same STANCE. A wrongdoing claim never merges with an innocent one, whatever
     their wording overlap. This is a hard gate, checked first, and it is the
     only part of this module that really matters.
  2. Shared FIGURES. They are about the same numbers, not merely the same topic.
  3. Lexical SIMILARITY above a threshold, on content words.

Confidence after a merge is the MAXIMUM of the two, never the sum and never a
boost. Two formulations drawn from one corpus by one model are not independent
observations, so there is no sound way to combine them into greater certainty.
What merging legitimately does is pool the SUPPORTING EVIDENCE, so the Skeptic
attacks one claim backed by thirty citations instead of two claims backed by one
and twenty-nine. If the claim deserves higher confidence, the Skeptic raises it
on the merits.

Every merge is logged with both claim texts. A consolidation that cannot be read
back and disputed is just quiet deletion.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

# Stance markers. Deliberately narrow: these are the words that carry an
# accusation or an exoneration, not general financial vocabulary.
WRONGDOING = (
    "artificial", "artificially", "inflated", "inflate", "sham", "fabricated",
    "fictitious", "bogus", "improper", "improperly", "misrepresent",
    "misrepresented", "misstated", "overstated", "not genuine", "non-arm",
    "non-arms", "undisclosed", "concealed", "disguised", "scheme", "fraud",
    "fraudulent", "manipulat", "circular", "self-dealing", "round-trip",
)
INNOCENT = (
    "legitimate", "standard", "standardized", "ordinary", "customary",
    "genuine", "bona fide", "routine", "normal", "clerical", "innocent",
    "consistent with industry", "common practice", "typical", "benign",
    "good faith", "inadvertent", "error", "errors", "mistake",
)

STOP = set("""a an the and or of to in on for with by from as at is are was were be been
being that this these those it its their his her they them we our us you your which who
whom whose what when where how why not no nor but if then than so such can could may
might must shall should will would do does did have has had over under between during
company companies inc llc corp reported report reporting financial financials
""".split())

WORD = re.compile(r"[a-z][a-z\-']{2,}")
FIGURE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\$\s?\d[\d,.]*|\b\d+(?:\.\d+)?%")

SIMILARITY_THRESHOLD = 0.34   # Jaccard on content words
STANCE_MARGIN = 2             # clear margin required when signals are mixed
MIN_SHARED_FIGURES = 1


def stance(claim: str) -> str:
    """ASSERTS_WRONGDOING, ASSERTS_INNOCENT, NEUTRAL, or AMBIGUOUS.

    A bare majority of markers is not enough to call a stance. "The standard
    practice was an artificial scheme" carries two accusation words and one
    exoneration word; reading that as an accusation on a 2-1 count and merging
    on the result is precisely the kind of confident guess this module must not
    make. Mixed signals without a clear margin return AMBIGUOUS, which merges
    with nothing at all - not even another AMBIGUOUS claim.
    """
    t = (claim or "").lower()
    w = sum(1 for k in WRONGDOING if k in t)
    i = sum(1 for k in INNOCENT if k in t)
    if w and not i:
        return "ASSERTS_WRONGDOING"
    if i and not w:
        return "ASSERTS_INNOCENT"
    if not w and not i:
        return "NEUTRAL"
    if w - i >= STANCE_MARGIN:
        return "ASSERTS_WRONGDOING"
    if i - w >= STANCE_MARGIN:
        return "ASSERTS_INNOCENT"
    return "AMBIGUOUS"


def content_words(claim: str) -> set:
    return {w for w in WORD.findall((claim or "").lower()) if w not in STOP}


def figures(claim: str) -> set:
    """Normalised numeric tokens. '$1,170,000' and '1,170,000' are one figure."""
    out = set()
    for f in FIGURE.findall(claim or ""):
        n = f.replace("$", "").replace(",", "").strip()
        if n.endswith("%"):
            out.add(n)
            continue
        try:
            v = float(n)
        except ValueError:
            continue
        # Bare small integers (years, counts of parties) carry no identity.
        if v >= 1000:
            out.add(f"{v:.0f}")
    return out


def similarity(a: str, b: str) -> float:
    x, y = content_words(a), content_words(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def should_merge(a: dict, b: dict) -> Tuple[bool, str]:
    """Returns (merge?, reason). The reason is logged either way."""
    ca, cb = a.get("claim", ""), b.get("claim", "")
    sa, sb = stance(ca), stance(cb)
    if sa == "AMBIGUOUS" or sb == "AMBIGUOUS":
        return False, "stance unreadable — a claim we cannot classify is never merged"
    if sa != sb:
        return False, f"different stance ({sa} vs {sb}) — competing explanations are the point"
    shared = figures(ca) & figures(cb)
    if len(shared) < MIN_SHARED_FIGURES:
        return False, "no shared figures — same topic is not the same claim"
    sim = similarity(ca, cb)
    if sim < SIMILARITY_THRESHOLD:
        return False, f"similarity {sim:.2f} below {SIMILARITY_THRESHOLD}"
    return True, (f"same stance {sa}, {len(shared)} shared figure(s) "
                  f"{sorted(shared)[:3]}, similarity {sim:.2f}")


def merge(keep: dict, absorb: dict) -> dict:
    """Fold `absorb` into `keep`. Evidence unions; confidence takes the max.

    Not the sum, and not a boost. Two phrasings produced by one model over one
    corpus are not independent measurements, and treating them as such would
    manufacture confidence out of repetition - the exact failure this project
    exists to refuse.
    """
    out = dict(keep)
    for field in ("supporting", "contradicting", "unresolved"):
        merged, seen = [], set()
        for v in list(keep.get(field) or []) + list(absorb.get(field) or []):
            k = str(v).strip().lower()
            if k and k not in seen:
                seen.add(k)
                merged.append(v)
        if merged:
            out[field] = merged
    ck, ca = keep.get("confidence"), absorb.get("confidence")
    vals = [c for c in (ck, ca) if isinstance(c, (int, float))]
    if vals:
        out["confidence"] = max(vals)
    out["merged_from"] = list(keep.get("merged_from") or []) + [
        {"id": absorb.get("id"), "claim": absorb.get("claim", ""),
         "confidence": ca}]
    return out


def consolidate(hypotheses: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Merge same-stance duplicates. Returns (kept, merge_log).

    Order matters only for which id survives: the highest-confidence member of a
    duplicate group becomes canonical, so downstream verdicts land on the
    strongest formulation.
    """
    ordered = sorted(hypotheses,
                     key=lambda h: -(h.get("confidence") or 0.0))
    kept: List[dict] = []
    log: List[dict] = []
    for h in ordered:
        target = None
        for k in kept:
            ok, why = should_merge(k, h)
            if ok:
                target, reason = k, why
                break
        if target is None:
            kept.append(dict(h))
            continue
        merged = merge(target, h)
        kept[kept.index(target)] = merged
        log.append({"kept": target.get("id"), "absorbed": h.get("id"),
                    "reason": reason,
                    "kept_claim": target.get("claim", "")[:160],
                    "absorbed_claim": h.get("claim", "")[:160]})
    return kept, log
