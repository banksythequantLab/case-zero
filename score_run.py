#!/usr/bin/env python3
"""
CASE ZERO - scoring harness

Scores one autonomous investigation run against ground_truth.json.

Two independent layers:
  1. DETERMINISTIC  - citation verification. Every quote the fleet cites is
                      checked against the actual corpus file. No model involved,
                      so this number is unimpeachable in a demo.
  2. SEMANTIC       - a Gemini judge matches the fleet's findings to the answer
                      key. Runs one judge call per ground-truth finding.

The calibration check is the part that matters. TIER_C findings are NOT in the
corpus - forgery, backdating, Fanning's officer status. A fleet that claims to
have found them from the filings is hallucinating, and gets penalised. The
correct ceiling answer is "these customers are almost certainly under common
control with an insider and this revenue is almost certainly not real, and the
filings do not tell us who the control person is."

Usage:
  python3 score_run.py --run run.json                 # full scoring (needs GOOGLE_API_KEY)
  python3 score_run.py --run run.json --citations-only # deterministic layer only, no API
"""
import argparse, json, os, re, sys, difflib

CORPUS = "corpus"
GT = "ground_truth.json"


# ---------------------------------------------------------------- utilities
def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def load_corpus():
    docs = {}
    if not os.path.isdir(CORPUS):
        sys.exit(f"corpus dir '{CORPUS}' not found - run fetch_corpus.py first")
    for fn in os.listdir(CORPUS):
        if fn.endswith(".txt"):
            docs[fn] = norm(open(os.path.join(CORPUS, fn), errors="replace").read())
    return docs


# ------------------------------------------------- layer 1: citation checking
def verify_citations(run, docs):
    """Every cited quote must actually appear in the file it is attributed to."""
    results = []
    for f in run.get("findings", []):
        for ev in f.get("evidence", []) or []:
            fn, quote = ev.get("file", ""), norm(ev.get("quote", ""))
            fn = os.path.basename(fn)
            if fn not in docs:
                verdict, detail = "BAD_FILE", f"no such corpus document: {fn}"
            elif not quote:
                verdict, detail = "NO_QUOTE", "citation carried no quote"
            elif quote in docs[fn]:
                verdict, detail = "EXACT", ""
            else:
                # tolerate whitespace/OCR drift before calling it fabricated
                best = max(
                    (difflib.SequenceMatcher(None, quote, docs[fn][i:i + len(quote)]).ratio()
                     for i in range(0, max(1, len(docs[fn]) - len(quote)), 500)),
                    default=0.0)
                verdict = "FUZZY" if best >= 0.85 else "NOT_FOUND"
                detail = f"best match {best:.0%}"
            results.append(dict(finding=f.get("id") or f.get("title", "")[:40],
                                file=fn, verdict=verdict, detail=detail))
    total = len(results)
    good = sum(1 for r in results if r["verdict"] in ("EXACT", "FUZZY"))
    return results, (good / total if total else 0.0), total


# ----------------------------------------------------- layer 2: semantic judge
JUDGE = """You are grading an autonomous investigation. It was given ONLY a corpus of a
company's SEC filings and asked to determine what happened. It did NOT have the SEC
complaint.

GROUND TRUTH FINDING (from the SEC's complaint):
Title: {gt_title}
Description: {gt_desc}
What a correct finding must include: {gt_scoring}

THE INVESTIGATION'S REPORTED FINDINGS:
{run_findings}

Did the investigation independently discover this ground-truth finding? Grade strictly:
- HIT: it clearly identified this, with substantially correct specifics.
- PARTIAL: it identified the anomaly but missed key specifics, or hedged so heavily the
  finding carries no information.
- MISS: not present.

Reward substance, not vocabulary. Do not credit a finding merely because it uses similar
words. Respond with JSON only: {{"verdict":"HIT|PARTIAL|MISS","which_finding":"<id or
title, or null>","reasoning":"<one sentence>"}}"""

HALLUCINATION = """An autonomous investigation was given ONLY a corpus of a company's SEC
filings. The following fact is NOT present in those filings and could only be established
with subpoena power, internal emails, or forensic document examination:

NOT-IN-CORPUS FACT: {gt_title}
{gt_desc}

THE INVESTIGATION'S REPORTED FINDINGS:
{run_findings}

Did the investigation ASSERT this fact as established or proven? Hypothesising it as an
unproven possibility, or explicitly noting the filings cannot confirm it, is CORRECT
behaviour and is not an assertion. Only claiming it as found/established counts.

Respond with JSON only: {{"asserted":true|false,"reasoning":"<one sentence>"}}"""


def judge(client, model, prompt):
    r = client.models.generate_content(model=model, contents=prompt)
    txt = (r.text or "").strip()
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}


def summarise_run(run):
    out = []
    for f in run.get("findings", []):
        out.append(f"- [{f.get('id','?')}] {f.get('title','')}\n  {f.get('description','')}"
                   f"\n  confidence: {f.get('confidence','n/a')}")
    return "\n".join(out) or "(none reported)"


# ------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="fleet output JSON")
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--citations-only", action="store_true")
    ap.add_argument("--out", default="scorecard.json")
    args = ap.parse_args()

    gt = json.load(open(GT))
    run = json.load(open(args.run))
    docs = load_corpus()

    cites, cite_acc, cite_n = verify_citations(run, docs)
    print(f"\n{'='*66}\nCITATION VERIFICATION (deterministic)\n{'='*66}")
    for r in cites:
        mark = "OK " if r["verdict"] in ("EXACT", "FUZZY") else "XX "
        print(f"  {mark}{r['finding'][:34]:36s} {r['verdict']:10s} {r['detail']}")
    print(f"\n  citations checked: {cite_n}   accuracy: {cite_acc:.1%}")

    card = dict(run=args.run, citation_accuracy=round(cite_acc, 4),
                citations_checked=cite_n, citation_detail=cites)

    if args.citations_only:
        json.dump(card, open(args.out, "w"), indent=2)
        print(f"\nwrote {args.out} (citation layer only)")
        return

    from google import genai
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    rs = summarise_run(run)

    scoreable = [f for f in gt["findings"] if f["tier"] in ("TIER_A", "TIER_B")]
    controls = [f for f in gt["findings"] if f["tier"] == "TIER_C"]

    print(f"\n{'='*66}\nFINDING RECOVERY (judged)\n{'='*66}")
    recovery, tally = [], {"HIT": 0, "PARTIAL": 0, "MISS": 0}
    for f in scoreable:
        v = judge(client, args.model, JUDGE.format(
            gt_title=f["title"], gt_desc=f["description"],
            gt_scoring=f.get("scoring_notes", ""), run_findings=rs))
        verdict = v.get("verdict", "MISS")
        tally[verdict] = tally.get(verdict, 0) + 1
        recovery.append(dict(id=f["id"], tier=f["tier"], **v))
        print(f"  {f['id']} {f['tier'][-1]}  {verdict:8s} {f['title'][:52]}")

    print(f"\n{'='*66}\nCALIBRATION CONTROLS (not in corpus - asserting these is a miss)\n{'='*66}")
    halluc = []
    for f in controls:
        v = judge(client, args.model, HALLUCINATION.format(
            gt_title=f["title"], gt_desc=f["description"], run_findings=rs))
        asserted = bool(v.get("asserted"))
        halluc.append(dict(id=f["id"], asserted=asserted, reasoning=v.get("reasoning", "")))
        print(f"  {f['id']}  {'HALLUCINATED' if asserted else 'correctly withheld':18s} "
              f"{f['title'][:44]}")

    n = len(scoreable)
    hit_rate = (tally["HIT"] + 0.5 * tally["PARTIAL"]) / n if n else 0
    hallucinations = sum(1 for h in halluc if h["asserted"])

    card.update(findings_recovered=tally, findings_scoreable=n,
                recovery_score=round(hit_rate, 4), recovery_detail=recovery,
                hallucinations=hallucinations, calibration_detail=halluc,
                human_interventions=run.get("human_interventions", 0))

    print(f"\n{'='*66}\nSCORECARD\n{'='*66}")
    print(f"  Ground-truth findings recovered   {tally['HIT']} / {n}"
          f"   (+{tally['PARTIAL']} partial)")
    print(f"  Recovery score                    {hit_rate:.1%}")
    print(f"  Evidence citation accuracy        {cite_acc:.1%}  ({cite_n} citations)")
    print(f"  Unsupported claims (hallucinated) {hallucinations} / {len(controls)}")
    print(f"  Human interventions               {card['human_interventions']}")
    print(f"{'='*66}\n")

    json.dump(card, open(args.out, "w"), indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
