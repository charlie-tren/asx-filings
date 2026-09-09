"""Sweep the market-wide announcement feed for downgrades and profit warnings.

The per-ticker index keeps five items and cannot be paged. This endpoint is
different: it is MARKET-WIDE and it does page, back to a hard cap of 100 pages
of 100 items - about 10,000 announcements, roughly 20 calendar days. That is the
only way to find a downgrade without knowing in advance which company issued it.

Written for the gold set, which is 25 positive documents to 1 negative and
therefore cannot measure stance. Nothing here is used by the collector.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import common  # noqa: E402

FEED = "https://asx.api.markitdigital.com/asx-research/1.0/markets/announcements"
OUT = pathlib.Path(__file__).resolve().parent

# Headline shapes that CAN carry a downgrade. Deliberately wide: this is a
# recall problem, not a precision one - the headlines are read by hand
# afterwards, and a downgrade missed here cannot be found any other way once
# the 20-day window rolls past it.
CANDIDATE = re.compile(
    r"trading update|guidance|profit warning|downgrade|earnings update|"
    r"market update|business update|revision|revised|update on|impairment|"
    r"write.?down|writedown|restructur|material change|outlook|"
    r"response to asx|price and volume|profit|earnings", re.I)

# Headlines that match the above and are almost never a downgrade.
NOISE = re.compile(
    r"cessation|quotation of securities|substantial holder|substantial holding|"
    r"director.s interest|proxy|notice of meeting|results of meeting|"
    r"section 708|appendix 2a|appendix 3|change of address|becoming a|"
    r"daily fund update|net tangible asset|investment update|distribution",
    re.I)


def sweep(pages: int = 100) -> list[dict]:
    cfg = common.load_config()
    seen, out = set(), []
    for page in range(1, pages + 1):
        url = (f"{FEED}?itemsPerPage=100&page={page}"
               f"&access_token={cfg['access_token']}")
        try:
            items = json.loads(common.fetch(url, cfg))["data"]["items"]
        except Exception as e:                                   # noqa: BLE001
            print(f"  page {page}: {type(e).__name__} {str(e)[:70]}", flush=True)
            continue
        if not items:
            print(f"  page {page}: empty, stopping", flush=True)
            break
        for i in items:
            k = i["documentKey"]
            if k in seen:
                continue
            seen.add(k)
            out.append(i)
        if page % 20 == 0:
            print(f"  page {page}: {len(out)} announcements so far", flush=True)
        time.sleep(0.25)
    return out


def main() -> None:
    anns = sweep()
    dates = sorted({a["date"][:10] for a in anns})
    print(f"\n{len(anns)} announcements, {dates[0]} .. {dates[-1]}, "
          f"{len({a['symbol'] for a in anns})} tickers")

    cands = [a for a in anns
             if CANDIDATE.search(a["headline"]) and not NOISE.search(a["headline"])]
    ps = [a for a in cands if a.get("isPriceSensitive")]
    print(f"{len(cands)} candidate headlines, {len(ps)} of them price-sensitive")

    (OUT / "market_sweep.json").write_text(
        json.dumps({"swept": common.now_iso(), "n_announcements": len(anns),
                    "date_range": [dates[0], dates[-1]],
                    "candidates": sorted(ps, key=lambda a: a["date"])},
                   indent=1, ensure_ascii=False), encoding="utf-8")
    for a in sorted(ps, key=lambda a: a["date"]):
        print(f"  {a['date'][:10]} {a['symbol']:5} {a['fileSize']:>7} "
              f"{a['headline'][:64]}")


if __name__ == "__main__":
    main()
