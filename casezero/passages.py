"""Passage selection — send the fleet the relevant part of a filing, not the front.

THE BUG THIS EXISTS TO FIX
---------------------------------------------------------------------------
The dispatcher used to hand each selected document to the agent as
`open(f).read()[:char_cap]` — the first 40,000 characters. SEC filings put the
financial statement notes at the END. In the FY2023 10-K, a 320,968-character
document, the sentence

    "In April 2023, the Company received 2,853,659 units of HeadFarm LLC as a
     payment for services rendered..."

begins at character **302,971**. Under a 40,000-character head cut, the fleet had
never seen it. Not in one run, not at budget 40, not at budget 90, not once
across every live run we have logged.

Everything we chased for two days traces back to this:

  * "Verbatim sentences containing '2,853,659' cannot be directly extracted from
    the body text of the filings because the text is truncated after Note 3."
    We logged that as a hallucination and built a guard to catch its class. It
    was not a hallucination. It was an accurate report of the agent's own
    context window, and the agent was right while we were wrong.
  * The seeded ledger citations pointed at real sentences the fleet could not
    reach, so it discounted them.
  * Recovery sat near 18% across four scored runs no matter what we changed,
    because none of the changes touched the thing that was actually broken.

Relevance scoring had the same defect from the other end: documents were ranked
by matching the query against `read(8000)`, i.e. the cover page, so a filing was
judged on its letterhead rather than its contents.

THE FIX
---------------------------------------------------------------------------
Score over the whole document, then send WINDOWS around the matches instead of
the head. Elisions are marked explicitly, because an agent that cannot tell
truncated text from complete text will keep drawing conclusions about absence -
which is exactly the failure mode we spent a day mis-diagnosing.
"""
from __future__ import annotations
import re
from typing import Iterable, List, Optional, Tuple

# Figures are the highest-value selectors: they are rare, exact, and they are
# what the deterministic screens hand over.
FIGURE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")
TERM = re.compile(r"[A-Za-z][A-Za-z0-9]{3,}")

STOP = set("""the and for with from that this have been were was are which their they
company companies inc llc corp report reports reported filing filings financial
statement statements period periods year years quarter quarters what when where
identify determine whether across between during before after any all more most
""".split())

HEAD_CHARS = 1500       # cover page: form type, period, registrant
WINDOW = 2600           # characters either side of a match cluster
ELISION = "\n[... {n:,} characters omitted ...]\n"


def query_terms(*texts: str, extra: Iterable[str] = ()) -> List[str]:
    """Selectors drawn from the lead question and current state.

    Figures first and de-duplicated: '2,853,659' locates the decisive paragraph
    in one hop, where a word like 'revenue' matches five hundred places.
    """
    figs, words = [], []
    for t in texts:
        if not t:
            continue
        for f in FIGURE.findall(t):
            if f not in figs:
                figs.append(f)
        for w in TERM.findall(t):
            lw = w.lower()
            if lw not in STOP and lw not in words:
                words.append(lw)
    for e in extra:
        e = str(e).strip()
        if e and e not in figs:
            figs.append(e)
    return figs + words


def find_spans(text: str, terms: List[str], max_hits_per_term: int = 6
               ) -> List[Tuple[int, int, str]]:
    """(start, end, term) for term occurrences, searched over the WHOLE text."""
    low = text.lower()
    spans = []
    for t in terms:
        needle = t.lower()
        if len(needle) < 4:
            continue
        start, n = 0, 0
        while n < max_hits_per_term:
            i = low.find(needle, start)
            if i < 0:
                break
            spans.append((i, i + len(needle), t))
            start = i + len(needle)
            n += 1
    return sorted(spans)


def _merge(windows: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for lo, hi in sorted(windows):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def select(text: str, terms: List[str], budget: int = 40000,
           window: int = WINDOW, head: int = HEAD_CHARS) -> Tuple[str, dict]:
    """Return (excerpt, stats). Windows around matches, plus a short head.

    Falls back to the head of the document when nothing matches, which is the
    old behaviour and the right behaviour when there is no signal to aim at.
    """
    if len(text) <= budget:
        return text, {"mode": "full", "chars": len(text), "of": len(text),
                      "matches": 0, "windows": 1}

    spans = find_spans(text, terms)
    if not spans:
        return (text[:budget],
                {"mode": "head", "chars": min(budget, len(text)), "of": len(text),
                 "matches": 0, "windows": 1})

    wins = _merge([(max(0, s - window), min(len(text), e + window)) for s, e, _ in spans])

    # Head first, so the excerpt always identifies which filing it came from.
    keep: List[Tuple[int, int]] = []
    used = 0
    if head:
        keep.append((0, min(head, len(text))))
        used += min(head, len(text))

    # Densest windows first: a window holding several distinct matches is where
    # the answer is, and a fixed budget should buy those before anything else.
    def density(w):
        lo, hi = w
        return -sum(1 for s, _, _ in spans if lo <= s < hi)

    for lo, hi in sorted(wins, key=density):
        if used >= budget:
            break
        take = min(hi - lo, budget - used)
        if take <= 0:
            break
        keep.append((lo, lo + take))
        used += take

    keep = _merge(keep)
    parts, prev = [], 0
    for lo, hi in keep:
        if lo > prev:
            parts.append(ELISION.format(n=lo - prev))
        parts.append(text[lo:hi])
        prev = hi
    if prev < len(text):
        parts.append(ELISION.format(n=len(text) - prev))

    return "".join(parts), {"mode": "windows", "chars": used, "of": len(text),
                            "matches": len(spans), "windows": len(keep)}


def score_document(text: str, terms: List[str]) -> int:
    """Relevance over the WHOLE document.

    Scoring on `read(8000)` ranked filings by their cover page. Counting matches
    across the full text costs a substring scan and actually finds the filing
    that contains the answer.
    """
    low = text.lower()
    return sum(low.count(t.lower()) for t in terms if len(t) >= 4)
