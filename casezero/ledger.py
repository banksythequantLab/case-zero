"""The forensic accountant's pass — rebuild the books, then look for irregularities.

This is not an agent and must never be one. Everything here has exactly one right
answer, so a model would only add cost, latency and the run-to-run variance we
measured at 1-of-3 claims reproducing. Arithmetic belongs in code.

WHAT THIS ACTUALLY DOES, AND WHY THE FIRST VERSION MISSED IT
---------------------------------------------------------------------------
The first version of this module hunted anomalies: figures that repeat across
counterparties. It worked, and it found a genuine fingerprint — four companies
transferring byte-identical amounts. But a fingerprint is not the books. Asked to
act like an accountant, it answered like a fraud examiner glancing at one ledger
line, and it ranked a $50,000 figure recurring across many customers as WEAK
noise. That figure is not noise. It is the CONTROL GROUP: what the company's own
arm's-length customers paid for the same service. Throwing it away discarded the
most important comparison available.

So this module now does what an accountant does first — build the customer
ledger, total it, and reconcile it against reported revenue — and only then looks
for anomalies inside it.

Four passes:

1. ENGAGEMENT REGISTER. Every consulting engagement disclosed in the filings:
   who, how much, and CRITICALLY in what form. Equity-settled engagements
   ("received N units of X LLC ... satisfied an accounts receivable balance of
   $Y") are separated from cash engagements ("a $40,000 fee"). One engagement is
   restated in every subsequent filing, so the register de-duplicates by
   counterparty and reports first appearance.

2. DISCLOSED CONCENTRATION. The company names its own largest customers and their
   share of revenue in the S-1/As. This is the issuer's own admission, and it
   reaches counterparties the Investments note never mentions.

3. RECONCILIATION. Equity-settled consideration against reported revenue for the
   same window. This is the number the whole case turns on: what share of revenue
   never arrived as money.

4. PRICING. The company publishes its own rate card. Compare it to what the
   equity-settled counterparties were billed. Same service, two prices.

Anomaly detection (repeated figures, near-miss variants) is retained as a
SUPPORTING section. It is real and it is corroborative; it is not the headline.

Everything is emitted as INFERRED evidence. Arithmetic from filed documents is
grounds for a conclusion, but the conclusion is the fleet's to argue, not this
module's to assert.
"""
from __future__ import annotations
import os, re, statistics
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------- patterns

AMOUNT = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b")

# The trailing (?![A-Za-z]) is load-bearing: without it `Inc\.?` matches inside
# "Equity Incentive Plan" and the corpus sprouts a counterparty called
# "Equity Inc" carrying 119 figures.
_SUFFIX = r"(LLC|L\.L\.C\.|Inc\.?|Corp\.?|Corporation|Ltd\.?)(?![A-Za-z])"
ENTITY = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?: [A-Z][A-Za-z0-9]{2,}){0,2}) " + _SUFFIX)
ALIAS = re.compile(ENTITY.pattern + r"\.?\s*\(\s*[“\"']([A-Za-z][A-Za-z0-9 .\-]{1,24})[”\"']\s*\)")

# "received 2,853,659 units of HeadFarm LLC as a payment for services rendered"
EQUITY_DEAL = re.compile(
    r"received\s+([\d,]+)\s+(?:membership interest\s+)?units\s+of\s+"
    r"(.{3,45}?)\s*(?:\(|as\s+(?:a\s+)?payment)", re.I)

# "...satisfied an accounts receivable balance of $1,170,000."
AR_SETTLED = re.compile(r"satisfied an accounts receivable balance\s+of\s+\$?"
                        r"([\d,]+)(?![\d,])", re.I)

# "The units are valued at $0.41 per unit"
UNIT_PRICE = re.compile(r"valued at \$?([\d.]+)\s+per unit", re.I)

# "consulting agreement with Vymedic, Inc. for a $40,000 fee over a 5-month period"
CASH_DEAL = re.compile(r"consulting (?:agreement|contract) with\s+(.{3,60}?)"
                       r"\s+for a \$\s?([\d,]+)\s*fee"
                       r"(?:\s+over a\s+([a-z0-9\-]+\s*\w*))?", re.I)

# "one customer, AceHedge LLC that constituted 37% of revenues"
CONCENTRATION = re.compile(r"customer,?\s+(.{3,40}?)\s+that constituted\s+(\d+)%\s+of revenue", re.I)
PERIOD = re.compile(r"(?:For|during) the ([a-z\- ]+?(?:period|months?|year)[a-z ]*"
                    r"ended [A-Z][a-z]+ \d{1,2}, \d{4})")

# The company's own published price for the same service.
RATE_CARD = re.compile(r"charges a \$([\d,]+)(?:\s*to\s*\$([\d,]+))?\s*engagement fee", re.I)

SELF_TERMS = ("netcapital", "funding portal", "advisors", "systems")
ALIAS_STOP = {"the company", "company", "we", "us", "registration statement",
              "offering", "the offering", "our company", "the notes"}

STRONG_SIGNIFICANCE = 3


# ----------------------------------------------------------------------- utils

def _num(s: str) -> float:
    return float(str(s).replace(",", "").replace("$", "").strip())


def _read(path: str) -> str:
    with open(path, errors="replace") as fh:
        return fh.read()


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# A blank line is a hard boundary; a single newline is not. EDGAR wraps sentences
# mid-name ("Netcapital Funding\n Portal Inc"), so collapsing every newline is
# required - but collapsing blank lines too lets a name absorb whatever word
# ended the previous block ("Technology MustWatch LLC"). The pipe is outside the
# entity character set, so it breaks the chain.
_BLANK = re.compile(r"\n[ \t\xa0]*\n\s*")


def _flat_blocks(text: str) -> str:
    return _flat(_BLANK.sub(" | ", text))


def _is_self(name: str) -> bool:
    return any(t in name.lower() for t in SELF_TERMS)


def _clean(name: str) -> str:
    """Normalise a counterparty as the filings render it."""
    n = re.sub(r"\s+", " ", name).strip().strip(".,;:")
    n = re.sub(r"\s*\(.*$", "", n)
    return n


def _key(name: str) -> str:
    """Match 'Cust Corp.' to 'CustCorp' and 'RealWorld.net LLC' to 'RealWorld LLC'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def significant_digits(amount: str) -> int:
    """Digits remaining after stripping trailing zeros. 50,000 -> 1; 2,853,659 -> 7."""
    d = str(amount).replace(",", "").replace(".", "").lstrip("0").rstrip("0")
    return len(d) if d else 1


def _files(corpus_dir: str) -> List[str]:
    return sorted(f for f in os.listdir(corpus_dir) if f.endswith(".txt"))


def _filing_date(fn: str) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2})", fn)
    return m.group(1) if m else ""


def paragraphs(text: str, max_chars: int = 2500):
    for block in re.split(r"\n[ \t\xa0]*\n", text):
        p = _flat(block).strip()
        if p and len(p) <= max_chars:
            yield p


_SENT_START = re.compile(r"(?<=[.;])\s+(?=[A-Z(\"'“])")


def quote_span(flat_text: str, start: int, end: int, max_chars: int = 400) -> str:
    """The verbatim sentence(s) around a match, for use as a citation.

    Seeding a claim WITHOUT its source text is worse than not seeding it. We
    measured this: given the figure 2,853,659 and no quote, one live run spent
    its entire budget trying to re-derive the sentence from an eight-document
    sample, failed, and reported "these figures cannot be extracted from the
    filings" as a 0.95-confidence finding. The figures are in the filings. The
    fleet was simply never shown them.

    Input must be whitespace-flattened, which is also how CitationGuard
    normalises the corpus, so the returned quote verifies exactly.
    """
    lo = 0
    for m in _SENT_START.finditer(flat_text[:start]):
        lo = m.end()
    tail = flat_text[end:end + max_chars]
    m = _SENT_START.search(tail)
    hi = end + (m.start() + 1 if m else min(len(tail), max_chars))
    if hi - lo > max_chars:
        lo = max(lo, hi - max_chars)
    return flat_text[lo:hi].strip()


# ------------------------------------------------------------ 1. the register

def engagement_register(corpus_dir: str = "corpus") -> Dict[str, List[dict]]:
    """Every disclosed consulting engagement, split by how it was settled.

    A single engagement is restated in every later filing, so entries are
    de-duplicated by counterparty and stamped with the filing that first
    disclosed them.
    """
    equity: Dict[str, dict] = {}
    cash: Dict[str, dict] = {}

    for fn in _files(corpus_dir):
        date = _filing_date(fn)
        text = _flat(_read(os.path.join(corpus_dir, fn)))

        for m in EQUITY_DEAL.finditer(text):
            party = _clean(m.group(2))
            if not party or _is_self(party):
                continue
            tail = text[m.end():m.end() + 1200]
            ar = AR_SETTLED.search(tail)
            px = UNIT_PRICE.search(tail)
            end = m.end() + (ar.end() if ar else 0)
            row = {"counterparty": party,
                   "units": _num(m.group(1)),
                   "consideration": _num(ar.group(1)) if ar else None,
                   "unit_price": float(px.group(1)) if px else None,
                   "settled_in": "counterparty equity",
                   "citation": {"file": fn, "quote": quote_span(text, m.start(), end)},
                   "first_disclosed": date, "files": {fn}}
            prev = equity.get(_key(party))
            if prev is None:
                equity[_key(party)] = row
            else:
                prev["files"].add(fn)
                # Keep the earliest disclosure but fill gaps from later filings,
                # which often restate the same deal more completely.
                for f in ("consideration", "unit_price"):
                    if prev[f] is None:
                        prev[f] = row[f]

        for m in CASH_DEAL.finditer(text):
            party = _clean(m.group(1))
            if not party or _is_self(party):
                continue
            row = {"counterparty": party, "units": None,
                   "consideration": _num(m.group(2)), "unit_price": None,
                   "settled_in": "cash / cash and stock",
                   "term": (m.group(3) or "").strip(),
                   "citation": {"file": fn, "quote": quote_span(text, m.start(), m.end())},
                   "first_disclosed": date, "files": {fn}}
            prev = cash.get(_key(party))
            if prev is None:
                cash[_key(party)] = row
            else:
                prev["files"].add(fn)

    def _out(d):
        rows = []
        for r in d.values():
            r = dict(r)
            r["files"] = sorted(r["files"])
            r["filing_count"] = len(r["files"])
            rows.append(r)
        return sorted(rows, key=lambda r: -(r["consideration"] or 0))

    return {"equity": _out(equity), "cash": _out(cash)}


# ------------------------------------------------------- 2. disclosed concentration

def concentration(corpus_dir: str = "corpus") -> List[dict]:
    """The issuer naming its own largest customers and their share of revenue.

    Reaches counterparties the Investments note never mentions, because a company
    can disclose a customer concentration without ever describing the deal.
    """
    by_period: Dict[str, Dict[str, int]] = defaultdict(dict)
    cites: Dict[str, dict] = {}
    for fn in _files(corpus_dir):
        text = _flat(_read(os.path.join(corpus_dir, fn)))
        for m in CONCENTRATION.finditer(text):
            party = _clean(m.group(1))
            if not party or _is_self(party):
                continue
            pre = text[max(0, m.start() - 300):m.start()]
            periods = PERIOD.findall(pre)
            period = _clean(periods[-1]) if periods else "unspecified period"
            by_period[period][party] = int(m.group(2))
            cites.setdefault(period, {"file": fn,
                                      "quote": quote_span(text, m.start(), m.end())})

    out = []
    for period, parties in by_period.items():
        out.append({"period": period,
                    "customers": [{"counterparty": p, "pct": v}
                                  for p, v in sorted(parties.items(), key=lambda kv: -kv[1])],
                    "named_share_pct": sum(parties.values()),
                    "citation": cites.get(period)})
    return sorted(out, key=lambda r: -r["named_share_pct"])


_MONTHS = {"three": 3, "six": 6, "nine": 9, "twelve": 12}
_END = re.compile(r"ended ([A-Z][a-z]+) (\d{1,2}), (\d{4})")
_MON_N = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def _period_window(phrase: str) -> Optional[Tuple[str, int]]:
    """'six-month period ended October 31, 2023' -> ('2023-10-31', 6)."""
    e = _END.search(phrase)
    if not e:
        return None
    months = next((n for w, n in _MONTHS.items() if w in phrase.lower()), None)
    if months is None:
        months = 12 if "year" in phrase.lower() else None
    if months is None:
        return None
    return f"{e.group(3)}-{_MON_N[e.group(1)]:02d}-{int(e.group(2)):02d}", months


def value_concentration(conc: List[dict], quarters: List[dict]) -> dict:
    """Turn disclosed customer percentages into dollars.

    The Investments note describes the equity deals in dollars, but three
    customers appear ONLY in the concentration tables, as a percentage of
    revenue. An accountant does not leave them at "37%" - they multiply out
    against the revenue actually reported for that window.

    Double-counting is the trap. A six-month disclosure contains the three-month
    one, so per customer we keep only the LONGEST window disclosed and discard
    the rest. Values are approximate: the filings state whole percentages, so a
    37% figure carries about +/-0.5% of the window's revenue.

    `quarters` is forensic.revenue_timeline(...)["quarters"].
    """
    if not quarters:
        return {"customers": [], "total": 0.0, "note": "no reported revenue available"}

    def window_revenue(end: str, months: int) -> Optional[float]:
        ends = sorted(q["end"] for q in quarters)
        if end not in ends:
            return None
        n = months // 3
        idx = ends.index(end)
        if idx + 1 < n:
            return None
        chosen = ends[idx + 1 - n: idx + 1]
        return sum(q["revenue"] for q in quarters if q["end"] in chosen)

    best: Dict[str, dict] = {}
    for c in conc:
        w = _period_window(c["period"])
        if not w:
            continue
        end, months = w
        rev = window_revenue(end, months)
        if not rev:
            continue
        for cu in c["customers"]:
            k = _key(cu["counterparty"])
            # Longest window wins: it supersedes the shorter one it contains.
            if k in best and best[k]["months"] >= months:
                continue
            best[k] = {"counterparty": cu["counterparty"], "pct": cu["pct"],
                       "period_end": end, "months": months,
                       "window_revenue": rev,
                       "value": round(rev * cu["pct"] / 100, 0)}
    rows = sorted(best.values(), key=lambda r: -r["value"])
    return {"customers": rows, "total": sum(r["value"] for r in rows),
            "note": "derived: stated whole-percent share x reported revenue for the "
                    "same window; longest window per customer, shorter ones discarded"}


def counterparty_set(register: dict, conc: List[dict]) -> List[str]:
    """The full customer set, from both routes.

    Neither pass sees all of them. The Investments note describes the equity
    deals; the concentration tables name customers whose deals it never
    describes. The union is the customer base.
    """
    names: Dict[str, str] = {}
    for r in register["equity"] + register["cash"]:
        names.setdefault(_key(r["counterparty"]), r["counterparty"])
    for c in conc:
        for cu in c["customers"]:
            names.setdefault(_key(cu["counterparty"]), cu["counterparty"])
    return sorted(names.values())


# ------------------------------------------------------------ 3. reconciliation

def reconcile(register: dict, reported_revenue: Optional[float] = None,
              window: Optional[List[str]] = None,
              derived: Optional[dict] = None) -> dict:
    """Revenue attributable to named counterparties, against revenue reported.

    Two routes, deliberately kept as separate lines. The register is DISCLOSED -
    dollar amounts the filings state outright. `derived` is COMPUTED - customers
    the filings give only as a percentage, multiplied out. Merging them into one
    number would hide which half rests on an inference, and the whole point of
    this module is that a reader can see the arithmetic.

    `reported_revenue` comes from filed XBRL via forensic.revenue_timeline. It is
    passed in rather than fetched so this module stays offline and deterministic.
    """
    eq = [r for r in register["equity"] if r["consideration"]]
    cash = [r for r in register["cash"] if r["consideration"]]
    eq_total = sum(r["consideration"] for r in eq)
    cash_total = sum(r["consideration"] for r in cash)
    derived_total = float(derived["total"]) if derived else 0.0
    attributed = eq_total + derived_total

    out = {"equity_counterparties": len(eq), "equity_total": eq_total,
           "cash_counterparties": len(cash), "cash_total": cash_total,
           "derived_counterparties": len(derived["customers"]) if derived else 0,
           "derived_total": derived_total,
           "attributed_total": attributed,
           "reported_revenue": reported_revenue, "window": window,
           "equity_share_pct": None, "cash_share_pct": None,
           "attributed_share_pct": None, "overstatement_pct": None}
    if reported_revenue and reported_revenue > 0:
        out["equity_share_pct"] = round(eq_total / reported_revenue * 100, 1)
        out["cash_share_pct"] = round(cash_total / reported_revenue * 100, 1)
        out["attributed_share_pct"] = round(attributed / reported_revenue * 100, 1)
        residual = reported_revenue - attributed
        if residual > 0:
            # Strip the revenue that never arrived as cash: by what percentage
            # was the remainder inflated? This is the SEC's own framing.
            out["overstatement_pct"] = round(attributed / residual * 100, 0)
            out["revenue_excluding_attributed"] = residual
    return out


# ---------------------------------------------------------------- 4. pricing

def rate_card(corpus_dir: str = "corpus") -> List[dict]:
    """The company's own published price for the service it sells."""
    seen, out = set(), []
    for fn in _files(corpus_dir):
        text = _flat(_read(os.path.join(corpus_dir, fn)))
        for m in RATE_CARD.finditer(text):
            lo = _num(m.group(1))
            hi = _num(m.group(2)) if m.group(2) else lo
            if (lo, hi) in seen:
                continue
            seen.add((lo, hi))
            out.append({"low": lo, "high": hi, "first_disclosed": _filing_date(fn),
                        "citation": {"file": fn,
                                     "quote": quote_span(text, m.start(), m.end())}})
    return sorted(out, key=lambda r: r["low"])


def pricing(register: dict, cards: List[dict]) -> dict:
    """Same service, two prices. The spread is the finding."""
    eq = [r["consideration"] for r in register["equity"] if r["consideration"]]
    cash = [r["consideration"] for r in register["cash"] if r["consideration"]]
    out = {"equity_low": min(eq) if eq else None,
           "equity_high": max(eq) if eq else None,
           "equity_median": statistics.median(eq) if eq else None,
           "cash_low": min(cash) if cash else None,
           "cash_high": max(cash) if cash else None,
           "published_low": min((c["low"] for c in cards), default=None),
           "published_high": max((c["high"] for c in cards), default=None),
           "multiple_vs_published": None, "multiple_vs_cash": None}
    if out["equity_median"] and out["published_high"]:
        out["multiple_vs_published"] = round(out["equity_median"] / out["published_high"], 0)
    if out["equity_median"] and cash:
        out["multiple_vs_cash"] = round(out["equity_median"] / statistics.median(cash), 0)
    return out


# ------------------------------------------- supporting: repeated-figure anomaly

def discover_entities(corpus_dir: str = "corpus", min_files: int = 2
                      ) -> Tuple[Set[str], Dict[str, str]]:
    """Counterparties in >= `min_files` filings, plus alias -> canonical name."""
    seen: Dict[str, Set[str]] = defaultdict(set)
    alias: Dict[str, str] = {}
    for fn in _files(corpus_dir):
        text = _flat_blocks(_read(os.path.join(corpus_dir, fn)))
        for m in ENTITY.finditer(text):
            name = f"{m.group(1)} {m.group(2)}".strip()
            if not _is_self(name):
                seen[name].add(fn)
        for m in ALIAS.finditer(text):
            name = f"{m.group(1)} {m.group(2)}".strip()
            short = m.group(3).strip()
            if short.lower() in ALIAS_STOP or len(short) < 2:
                continue
            squashed = re.sub(r"[^a-z0-9]", "", name.lower())
            if len(short) > 5 and re.sub(r"[^a-z0-9]", "", short.lower()) not in squashed:
                continue
            alias.setdefault(short.lower(), name)
    ents = {n for n, files in seen.items() if len(files) >= min_files}
    return ents, {a: n for a, n in alias.items() if not _is_self(n)}


class _Matcher:
    def __init__(self, entities: Set[str], aliases: Dict[str, str]):
        self._low = [(n, n.lower()) for n in sorted(entities)]
        self._alias = [(re.compile(r"\b" + re.escape(a) + r"\b", re.I), n)
                       for a, n in aliases.items()]

    def mentions(self, paragraph: str) -> Set[str]:
        pl = paragraph.lower()
        hits = {n for n, nl in self._low if nl in pl}
        for rx, n in self._alias:
            if rx.search(paragraph):
                hits.add(n)
        return {h for h in hits if not _is_self(h)}


def repeated_figures(corpus_dir: str = "corpus",
                     entities: Optional[Set[str]] = None,
                     aliases: Optional[Dict[str, str]] = None,
                     min_parties: int = 3) -> List[dict]:
    """Amounts tied to several DISTINCT counterparties at paragraph level.

    The association unit took three attempts. A +/-300 character window gave 39
    hits and no signal - in a customer table every amount is "near" every
    customer. A 3-line window gave 8, of which 5 were wrong, because EDGAR
    hard-wraps and a wrapped summary sentence bleeds figures across entities. The
    paragraph works, but only once aliases count as mentions: one sentence
    ("...the MW and Chip securities") names two companies by short form and none
    in full, and on its own it fabricated a whole three-party cluster.
    """
    if entities is None or aliases is None:
        entities, aliases = discover_entities(corpus_dir)
    match = _Matcher(entities, aliases)

    tie: Dict[str, Set[str]] = defaultdict(set)
    where: Dict[str, Set[str]] = defaultdict(set)
    cites: Dict[str, List[dict]] = defaultdict(list)
    for fn in _files(corpus_dir):
        for para in paragraphs(_read(os.path.join(corpus_dir, fn))):
            hits = match.mentions(para)
            if len(hits) != 1:
                continue
            party = next(iter(hits))
            if party not in entities:
                continue
            for amt in AMOUNT.findall(para):
                if party not in tie[amt]:
                    # One exemplar sentence per (figure, party): enough for the
                    # fleet to verify the claim without re-reading the corpus.
                    i = para.find(amt)
                    cites[amt].append({"file": fn, "party": party,
                                       "quote": quote_span(para, i, i + len(amt))})
                tie[amt].add(party)
                where[amt].add(fn)

    out = []
    for amt, parties in tie.items():
        if len(parties) < min_parties:
            continue
        sig = significant_digits(amt)
        out.append({"amount": amt, "value": _num(amt),
                    "parties": sorted(parties), "party_count": len(parties),
                    "files": sorted(where[amt]), "significant_digits": sig,
                    "citations": cites[amt],
                    "significance": "STRONG" if sig >= STRONG_SIGNIFICANCE else "WEAK"})
    return sorted(out, key=lambda r: (-r["significant_digits"], -r["party_count"], -r["value"]))


def near_miss(repeats: List[dict], tolerance: float = 0.005) -> List[dict]:
    """Figures a hair apart across the same parties - a transcription error, or
    an attempt to make identical numbers look distinct."""
    out, seen = [], set()
    rows = sorted([r for r in repeats if r["significance"] == "STRONG"],
                  key=lambda r: r["value"])
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if b["value"] - a["value"] > a["value"] * tolerance:
                break
            key = (a["amount"], b["amount"])
            if key in seen or a["value"] == b["value"]:
                continue
            seen.add(key)
            out.append({"a": a["amount"], "b": b["amount"],
                        "delta": round(b["value"] - a["value"], 2),
                        "pct": round((b["value"] - a["value"]) / a["value"] * 100, 4),
                        "shared_parties": sorted(set(a["parties"]) & set(b["parties"])),
                        "citations": (a.get("citations", [])[:2]
                                      + b.get("citations", [])[:2])})
    return [o for o in out if o["shared_parties"]]


# --------------------------------------------------------------------- audit

def audit(corpus_dir: str = "corpus", reported_revenue: Optional[float] = None,
          window: Optional[List[str]] = None, min_parties: int = 3,
          quarters: Optional[List[dict]] = None) -> dict:
    reg = engagement_register(corpus_dir)
    conc = concentration(corpus_dir)
    cards = rate_card(corpus_dir)
    derived = value_concentration(conc, quarters or [])
    ents, aliases = discover_entities(corpus_dir)
    reps = repeated_figures(corpus_dir, ents, aliases, min_parties=min_parties)
    return {"register": reg,
            "rate_card_citations": [c["citation"] for c in cards if c.get("citation")],
            "concentration": conc,
            "derived_concentration": derived,
            "counterparties": counterparty_set(reg, conc),
            "reconciliation": reconcile(reg, reported_revenue, window, derived),
            "rate_card": cards,
            "pricing": pricing(reg, cards),
            "repeated_figures": reps,
            "strong_count": sum(1 for r in reps if r["significance"] == "STRONG"),
            "near_misses": near_miss(reps),
            "entities_discovered": len(ents),
            "aliases_resolved": len(aliases)}


# ------------------------------------------------------------------ evidence

def as_evidence(report: dict) -> List[dict]:
    """Seed evidence for the fleet, headline first.

    Ordered the way an accountant would brief it: the reconciliation, then the
    pricing spread, then the customer set, then the corroborating fingerprint.
    All INFERRED — this is arithmetic from filed documents, and what it means is
    the fleet's argument to make.
    """
    out: List[dict] = []
    rec, pr = report["reconciliation"], report["pricing"]

    if rec["equity_total"] and rec["equity_share_pct"] is not None:
        derived_clause = ""
        if rec["derived_total"]:
            derived_clause = (
                f" A further ${rec['derived_total']:,.0f} is attributable to "
                f"{rec['derived_counterparties']} customers the filings name only as a "
                f"percentage of revenue, multiplied out against the revenue reported for "
                f"the same window.")
        out.append({
            "id": "LG01", "tier": "INFERRED", "source": "ledger",
            "method": "revenue_reconciliation",
            "summary": (
                f"Of ${rec['reported_revenue']:,.0f} in revenue reported over "
                f"{rec['window'][0]} to {rec['window'][1]}, ${rec['equity_total']:,.0f} "
                f"({rec['equity_share_pct']}%) was settled not in cash but in equity issued "
                f"by the customers themselves, across {rec['equity_counterparties']} "
                f"counterparties.{derived_clause} In total ${rec['attributed_total']:,.0f} "
                f"({rec['attributed_share_pct']}%) of reported revenue traces to named "
                f"counterparties rather than to cash from arm's-length customers. Strip it "
                f"out and ${rec.get('revenue_excluding_attributed', 0):,.0f} of revenue "
                f"remains — the reported figure is roughly "
                f"{rec['overstatement_pct']:.0f}% above it."),
            "figures": [f"reported={rec['reported_revenue']:,.0f}",
                        f"equity_settled={rec['equity_total']:,.0f}",
                        f"derived={rec['derived_total']:,.0f}",
                        f"attributed={rec['attributed_total']:,.0f}",
                        f"share={rec['attributed_share_pct']}%"],
            "entities": [r["counterparty"] for r in report["register"]["equity"]],
            # Every engagement's own sentence. Without these the fleet cannot
            # verify the total and will not build on it.
            "citations": [r["citation"] for r in report["register"]["equity"]
                          if r.get("citation")][:12],
        })

    if pr["equity_median"] and pr["published_high"]:
        out.append({
            "id": "LG02", "tier": "INFERRED", "source": "ledger",
            "method": "pricing_comparator",
            # cash_low/cash_high are None when the corpus discloses no
            # arm's-length cash engagement. Formatting them unconditionally
            # crashed the whole ledger seed on such a corpus.
            "summary": (
                f"The company publishes its own price for this service: a "
                f"${pr['published_low']:,.0f}-${pr['published_high']:,.0f} engagement fee. "
                + (f"Its cash consulting engagements ran ${pr['cash_low']:,.0f}-"
                   f"${pr['cash_high']:,.0f}. " if pr["cash_low"] is not None else "")
                + f"The equity-settled engagements ran "
                  f"${pr['equity_low']:,.0f}-${pr['equity_high']:,.0f}, a median of "
                  f"${pr['equity_median']:,.0f} — roughly "
                  f"{pr['multiple_vs_published']:.0f}x the published rate card for the "
                  f"same service."),
            "figures": [f"published={pr['published_low']:,.0f}-{pr['published_high']:,.0f}",
                        f"equity_median={pr['equity_median']:,.0f}",
                        f"multiple={pr['multiple_vs_published']:.0f}x"],
            "entities": [],
            "citations": ([c for c in report.get("rate_card_citations", [])][:2]
                          + [r["citation"] for r in report["register"]["cash"]
                             if r.get("citation")][:3]),
        })

    for c in report["concentration"][:3]:
        named = ", ".join(f"{x['counterparty']} {x['pct']}%" for x in c["customers"])
        out.append({
            "id": f"LG-C{report['concentration'].index(c)+1:02d}",
            "tier": "INFERRED", "source": "ledger",
            "method": "disclosed_concentration",
            "summary": (
                f"The company itself discloses that for the {c['period']}, "
                f"{c['named_share_pct']}% of all revenue came from "
                f"{len(c['customers'])} named customers: {named}."),
            "figures": [f"named_share={c['named_share_pct']}%"],
            "entities": [x["counterparty"] for x in c["customers"]],
            "citations": [c["citation"]] if c.get("citation") else [],
        })

    strong = [r for r in report["repeated_figures"] if r["significance"] == "STRONG"]
    for i, r in enumerate(strong[:6], 1):
        out.append({
            "id": f"LG-F{i:02d}", "tier": "INFERRED", "source": "ledger",
            "method": "repeated_figure_across_counterparties",
            "summary": (
                f"The figure {r['amount']} is tied at paragraph level to "
                f"{r['party_count']} distinct counterparties - {', '.join(r['parties'])}. "
                f"It carries {r['significant_digits']} significant digits, so this is not "
                f"parties independently settling on a round number."),
            "figures": [r["amount"], f"{r['party_count']} parties"],
            "entities": r["parties"],
            "citations": [{"file": c["file"], "quote": c["quote"]}
                          for c in r.get("citations", [])],
        })

    for j, n in enumerate(report["near_misses"][:3], 1):
        out.append({
            "id": f"LG-N{j:02d}", "tier": "INFERRED", "source": "ledger",
            "method": "near_miss_variant",
            "summary": (
                f"Near-identical figures {n['a']} and {n['b']} (difference "
                f"{n['delta']:,.0f}, {n['pct']:.3f}%) both attach to "
                f"{', '.join(n['shared_parties'])}. Either a transcription error in a "
                f"filed document or figures altered to appear distinct."),
            "figures": [n["a"], n["b"]],
            "entities": n["shared_parties"],
            "citations": [{"file": c["file"], "quote": c["quote"]}
                          for c in n.get("citations", [])],
        })
    return out


# ------------------------------------------------------------------------ cli

def _money(v):
    return f"${v:,.0f}" if v is not None else "—"


def main():
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--cik", default=os.environ.get("CASEZERO_CIK", "1414767"))
    ap.add_argument("--start", default="2021-10-01")
    ap.add_argument("--end", default="2024-01-31")
    ap.add_argument("--revenue", type=float, default=None,
                    help="reported revenue for the window; skips the XBRL fetch")
    ap.add_argument("--offline", action="store_true", help="no reconciliation")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    revenue, window, quarters = a.revenue, [a.start, a.end], []
    if revenue is None and not a.offline:
        try:
            from .forensic import revenue_timeline
            tl = revenue_timeline(a.cik, a.start, a.end)
            revenue, quarters = tl["total"], tl["quarters"]
        except Exception as e:
            print(f"  [warn] revenue unavailable, reconciliation skipped: {e}")

    rep = audit(a.corpus, revenue, window, quarters=quarters)
    if a.json:
        print(json.dumps(rep, indent=2, default=str)); return

    W = 82
    print(f"\n{'='*W}\nFORENSIC LEDGER — the books, rebuilt from the filings\n{'='*W}")

    print("\nENGAGEMENT REGISTER — every consulting engagement, and how it settled")
    print("-" * W)
    print(f"  {'counterparty':<28}{'consideration':>15}  {'units':>12}  {'@/unit':>8}  first")
    for r in rep["register"]["equity"]:
        px = f"${r['unit_price']:.2f}" if r["unit_price"] else "—"
        print(f"  {r['counterparty'][:27]:<28}{_money(r['consideration']):>15}  "
              f"{r['units']:>12,.0f}  {px:>8}  {r['first_disclosed']}")
    print(f"  {'-'*(W-2)}")
    for r in rep["register"]["cash"]:
        print(f"  {r['counterparty'][:27]:<28}{_money(r['consideration']):>15}  "
              f"{'—':>12}  {'cash':>8}  {r['first_disclosed']}")

    rec = rep["reconciliation"]
    print(f"\n  SETTLED IN COUNTERPARTY EQUITY   {rec['equity_counterparties']:>2} parties"
          f"{_money(rec['equity_total']):>18}")
    print(f"  SETTLED IN CASH                  {rec['cash_counterparties']:>2} parties"
          f"{_money(rec['cash_total']):>18}")

    print(f"\nDISCLOSED REVENUE CONCENTRATION — the issuer's own admission\n{'-'*W}")
    for c in rep["concentration"]:
        print(f"  {c['period'][:52]:<54} {c['named_share_pct']:>3}% named")
        for cu in c["customers"]:
            print(f"      {cu['counterparty'][:36]:<38} {cu['pct']:>3}%")
    if not rep["concentration"]:
        print("  none disclosed")

    print(f"\nCUSTOMER SET — union of both routes ({len(rep['counterparties'])} counterparties)\n{'-'*W}")
    for i in range(0, len(rep["counterparties"]), 3):
        print("  " + "".join(f"{n[:24]:<26}" for n in rep["counterparties"][i:i+3]))

    print(f"\nRECONCILIATION vs REPORTED REVENUE\n{'-'*W}")
    if rec["reported_revenue"]:
        dc = rep["derived_concentration"]
        print(f"  Reported revenue, {rec['window'][0]} to {rec['window'][1]}"
              f"{_money(rec['reported_revenue']):>26}")
        print(f"  Settled in counterparty equity  (disclosed, {rec['equity_counterparties']:>2} parties)"
              f"{_money(rec['equity_total']):>16}   {rec['equity_share_pct']:>5}%")
        if dc["customers"]:
            print(f"  Named concentration customers  (derived,   {rec['derived_counterparties']:>2} parties)"
                  f"{_money(rec['derived_total']):>16}")
            for r in dc["customers"]:
                print(f"      {r['counterparty'][:26]:<28} {r['pct']:>3}% of "
                      f"{r['months']}mo to {r['period_end']}{_money(r['value']):>14}")
        print(f"  {'-'*(W-4)}")
        print(f"  Revenue attributable to named counterparties"
              f"{_money(rec['attributed_total']):>21}   {rec['attributed_share_pct']:>5}%")
        print(f"  Settled in arm's-length cash{_money(rec['cash_total']):>36}   {rec['cash_share_pct']:>5}%")
        if rec.get("revenue_excluding_attributed"):
            print(f"  Revenue remaining once it is removed"
                  f"{_money(rec['revenue_excluding_attributed']):>28}")
            print(f"\n  >> OVERSTATEMENT OF THE REMAINDER: {rec['overstatement_pct']:.0f}%")
        if dc["customers"]:
            print(f"\n  ({dc['note']})")
    else:
        print("  reported revenue unavailable — rerun without --offline")

    pr = rep["pricing"]
    print(f"\nPRICING — the same service, two prices\n{'-'*W}")
    print(f"  Company's own published rate card    "
          f"{_money(pr['published_low'])} – {_money(pr['published_high'])} engagement fee")
    print(f"  Arm's-length cash engagements        "
          f"{_money(pr['cash_low'])} – {_money(pr['cash_high'])}")
    print(f"  Equity-settled engagements           "
          f"{_money(pr['equity_low'])} – {_money(pr['equity_high'])}"
          f"   (median {_money(pr['equity_median'])})")
    if pr["multiple_vs_published"]:
        print(f"\n  >> {pr['multiple_vs_published']:.0f}x the published price for the same service"
              + (f", {pr['multiple_vs_cash']:.0f}x what cash customers paid"
                 if pr["multiple_vs_cash"] else ""))

    print(f"\nSUPPORTING — figures shared across supposedly independent parties\n{'-'*W}")
    for r in rep["repeated_figures"]:
        if r["significance"] != "STRONG":
            continue
        print(f"  {r['amount']:>12}  x{r['party_count']}  {', '.join(r['parties'])}")
    for n in rep["near_misses"]:
        print(f"  {n['a']} vs {n['b']} — differ by {n['delta']:,.0f} ({n['pct']:.3f}%), "
              f"shared by {len(n['shared_parties'])}")

    print(f"\n{'='*W}\nAll INFERRED. Arithmetic from filed documents; the conclusion is the "
          f"fleet's to argue.\n")


if __name__ == "__main__":
    main()
