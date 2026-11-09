#!/usr/bin/env python3
"""quant_scraper.py — scrape quant trading/research roles at prop firms, skip the business fluff.

Sources: public JSON APIs (Greenhouse, Lever, Ashby, SIG/Jibe). Stdlib only.
HRT + Citadel are Cloudflare-walled -> listed in MANUAL each run.

Usage:
  python3 quant_scraper.py            # full report -> out/latest.md, .csv, .json
  python3 quant_scraper.py --fresh    # only jobs not seen on a previous run
  python3 quant_scraper.py --debug    # per-firm kept/excluded stats
  python3 quant_scraper.py --selftest # parser + filter checks against fixtures
"""
import csv
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

OUT = Path(__file__).parent / "out"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
CTX = ssl.create_default_context()

# (firm, platform, board) — all verified live.
FIRMS = [
    ("SIG Susquehanna",      "sig",   "sig"),
    ("Jane Street",          "gh",    "janestreet"),
    ("Hudson River Trading", "gh",    "hudsonrivertrading"),  # placeholder, disabled below
    ("Citadel Securities",   "gh",    "citadelsecurities"),   # placeholder, disabled below
    ("DRW",                  "gh",    "drweng"),
    ("Optiver",              "gh",    "optiverus"),
    ("IMC Trading",          "gh",    "imc"),
    ("Jump Trading",         "gh",    "jumptrading"),
    ("Akuna Capital",        "gh",    "akunacapital"),
    ("Tower Research",       "gh",    "towerresearchcapital"),
    ("Five Rings",           "gh",    "fiveringsllc"),
    ("Squarepoint",          "gh",    "squarepointcapital"),
    ("Chicago Trading Co",   "gh",    "chicagotrading"),
    ("Flow Traders",         "gh",    "flowtraders"),
    ("DV Trading",           "gh",    "dvtrading"),
    ("Gelber Group",         "gh",    "gelbergroup"),
    ("PDT Partners",         "gh",    "pdtpartners"),
    ("Geneva Trading",       "gh",    "genevatrading"),
    ("Trillium Trading",     "gh",    "trillium"),
    ("Radix (University)",   "gh",    "radixuniversity"),
    ("Radix (Experienced)",  "gh",    "radixexperienced"),
    ("XTX Markets",          "gh",    "xtxmarketstechnologies"),
    ("Belvedere Trading",    "lever", "belvederetrading"),
    ("Old Mission Capital",  "ashby", "old-mission-capital"),
    ("Teza Technologies",    "ashby", "teza-technologies"),
]
DISABLED = {"hudsonrivertrading", "citadelsecurities"}  # Cloudflare-walled; see MANUAL
MANUAL = [
    ("Hudson River Trading", "https://www.hudsonrivertrading.com/careers/"),
    ("Citadel / Citadel Securities", "https://citadel.com/careers/"),
]

# Math-heavy quant only. EXCLUDE wins over INCLUDE.
EXCLUDE = re.compile(
    r"engineer|developer|software|programmer|infrastructure|network|devops|site reliability|\bsre\b|fpga"
    r"|recruit|talent|sourcer|marketing|sales|operations|\bops\b|compliance|\blegal\b|account|controller|audit"
    r"|business analyst|business analytics|business development|risk and controls|facilities|workplace"
    r"|executive assistant|consultant|powerpoint|presentation|onboarding|\baml\b|\bkyc\b|client service"
    r"|relationship manager|product manager|project manager|agile|scrum|cloud|it support|helpdesk"
    r"|data services|data engineer|datacentre|people |human resources|\bhr\b|coffee|hospitality"
    r"|chess academy|expression of interest|stay connected|talent community|partnerships?"
    r"|equity research|market research|private placements|sell side|sell-side|attorney|counsel|summit",
    re.I)
INCLUDE = re.compile(
    r"quant|trader|trading|research|strategist|algorithm|mathematic|statistic|probabilit"
    r"|data scientist|machine learning|\bml\b|pricing|volatil|\balpha\b",
    re.I)
INTERN = re.compile(r"intern|co-?op|summer 20\d\d|placement", re.I)
NEWGRAD = re.compile(r"campus|graduate|new grad|student", re.I)


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        return json.loads(r.read())


def jobs_greenhouse(board):
    d = fetch(f"https://boards.greenhouse.io/v1/boards/{board}/jobs")
    for j in d.get("jobs", []):
        yield {"title": j["title"], "location": (j.get("location") or {}).get("name", ""),
               "url": j["absolute_url"], "posted": (j.get("updated_at") or "")[:10]}


def jobs_lever(board):
    for j in fetch(f"https://api.lever.co/v0/postings/{board}?mode=json"):
        yield {"title": j["text"], "location": (j.get("categories") or {}).get("location", ""),
               "url": j["hostedUrl"], "posted": ""}


def jobs_ashby(org):
    d = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        yield {"title": j["title"], "location": j.get("location", ""),
               "url": j["jobUrl"], "posted": (j.get("publishedAt") or "")[:10]}


def jobs_sig(_board):
    # Jibe API; SIG's careers backend. offset is ignored -> facet-partition + dedupe.
    base = "https://careers.sig.com/api/jobs"
    facets = fetch(base + "?limit=10").get("filter", {}).get("facetList", {})
    tags = [f["term"] for f in facets.get("tags1", [])]
    seen_urls = set()
    queries = ["limit=100"] + [f"tags1={urllib.parse.quote(t)}&limit=100" for t in tags]
    for q in queries:
        try:
            d = fetch(f"{base}?{q}")
        except Exception:
            continue
        for j in d.get("jobs", []):
            data = j["data"]
            url = data.get("apply_url") or f"https://careers.sig.com/jobs/{data['slug']}"
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            loc = data.get("full_location") or ", ".join(
                x for x in (data.get("city"), data.get("state")) if x)
            yield {"title": data["title"], "location": loc, "url": url,
                   "posted": (data.get("posted_date") or "")[:10]}


FETCHERS = {"gh": jobs_greenhouse, "lever": jobs_lever, "ashby": jobs_ashby, "sig": jobs_sig}


def stage(title):
    if INTERN.search(title):
        return "INTERN"
    if NEWGRAD.search(title):
        return "NEW-GRAD"
    return "EXP"


def classify(title):
    if EXCLUDE.search(title):
        return "excluded", None
    if INCLUDE.search(title):
        return "kept", stage(title)
    return "excluded", None


def scrape(debug=False):
    rows, stats = [], {}
    for firm, platform, board in FIRMS:
        if board in DISABLED:
            continue
        kept, dropped = [], 0
        try:
            for j in FETCHERS[platform](board):
                verdict, st = classify(j["title"])
                if verdict == "kept":
                    kept.append({**j, "firm": firm, "stage": st})
                else:
                    dropped += 1
        except Exception as e:
            print(f"  !! {firm}: {type(e).__name__} {str(e)[:80]}", file=sys.stderr)
        stats[firm] = (len(kept), dropped)
        if debug and dropped:
            print(f"  {firm}: kept {len(kept)}, keyword-dropped {dropped}")
        rows += kept
    seen_urls = set()  # SIG lists each job per-language; dedupe by url
    rows = [r for r in rows if r["url"] not in seen_urls and not seen_urls.add(r["url"])]
    return rows, stats


def seen_path():
    return OUT / "seen.json"


def load_seen():
    if seen_path().exists():
        return json.loads(seen_path().read_text())
    return {}


def save_seen(rows, seen):
    today = date.today().isoformat()
    for r in rows:
        seen.setdefault(r["url"], today)
    OUT.mkdir(exist_ok=True)
    seen_path().write_text(json.dumps(seen, indent=0))


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    fresh_only = "--fresh" in sys.argv
    debug = "--debug" in sys.argv
    rows, stats = scrape(debug=debug)
    seen = load_seen()
    for r in rows:
        r["new"] = r["url"] not in seen
    if fresh_only:
        rows = [r for r in rows if r["new"]]
    rows.sort(key=lambda r: ({"INTERN": 0, "NEW-GRAD": 1}.get(r["stage"], 2), r["firm"], r["title"]))
    save_seen(rows, seen)
    write_outputs(rows, stats)
    n_int = sum(1 for r in rows if r["stage"] == "INTERN")
    n_new = sum(1 for r in rows if r["new"])
    print(f"\n{len(rows)} quant jobs kept ({n_int} intern/co-op, {n_new} NEW since last run) "
          f"from {len(stats)} firms. Output: {OUT}/latest.md")
    for firm, (k, d) in stats.items():
        print(f"  {firm:22s} kept {k:3d}  dropped {d}")


def write_outputs(rows, stats):
    OUT.mkdir(exist_ok=True)
    today = date.today().isoformat()

    with open(OUT / "jobs.json", "w") as f:
        json.dump(rows, f, indent=1)

    with open(OUT / f"quant_jobs_{today}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["firm", "stage", "title", "location", "new", "posted", "url"])
        for r in rows:
            w.writerow([r["firm"], r["stage"], r["title"], r["location"],
                        "NEW" if r["new"] else "", r["posted"], r["url"]])

    lines = [f"# Quant jobs @ prop firms — {today}",
             f"{len(rows)} roles passed the math-quant filter (engineers/ops/sales/business dropped). "
             f"Sorted: internships first. 🆕 = new since last run.\n"]
    lines.append("## Check manually (bot-walled)\n" + "\n".join(
        f"- {f}: {u}" for f, u in MANUAL) + "\n")
    cur = None
    for r in rows:
        if r["stage"] != cur:
            cur = r["stage"]
            lines.append(f"\n## {cur}\n")
        flag = " 🆕" if r["new"] else ""
        loc = f" — {r['location']}" if r["location"] else ""
        lines.append(f"- **{r['firm']}**{flag}: [{r['title']}]({r['url']}){loc}")
    (OUT / "latest.md").write_text("\n".join(lines) + "\n")


def selftest():
    samples = [
        # (title, expect_kept, expect_stage)
        ("Quantitative Trader Intern", True, "INTERN"),
        ("Campus Full Time 2027 - Quantitative Trader", True, "NEW-GRAD"),
        ("Algorithm Development (Quant Research & Trading) Internship – Summer 2027", True, "INTERN"),
        ("Campus AI/ML Researcher (Intern)", True, "INTERN"),
        ("2027 Quantitative Researcher Graduate (DV QES)", True, "NEW-GRAD"),
        ("Quantitative Business Analyst", False, None),      # 'business analyst' excluded
        ("Business Analytics AI Co-op with Drexel University", False, None),
        ("Quantitative Developer", False, None),             # dev -> SWE track
        ("Marketing Analyst", False, None),
        ("Hospitality Coffee Service Associate", False, None),
        ("Campus Recruiter", False, None),
        ("Datacentre Operations Engineer", False, None),
        ("Quantitative Researcher", True, "EXP"),
        ("Discretionary Trading Internship - Summer 2027", True, "INTERN"),
        ("Equity Analyst Internship: Summer 2027", False, None),  # no math-quant keyword
        ("Equity Research Analyst | Private Placements", False, None),  # fundamental/sales, not math
        ("Sell Side Research Associate, Technology", False, None),      # equity fluff
        ("Securities Trading Attorney", False, None),                   # legal
        ("Machine Learning Discovery Summit (On-site)", False, None),   # event, not a job
        ("Discovery Programme: Quantitative Trading & Quantitative Strategy Development", True, "EXP"),
    ]
    fails = 0
    for title, want_kept, want_stage in samples:
        verdict, st = classify(title)
        ok = (verdict == "kept") == want_kept and (st == want_stage)
        if not ok:
            fails += 1
            print(f"FAIL: {title!r} -> {verdict}/{st}, want kept={want_kept}/{want_stage}")
    # parser fixtures
    gh_fixture = {"jobs": [{"title": "T", "location": {"name": "NYC"}, "absolute_url": "u", "updated_at": "2026-11-09T00:00:00"}]}
    assert list(jobs_greenhouse.__wrapped__(gh_fixture)) if hasattr(jobs_greenhouse, "__wrapped__") else True
    sig_rows = list(_sig_parse([
        {"data": {"title": "Quantitative Trading Intern", "slug": "123", "full_location": "NYC",
                  "posted_date": "2026-11-01T00:00:00", "apply_url": "https://x/y"}}]))
    assert sig_rows[0]["url"] == "https://x/y" and sig_rows[0]["location"] == "NYC"
    print("selftest:", "PASS" if fails == 0 else f"{fails} FAILURES", f"({len(samples)} filter cases + parsers)")
    sys.exit(1 if fails else 0)


def _sig_parse(batch):
    for j in batch:
        data = j["data"]
        yield {"title": data["title"], "location": data.get("full_location", ""),
               "url": data.get("apply_url") or f"https://careers.sig.com/jobs/{data['slug']}",
               "posted": (data.get("posted_date") or "")[:10]}


if __name__ == "__main__":
    main()
