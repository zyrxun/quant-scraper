# quant-scraper

Scrapes **quant trading / research roles at 23 prop-trading firms** via public job-board JSON APIs and filters to math-heavy roles only — drops engineers, ops, sales, business analysts, recruiting and other fluff.

Firms covered: SIG Susquehanna, Jane Street, DRW, Optiver, IMC, Jump Trading, Akuna Capital, Tower Research, Five Rings, Squarepoint, Chicago Trading Co, Flow Traders, DV Trading, Gelber Group, PDT Partners, Geneva Trading, Trillium, Radix (univ + exp), XTX Markets, Belvedere, Old Mission Capital, Teza.

Hudson River Trading + Citadel Securities are Cloudflare-walled to plain HTTP → listed as manual-check links in every report.

## Usage

```bash
python3 quant_scraper.py            # full report -> out/latest.md + dated CSV + JSON
python3 quant_scraper.py --fresh    # only jobs not seen on a previous run (out/seen.json)
python3 quant_scraper.py --debug    # per-firm kept/excluded stats
python3 quant_scraper.py --selftest # filter fixtures + parser checks
```

Stdlib only. Python 3.8+.

## How it works

- **Sources**: Greenhouse `boards/v1` JSON, Lever API, Ashby posting-api, SIG's Jibe API (`careers.sig.com/api/jobs` — note: `offset` is ignored there, so it pages via `tags1` facet partitions, limit caps at 100).
- **Filter**: `EXCLUDE` regex wins over `INCLUDE` regex (both at the top of `quant_scraper.py` — edit them to retune). Roles are tagged INTERN / NEW-GRAD / EXP and sorted internships-first.
- **Freshness**: every URL is recorded in `out/seen.json`; `--fresh` surfaces only first-time sightings.
