"""Deterministic forensic screens — no LLM in the loop.

The Beneish M-Score was fit on companies subject to SEC Accounting and Auditing
Enforcement Releases. It is, literally, a model trained on past SEC actions to
recognise manipulation patterns — published in 1999, so it knows nothing about
any case you point it at, and it cannot hallucinate.

That makes it the right answer to "can we train on past SEC actions?": you don't
need to. The fitting was done, on AAER data, by Beneish. What you need is the
arithmetic.

    M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI
             + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI

    M > -1.78  =>  profile consistent with earnings manipulation

HONEST LIMITS, and they belong in the output rather than a footnote:
  * ~50%+ false-positive rate in the original sample. This is a SCREEN, not a
    verdict, and it is emitted as INFERRED evidence, never DIRECT.
  * Fit on larger firms than a nano-cap. Small denominators make ratios jumpy.
  * A high score says "these financials have the shape of manipulated ones",
    not "this company committed fraud".

Any index that cannot be computed from the filed XBRL is reported as
unavailable and held at 1.0 (neutral). It is never quietly guessed.
"""
from __future__ import annotations
import json, urllib.request
from typing import Dict, List, Optional

UA = "Derek Soltis dj@soltis.info"

# Preference order: first tag present wins.
TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities"],
    "net_income": ["NetIncomeLoss"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "liabilities": ["Liabilities"],
    "ltd": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "sga": ["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"],
    "depreciation": ["DepreciationDepletionAndAmortization", "Depreciation",
                     "DepreciationAmortizationAndAccretionNet"],
    "securities": ["MarketableSecuritiesNoncurrent", "LongTermInvestments"],
}


def fetch_facts(cik: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def annual_series(facts: dict, tag_list: List[str]) -> Dict[str, float]:
    """Fiscal-year-end date -> value, from annual (10-K) figures only."""
    us = facts.get("facts", {}).get("us-gaap", {})
    for tag in tag_list:
        if tag not in us:
            continue
        out: Dict[str, float] = {}
        for u in us[tag]["units"].get("USD", []):
            if u.get("form") != "10-K" or u.get("fp") != "FY":
                continue
            # duration facts (income/cash-flow) vs instant facts (balance sheet)
            if u.get("start") and u.get("end"):
                months = (int(u["end"][:4]) - int(u["start"][:4])) * 12 + \
                         (int(u["end"][5:7]) - int(u["start"][5:7]))
                if not (10 <= months <= 14):      # full year only, never a quarter
                    continue
            end = u["end"]
            if end not in out or abs(u["val"]) > abs(out[end]):
                out[end] = float(u["val"])
        if out:
            return out
    return {}


def build_panel(cik: str) -> Dict[str, Dict[str, Optional[float]]]:
    facts = fetch_facts(cik)
    series = {k: annual_series(facts, tags) for k, tags in TAGS.items()}
    years = sorted({d for s in series.values() for d in s})
    return {y: {k: series[k].get(y) for k in TAGS} for y in years}, facts.get("entityName", "")


def _safe(n, d, default=None):
    try:
        if n is None or d in (None, 0):
            return default
        return n / d
    except ZeroDivisionError:
        return default


def m_score(cur: dict, prior: dict) -> dict:
    """Eight indices + M. Missing indices are held at 1.0 and reported."""
    idx: Dict[str, float] = {}
    missing: List[str] = []

    def put(name, value, neutral=1.0):
        if value is None:
            idx[name] = neutral
            missing.append(name)
        else:
            idx[name] = value

    # DSRI — receivables growing faster than sales
    put("DSRI", _safe(_safe(cur["receivables"], cur["revenue"]),
                      _safe(prior["receivables"], prior["revenue"])))

    # GMI — deteriorating gross margin
    gm_c = _safe((cur["revenue"] or 0) - (cur["cogs"] or 0), cur["revenue"])
    gm_p = _safe((prior["revenue"] or 0) - (prior["cogs"] or 0), prior["revenue"])
    put("GMI", _safe(gm_p, gm_c) if (gm_c and gm_p) else None)

    # AQI — share of assets that is neither current nor PP&E ("soft" assets)
    def soft(y):
        if y["assets"] in (None, 0):
            return None
        hard = (y["current_assets"] or 0) + (y["ppe"] or 0) + (y["securities"] or 0)
        return 1 - hard / y["assets"]
    put("AQI", _safe(soft(cur), soft(prior)))

    # SGI — sales growth. Growth is not fraud, but it is where fraud hides.
    put("SGI", _safe(cur["revenue"], prior["revenue"]))

    # DEPI — depreciation rate slowing (capitalising what should be expensed)
    def deprate(y):
        base = (y["depreciation"] or 0) + (y["ppe"] or 0)
        return _safe(y["depreciation"], base)
    put("DEPI", _safe(deprate(prior), deprate(cur)))

    # SGAI — SG&A rising faster than sales
    put("SGAI", _safe(_safe(cur["sga"], cur["revenue"]),
                      _safe(prior["sga"], prior["revenue"])))

    # TATA — accruals: the gap between reported income and actual cash.
    # The heaviest coefficient in the model, and the one that matters here.
    put("TATA", _safe((cur["net_income"] or 0) - (cur["cfo"] or 0), cur["assets"]), neutral=0.0)

    # LVGI — leverage rising
    def lev(y):
        tot = (y["current_liabilities"] or 0) + (y["ltd"] or 0)
        if not tot and y["liabilities"]:
            tot = y["liabilities"]
        return _safe(tot, y["assets"])
    put("LVGI", _safe(lev(cur), lev(prior)))

    M = (-4.84
         + 0.920 * idx["DSRI"] + 0.528 * idx["GMI"] + 0.404 * idx["AQI"]
         + 0.892 * idx["SGI"] + 0.115 * idx["DEPI"] - 0.172 * idx["SGAI"]
         + 4.679 * idx["TATA"] - 0.327 * idx["LVGI"])

    contrib = {"DSRI": 0.920 * idx["DSRI"], "GMI": 0.528 * idx["GMI"],
               "AQI": 0.404 * idx["AQI"], "SGI": 0.892 * idx["SGI"],
               "DEPI": 0.115 * idx["DEPI"], "SGAI": -0.172 * idx["SGAI"],
               "TATA": 4.679 * idx["TATA"], "LVGI": -0.327 * idx["LVGI"]}

    return {"m_score": M, "flagged": M > -1.78, "threshold": -1.78,
            "indices": idx, "contributions": contrib,
            "unavailable": missing,
            "dominant_driver": max(contrib, key=lambda k: abs(contrib[k]))}


MIN_REVENUE = 1_000_000   # below this, ratio denominators are too small to mean anything


def accrual_screen(y: dict) -> Optional[dict]:
    """The cleaner signal, and on a nano-cap the more trustworthy one.

    Positive reported net income alongside negative operating cash flow means
    the profit is accrual, not cash. It is one subtraction, it has no fitted
    coefficients, and it does not degrade on small companies the way a
    ratio-of-ratios composite does.
    """
    ni, cfo, rev = y.get("net_income"), y.get("cfo"), y.get("revenue")
    if ni is None or cfo is None or not rev:
        return None
    return {
        "net_income": ni, "cfo": cfo, "gap": ni - cfo,
        "gap_over_revenue": (ni - cfo) / rev,
        "profit_without_cash": ni > 0 > cfo,
    }


def screen(cik: str, min_revenue: float = MIN_REVENUE) -> dict:
    panel, name = build_panel(cik)
    years = sorted(panel)
    results, skipped = [], []
    for prev, cur in zip(years, years[1:]):
        rev_c, rev_p = panel[cur]["revenue"], panel[prev]["revenue"]
        if not rev_c or not rev_p:
            continue
        if min(rev_c, rev_p) < min_revenue:
            skipped.append({"fiscal_year_end": cur, "revenue": rev_c,
                            "reason": "revenue below the floor where these ratios mean anything"})
            continue
        r = m_score(panel[cur], panel[prev])
        r.update(fiscal_year_end=cur, prior_year_end=prev, revenue=rev_c,
                 net_income=panel[cur]["net_income"], cfo=panel[cur]["cfo"],
                 accruals=accrual_screen(panel[cur]))
        results.append(r)
    return {"company": name, "cik": cik, "years": results,
            "skipped_years": skipped, "min_revenue": min_revenue}


def as_evidence(result: dict) -> List[dict]:
    """Emit as seed evidence for the fleet.

    Tier is INFERRED, never DIRECT: the inputs are filed figures but the score
    is a derived statistical screen, and the tier system exists precisely so
    that distinction survives into the findings.
    """
    out = []
    for i, y in enumerate(result["years"], 1):
        a = y.get("accruals") or {}

        # The accruals divergence leads, because on a company this size it is
        # the more trustworthy of the two and it needs no fitted coefficients.
        if a.get("profit_without_cash"):
            out.append({
                "id": f"F{i:02d}A",
                "tier": "INFERRED",
                "summary": (
                    f"FY ending {y['fiscal_year_end']}: reported net income of "
                    f"${a['net_income']:,.0f} against operating cash flow of "
                    f"${a['cfo']:,.0f} — a ${a['gap']:,.0f} gap, "
                    f"{a['gap_over_revenue']:.0%} of revenue. The reported profit "
                    f"did not arrive as cash."),
                "figures": [f"net income={a['net_income']:,.0f}",
                            f"operating cash flow={a['cfo']:,.0f}",
                            f"gap={a['gap']:,.0f}"],
                "event_date": y["fiscal_year_end"],
                "method": "accruals_divergence",
            })

        if y["flagged"]:
            d = y["dominant_driver"]
            out.append({
                "id": f"F{i:02d}M",
                "tier": "INFERRED",
                "summary": (
                    f"Beneish M-Score for FY ending {y['fiscal_year_end']} is "
                    f"{y['m_score']:.2f}, above the -1.78 manipulation threshold. "
                    f"Dominant driver: {d}. A screen fit on SEC AAER companies — "
                    f"high false-positive rate, and not a finding of fraud."),
                "figures": [f"M={y['m_score']:.2f}", f"{d}={y['indices'][d]:.2f}"],
                "event_date": y["fiscal_year_end"],
                "method": "beneish_m_score",
            })
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cik", default="1414767")
    args = ap.parse_args()

    r = screen(args.cik)
    print(f"\n{'='*76}\nBENEISH M-SCORE — {r['company']} (CIK {r['cik']})")
    print(f"{'='*76}")
    print(f"{'FY end':<12}{'M':>8}{'flag':>7}   {'driver':<7}{'revenue':>14}{'net inc':>13}{'op cash':>13}")
    print("-" * 76)
    for y in r["years"]:
        ni = f"{y['net_income']:,.0f}" if y["net_income"] is not None else "-"
        cf = f"{y['cfo']:,.0f}" if y["cfo"] is not None else "-"
        acc = "  PROFIT/NO CASH" if (y.get("accruals") or {}).get("profit_without_cash") else ""
        print(f"{y['fiscal_year_end']:<12}{y['m_score']:>8.2f}"
              f"{('  FLAG' if y['flagged'] else '   ok'):>7}   {y['dominant_driver']:<7}"
              f"{y['revenue']:>14,.0f}{ni:>13}{cf:>13}{acc}")
    print("-" * 76)
    flagged = [y for y in r["years"] if y["flagged"]]
    accr = [y for y in r["years"] if (y.get("accruals") or {}).get("profit_without_cash")]
    print(f"M-Score above threshold : {len(flagged)}/{len(r['years'])} fiscal years")
    print(f"Profit without cash     : {len(accr)}/{len(r['years'])} fiscal years")
    for s in r["skipped_years"]:
        print(f"skipped {s['fiscal_year_end']} (revenue ${s['revenue']:,.0f}) — {s['reason']}")
    miss = sorted({m for y in r["years"] for m in y["unavailable"]})
    if miss:
        print(f"indices unavailable in some years, held neutral: {', '.join(miss)}")
    print("\nBoth are SCREENS, emitted as INFERRED evidence. Neither is a finding of fraud.")


# =========================================================================
# Revenue timeline reconstruction
# =========================================================================
# The fleet cannot do this itself, and that is structural rather than a
# prompting failure: each agent call sees ~8 of 71 documents, so no single
# context ever contains all ten quarters. Summing across the whole period is
# an aggregation problem, not a reasoning problem, and it belongs in code.
#
# Q4 is never filed on its own - there is no fourth 10-Q - so it is derived as
# (fiscal year total - nine-month year-to-date). That derivation is arithmetic
# on filed figures, not an estimate.

from datetime import date as _date


def _days(fact) -> int:
    if not fact.get("start"):
        return 0
    a = _date(*map(int, fact["start"].split("-")))
    b = _date(*map(int, fact["end"].split("-")))
    return (b - a).days


def revenue_timeline(cik: str, start: str, end: str, tag: str = "Revenues") -> dict:
    """Quarterly revenue across a window, with Q4s derived. All filed figures."""
    url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
           f"CIK{cik.zfill(10)}/us-gaap/{tag}.json")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req) as r:
        facts = json.loads(r.read())["units"]["USD"]

    filed = [f for f in facts if str(f.get("form", "")).startswith("10-")]
    quarters, ytd9, annual = {}, {}, {}
    for f in filed:
        d = _days(f)
        if 80 <= d <= 100:
            quarters[(f["start"], f["end"])] = f["val"]
        elif 260 <= d <= 285:
            ytd9[(f["start"], f["end"])] = f["val"]
        elif 355 <= d <= 375:
            annual[(f["start"], f["end"])] = f["val"]

    derived = []
    for (fy_start, fy_end), fy_val in annual.items():
        for (y_start, y_end), y_val in ytd9.items():
            if y_start == fy_start:                       # same fiscal year
                # Q4 starts the day AFTER the nine-month period ends.
                nxt = _date(*map(int, y_end.split("-")))
                q4_start = (nxt.replace(day=1) if nxt.day == 1 else nxt).isoformat()
                q4_start = _date.fromordinal(nxt.toordinal() + 1).isoformat()
                key = (q4_start, fy_end)
                if key not in quarters:
                    quarters[key] = fy_val - y_val
                    derived.append(key)

    rows = sorted((s, e, v) for (s, e), v in quarters.items() if start <= s <= end)
    # a quarter reported twice under different fiscal-year labels is one quarter
    seen, uniq = set(), []
    for s, e, v in rows:
        if e in seen:
            continue
        seen.add(e)
        uniq.append({"start": s, "end": e, "revenue": v,
                     "derived": (s, e) in derived})
    return {"cik": cik, "tag": tag, "window": [start, end],
            "quarters": uniq, "total": sum(q["revenue"] for q in uniq),
            "derived_count": sum(1 for q in uniq if q["derived"])}


def timeline_evidence(tl: dict) -> List[dict]:
    if not tl["quarters"]:
        return []
    n, d = len(tl["quarters"]), tl["derived_count"]
    return [{
        "id": "F-TL",
        "tier": "INFERRED",
        "summary": (
            f"Total revenue across the {n} quarters from {tl['window'][0]} to "
            f"{tl['window'][1]} is ${tl['total']:,.0f}, aggregated from filed XBRL "
            f"({d} fourth quarters derived as fiscal-year total minus nine-month "
            f"year-to-date). No single filing states this figure. NOTE: this "
            f"aggregates whole fiscal quarters. Where an alleged conduct period "
            f"does not begin and end on a quarter boundary, the totals will not "
            f"reconcile exactly and the difference is a calendar artefact, not a "
            f"discrepancy."),
        "figures": [f"total={tl['total']:,.0f}", f"quarters={n}"]
                   + [f"{q['end']}={q['revenue']:,.0f}" for q in tl["quarters"]],
        "event_date": tl["quarters"][-1]["end"],
        "method": "revenue_timeline",
    }]
