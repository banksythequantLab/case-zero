#!/usr/bin/env python3
"""
CASE ZERO - corpus fetcher
Pulls a public company's contemporaneous SEC filings from EDGAR as the
investigation corpus. No corpus construction: these are real documents.

Usage:  python3 fetch_corpus.py --cik 1414767 --start 2021-01-01 --end 2024-06-30
"""
import argparse, json, os, re, time, urllib.request

UA = os.environ.get("SEC_UA", "Derek Soltis dj@soltis.info")
FORMS = {"10-K", "10-Q", "8-K", "DEF 14A", "S-1", "S-1/A", "NT 10-K", "NT 10-Q"}


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def to_text(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    txt = soup.get_text("\n")
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    return txt.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cik", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="corpus")
    args = ap.parse_args()

    cik10 = args.cik.zfill(10)
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    company = sub["name"]
    r = sub["filings"]["recent"]

    rows = [
        dict(date=d, form=f, acc=a.replace("-", ""), doc=p)
        for d, f, a, p in zip(r["filingDate"], r["form"], r["accessionNumber"], r["primaryDocument"])
        if f in FORMS and args.start <= d <= args.end and p
    ]
    rows.sort(key=lambda x: x["date"])

    os.makedirs(args.out, exist_ok=True)
    manifest, total_chars = [], 0

    for i, row in enumerate(rows, 1):
        url = f"https://www.sec.gov/Archives/edgar/data/{int(args.cik)}/{row['acc']}/{row['doc']}"
        try:
            text = to_text(get(url))
        except Exception as e:
            print(f"  !! {row['date']} {row['form']}: {e}")
            continue
        slug = f"{row['date']}_{row['form'].replace(' ', '').replace('/', '')}_{row['acc'][-6:]}.txt"
        path = os.path.join(args.out, slug)
        with open(path, "w") as fh:
            fh.write(f"SOURCE: {url}\nFORM: {row['form']}\nFILED: {row['date']}\nCOMPANY: {company}\n\n{text}")
        total_chars += len(text)
        manifest.append(dict(file=slug, form=row["form"], filed=row["date"], url=url, chars=len(text)))
        print(f"[{i}/{len(rows)}] {row['date']} {row['form']:9s} {len(text):>9,} chars")
        time.sleep(0.15)  # SEC asks <10 req/s

    with open(os.path.join(args.out, "_manifest.json"), "w") as fh:
        json.dump(dict(company=company, cik=args.cik, documents=manifest), fh, indent=2)

    tok = total_chars / 4
    print(f"\n{'='*58}\nCOMPANY        {company}\nDOCUMENTS      {len(manifest)}")
    print(f"CHARACTERS     {total_chars:,}\nEST. TOKENS    {tok:,.0f}")
    print(f"COST / PASS    ${tok/1e6*0.75:,.2f}  (Gemini 3.5 Flash input @ $0.75/M)")
    print(f"CACHED READ    ${tok/1e6*0.075:,.2f}  (@ $0.075/M)\n{'='*58}")


if __name__ == "__main__":
    main()
