#!/usr/bin/env python3
"""
CASE ZERO - contamination test

Proves the investigator model has no prior knowledge of the case. Run this
BEFORE committing to a candidate, and again ON CAMERA in the demo video. A
judge's first objection is "the model already knew" - this is the ten seconds
that kills it.

METHOD. Two probe sets, scored differently, because they answer different
questions:

  SCORED probes never mention a name, a number, or an allegation. They ask open
  questions and see what the model volunteers. Only these decide the verdict.
  Naming "John Fanning" inside a probe and then flagging the model for echoing
  it back would be measuring the prompt, not the model.

  DIAGNOSTIC probes deliberately name names. They do not affect the verdict.
  They exist because John Fanning is a real public figure connected to Napster,
  so the model plausibly knows *a* John Fanning without knowing anything about
  this case. Knowing the person is not knowing the fraud, and conflating the two
  would fail a perfectly good candidate.

Setup:  pip install google-genai
        export GOOGLE_API_KEY=...
Usage:  python3 cold_prompt_test.py --company "Netcapital Inc." --ticker NCPL

Writes cold_prompt_result.json, which preflight.py reads as evidence the test
was actually run. Keep it with the submission.
"""
import argparse, json, os, re, sys, time

# Scored: no names, no figures, no allegations. Nothing to echo back.
SCORED_PROBES = [
    "What do you know about {company} (NASDAQ: {ticker})? Describe its business, its "
    "management, and any accounting, disclosure, or regulatory problems it has had.",

    "Has {company} ever restated its financials, been accused of misstating revenue, or "
    "faced securities litigation? Answer only from what you already know. If you do not "
    "know, say so.",

    "Has any securities regulator brought an enforcement action against {company} or its "
    "officers? Name any individuals charged and describe the allegations.",

    "Describe any related-party transactions, undisclosed affiliations, or consulting "
    "arrangements involving {company} and entities controlled by its executives or "
    "their families.",

    "Who are the executives of {company}, and is any of them related to any other person "
    "involved with the company or its customers?",
]

# Diagnostic only. Never affects the verdict.
DIAGNOSTIC_PROBES = [
    "Who is John Fanning? List every notable person of that name you know of.",
    "What is Netcapital Advisors and what are its 'portfolio companies'?",
]

# Three different things get conflated if you use one flag list, and the whole
# verdict turns on keeping them apart.
#
# FRAUD_FLAGS  - knowledge of THE CASE. Any hit here is disqualifying: the model
#                would be recalling the answer rather than deriving it.
# IDENTITY_FLAGS - knowledge of the PEOPLE. Officers of a public company are
#                public information and were public long before the cutoff.
#                Recorded, reported, but NOT disqualifying on its own.
# (Deliberately absent: "netcapital advisors", "portfolio companies". Those are
#  the company's own publicly disclosed business model, described in its filings
#  since 2021. Flagging them measures nothing.)

# Phrases specific enough that a model cannot produce them without knowing the
# case. Bare stems like "misstat"/"restat" are deliberately NOT here: the probes
# themselves use those words, so the model echoes them back inside its own
# denial, and "material misstatement" is boilerplate in every internal-controls
# disclosure ever written. Both are false positives that cost me a re-run.
FRAUD_FLAGS = [
    "345", "sham consulting", "sham agreement", "forged", "backdated",
    "13.9 million", "$14 million", "inflated revenue", "fictitious revenue",
    "overstated its revenue", "overstated revenue", "revenue was overstated",
    "restated its financials to", "accounting fraud at netcapital",
]

IDENTITY_FLAGS = ["fanning", "kraysler", "lenk", "riss"]

# Claims of enforcement actions are checked by hand against the SEC's
# litigation-release record - the model invents these with full confidence.
ENFORCEMENT_CUES = ["sec charged", "sec filed", "enforcement action", "civil complaint",
                    "finra", "consent order", "cease and desist", "sued"]

DENIALS = ["i do not have", "i don't have", "no information", "not aware",
           "cannot find", "no knowledge", "i am not familiar", "unable to find",
           "no record", "do not know", "don't know"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--company", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--out", default="cold_prompt_result.json")
    args = ap.parse_args()

    try:
        from google import genai
    except ImportError:
        sys.exit("pip install google-genai")

    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def ask(q):
        # No tools and no grounding: parametric memory only. If the model can
        # search, this test measures nothing.
        r = client.models.generate_content(model=args.model, contents=q)
        return (r.text or "").strip()

    record, fraud_hits, identity_hits = [], 0, 0

    for kind, probes in (("SCORED", SCORED_PROBES), ("DIAGNOSTIC", DIAGNOSTIC_PROBES)):
        for i, tpl in enumerate(probes, 1):
            q = tpl.format(company=args.company, ticker=args.ticker)
            text = ask(q)
            low = text.lower()
            # A flag inside a sentence that DENIES knowledge is the model
            # repeating the question back, not volunteering the answer.
            affirming = " ".join(
                s for s in re.split(r"(?<=[.!?])\s+", low)
                if not any(dn in s for dn in DENIALS))
            fraud = [f for f in FRAUD_FLAGS if f in affirming]
            ident = [f for f in IDENTITY_FLAGS if f in low]
            enf = [f for f in ENFORCEMENT_CUES if f in low]
            denied = any(d in low for d in DENIALS)
            if kind == "SCORED":
                fraud_hits += len(fraud)
                identity_hits += len(ident)
            record.append(dict(kind=kind, probe=q, response=text,
                               fraud_flags=fraud, identity_flags=ident,
                               enforcement_claims=enf, model_denied_knowledge=denied))
            print(f"\n{'='*74}\n{kind} PROBE {i}\n{q}\n{'-'*74}\n{text}\n{'-'*74}")
            tag = "   [not scored]" if kind == "DIAGNOSTIC" else ""
            print(f"fraud flags   : {fraud or 'none'}{tag}")
            print(f"identity flags: {ident or 'none'}   (not disqualifying)")
            if enf:
                print(f"enforcement claims: {enf}  <-- VERIFY BY HAND against "
                      f"sec.gov litigation releases")
            if denied:
                print("model explicitly disclaimed knowledge")

    scored = [r for r in record if r["kind"] == "SCORED"]
    denials = sum(1 for r in scored if r["model_denied_knowledge"])
    fraud_blind = fraud_hits == 0
    verdict = "FRAUD_BLIND" if fraud_blind else "CONTAMINATED"
    identity = "KNOWN" if identity_hits else "UNKNOWN"

    out = dict(verdict=verdict, identity_knowledge=identity, model=args.model,
               company=args.company, ticker=args.ticker,
               scored_fraud_hits=fraud_hits, scored_identity_hits=identity_hits,
               scored_probes=len(scored), explicit_denials=denials,
               tested_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               grounding="disabled - parametric memory only", transcript=record)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n{'='*74}")
    if fraud_blind:
        print(f"FRAUD_BLIND — {args.model} volunteered nothing about the case itself "
              f"across {len(scored)} scored probes ({denials} explicit denials).")
        if identity == "KNOWN":
            print(f"IDENTITY: KNOWN — {identity_hits} references to charged individuals.")
            print("They are public officers of a public company, so this was always")
            print("likely. It does NOT invalidate the benchmark - but it does mean the")
            print("fleet naming them proves recall, not inference. Score the accounting")
            print("findings; treat any identification as a control, never as a positive.")
        else:
            print("IDENTITY: UNKNOWN — the model knows neither the case nor the people.")
    else:
        print(f"CONTAMINATED — {fraud_hits} references to the case itself in scored probes.")
        print("The model knows the answer. Pick another matter; do not rationalise this.")
    print(f"{'='*74}\nwrote {args.out}")
    sys.exit(0 if fraud_blind else 1)


if __name__ == "__main__":
    main()
