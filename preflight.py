#!/usr/bin/env python3
"""Pre-deploy checks. Run this before deploy.sh and before the demo.

Every check is something that has a real chance of being wrong and a cheap way
to find out. Nothing here needs a deployed service.

    python3 preflight.py
"""
import importlib.util, json, os, subprocess, sys
from pathlib import Path

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
results = []


def check(name, fn, fatal=True):
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = (FAIL if fatal else WARN), f"{type(e).__name__}: {e}"
    results.append((status, name, detail))


# ------------------------------------------------------------------ checks
def corpus():
    d = Path("corpus")
    if not d.is_dir():
        return FAIL, "corpus/ missing — run fetch_corpus.py"
    txt = list(d.glob("*.txt"))
    chars = sum(f.stat().st_size for f in txt)
    tok = chars / 4
    return (OK if txt else FAIL,
            f"{len(txt)} documents, ~{tok:,.0f} tokens, ~${tok/1e6*0.75:.2f}/pass")


def answer_key_isolated():
    """The complaint must never be reachable from the fleet's corpus dir."""
    stray = [p.name for p in Path("corpus").glob("*complaint*")] if Path("corpus").is_dir() else []
    di = Path(".dockerignore").read_text() if Path(".dockerignore").exists() else ""
    ignored = all(x in di for x in ("complaint.pdf", "complaint.txt", "ground_truth.json"))
    if stray:
        return FAIL, f"answer key inside corpus/: {stray}"
    if not ignored:
        return FAIL, ".dockerignore does not exclude complaint/ground_truth"
    return OK, "complaint + ground_truth excluded from corpus and image"


def ground_truth():
    p = Path("ground_truth.json")
    if not p.exists():
        return WARN, "ground_truth.json missing — scoring unavailable"
    g = json.loads(p.read_text())
    f = g.get("findings", [])
    tiers = {t: sum(1 for x in f if x.get("tier") == t)
             for t in ("TIER_A", "TIER_B", "TIER_C")}
    scoreable = tiers["TIER_A"] + tiers["TIER_B"]
    return OK, f"{len(f)} findings — {scoreable} scoreable, {tiers['TIER_C']} calibration controls"


def deps():
    missing = [m for m in ("google.adk", "google.genai", "fastapi", "uvicorn", "pydantic")
               if not importlib.util.find_spec(m)]
    return (FAIL, f"missing: {missing}") if missing else (OK, "adk, genai, fastapi, pydantic present")


def firestore_dep():
    if not importlib.util.find_spec("google.cloud.firestore"):
        return WARN, "google-cloud-firestore not installed (needed only for cloud mode)"
    from importlib.metadata import version
    return OK, f"google-cloud-firestore {version('google-cloud-firestore')}"


def api_key():
    if os.environ.get("GOOGLE_API_KEY"):
        return OK, "GOOGLE_API_KEY set"
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") and os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return OK, "Vertex AI mode configured"
    return WARN, "no GOOGLE_API_KEY and no Vertex config — demo mode only"


def cold_prompt_evidence():
    """The single most important unchecked assumption in this project."""
    if Path("cold_prompt_result.json").exists():
        r = json.loads(Path("cold_prompt_result.json").read_text())
        v = r.get("verdict", "?")
        ident = r.get("identity_knowledge", "?")
        if v in ("CLEAN", "FRAUD_BLIND"):
            note = f"{v}, {r.get('scored_fraud_hits', 0)} fraud hits / {r.get('scored_probes','?')} probes"
            if ident == "KNOWN":
                return WARN, (f"{note} — identity KNOWN: score accounting findings only, "
                              f"treat identifications as controls")
            return OK, note
        return FAIL, f"contamination test: {v}"
    return FAIL, ("contamination test NEVER RUN — the blindness claim is unverified. "
                  "Run cold_prompt_test.py before building anything else.")


def port_env():
    src = Path("casezero/board.py").read_text()
    return (OK, "board honours $PORT") if 'environ.get("PORT"' in src \
        else (FAIL, "board does not read $PORT — Cloud Run will fail health checks")


def cpu_throttling_flag():
    if not Path("deploy.sh").exists():
        return WARN, "deploy.sh missing"
    s = Path("deploy.sh").read_text()
    if "--no-cpu-throttling" not in s:
        return FAIL, ("deploy.sh lacks --no-cpu-throttling — background investigation "
                      "threads will freeze the moment the response is sent")
    return OK, "--no-cpu-throttling present (background threads keep CPU)"


def tests():
    out = []
    for t in ("tests/test_loop.py", "tests/test_resilience.py", "tests/test_firestore.py",
              "tests/test_forensic.py", "tests/test_ledger.py",
              "tests/test_consolidate.py", "tests/test_passages.py"):
        if not Path(t).exists():
            continue
        r = subprocess.run([sys.executable, t], capture_output=True, text=True)
        last = (r.stdout.strip().splitlines() or ["no output"])[-1]
        out.append(f"{Path(t).stem}: {last}")
        if r.returncode != 0:
            return FAIL, " | ".join(out)
    return OK, " | ".join(out)


# -------------------------------------------------------------------- run
for name, fn, fatal in [
    ("corpus present and costed", corpus, True),
    ("answer key isolated from fleet", answer_key_isolated, True),
    ("ground truth loadable", ground_truth, False),
    ("python dependencies", deps, True),
    ("firestore client", firestore_dep, False),
    ("model credentials", api_key, False),
    ("board honours $PORT", port_env, True),
    ("cloud run cpu allocation", cpu_throttling_flag, True),
    ("offline test suites", tests, True),
    ("CONTAMINATION TEST RUN", cold_prompt_evidence, True),
]:
    check(name, fn, fatal)

W = max(len(n) for _, n, _ in results)
print(f"\n{'='*88}\nCASE ZERO — PREFLIGHT\n{'='*88}")
for status, name, detail in results:
    mark = {"PASS": "  ok ", "WARN": " warn", "FAIL": " FAIL"}[status]
    print(f"{mark}  {name:<{W}}  {detail}")

fails = [r for r in results if r[0] == FAIL]
warns = [r for r in results if r[0] == WARN]
print("=" * 88)
print(f"{len(results)-len(fails)-len(warns)} pass · {len(warns)} warn · {len(fails)} fail")
if fails:
    print("\nBLOCKERS:")
    for _, n, d in fails:
        print(f"  - {n}: {d}")
print()
sys.exit(1 if fails else 0)
