"""Daily collector.

INGESTION IS THE MARKET-WIDE FEED. `/markets/announcements` returns
announcements for every listed company and pages back to a hard cap of 100
pages of 100 items: measured 9,900 announcements over 20 calendar days, about
550 a day across 1,845 tickers. The per-ticker index keeps five items and will
not page at all, under any parameter tried.

Migrated 09/09/2026 after checking coverage rather than assuming it. Against
the per-ticker index for all 67 universe tickers, the feed carried 227
announcements the five-item index could not see, and missed 23. Every one of
the 23 was a substantial-holding notice or an index rebalance: the S&P DJI
rebalance is filed under MIN rather than under each affected company, and
shareholding notices are filed under the HOLDER's symbol (NXL, AFG) rather than
the company held. Two were absent entirely. **Not one was a results, outlook,
guidance or trading document**, which is the only class this project reads.

So the per-ticker loop survives as a LIVENESS PROBE, not as ingestion. It costs
67 index calls and about a minute - the ninety minutes in the old version was
document downloads, not indexing - and it is the only thing that can tell a
delisted code (400 Symbol not found) from a company with nothing to say. The
sweep cannot: absence from a market feed is the normal state.

The PDF is transport. Text is extracted here and committed; the PDF is
discarded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from pypdf import PdfReader

FEED = "/markets/announcements"


def feed_url(cfg: dict, page: int) -> str:
    # itemsPerPage works; pageSize is silently ignored and returns 25.
    return (f"{cfg['index_host']}{FEED}?itemsPerPage={cfg['feed_items_per_page']}"
            f"&page={page}&access_token={cfg['access_token']}")


def index_url(cfg: dict, ticker: str) -> str:
    return (f"{cfg['index_host']}/companies/{ticker}/announcements"
            f"?pageSize={cfg['index_page_size']}")


def doc_url(cfg: dict, key: str) -> str:
    return f"{cfg['doc_host']}/file/{key}?access_token={cfg['access_token']}"


def wanted(headline: str, cfg: dict) -> tuple[bool, str]:
    """Headline triage only. Substance is checked after extraction, because the
    headline lies: MAD and PNV both announced "FY26 Results Presentation" and
    both are one-page PDFs linking to a webcast recording."""
    h = headline.lower()
    for s in cfg["skip_headline_any"]:
        if s in h:
            return False, f"skip:{s}"
    for k in cfg["keep_headline_any"]:
        if k in h:
            return True, ""
    return False, "not-results-shaped"


def size_kb(file_size: str) -> int:
    return int(re.sub(r"\D", "", file_size or "") or 0)


def forward_markers(text: str, cfg: dict) -> int:
    low = text.lower()
    return sum(low.count(m) for m in cfg["substance"]["forward_markers"])


def record(con, table: str, row: dict, when: str | None = None) -> None:
    """Write one record to the committed ledger AND the derived database."""
    common.append(table, row, when=when)
    cols = common.COLUMNS[table]
    con.execute(f"INSERT OR REPLACE INTO {table} "
                f"VALUES({','.join('?' * len(cols))})",
                [row.get(c) for c in cols])


def sweep_market(cfg, con, run_id) -> tuple[list[dict], int, int]:
    """Page the market-wide feed. Returns (items, pages_ok, pages_attempted).

    Every page outcome is recorded. A partial sweep is the new failure mode:
    the old one was a ticker whose index would not answer, this one is a sweep
    that stopped early and looks exactly like a quiet day.
    """
    items, seen = [], set()
    pages_ok = pages = 0
    for page in range(1, cfg["feed_max_pages"] + 1):
        pages += 1
        try:
            got = json.loads(common.fetch(feed_url(cfg, page), cfg))["data"]["items"]
        except Exception as e:                                   # noqa: BLE001
            record(con, "fetches", {"run_id": run_id, "ticker": f"page:{page}",
                                    "ok": 0, "items": None, "error": str(e)[:800],
                                    "fetched_at": common.now_iso()})
            print(f"  page {page}: FAIL {str(e)[:90]}", flush=True)
            continue
        pages_ok += 1
        record(con, "fetches", {"run_id": run_id, "ticker": f"page:{page}",
                               "ok": 1, "items": len(got), "error": None,
                               "fetched_at": common.now_iso()})
        if not got:
            break                       # past the end of the feed, not an error
        for i in got:
            if i["documentKey"] not in seen:
                seen.add(i["documentKey"])
                items.append(i)
        time.sleep(cfg["http"]["pause_seconds"])
    return items, pages_ok, pages


def probe_universe(cfg, con, run_id, universe) -> int:
    """Liveness only: no downloads. The one thing the sweep cannot do is tell a
    delisted code from a company that simply has not announced anything."""
    ok = 0
    for entry in universe:
        code = entry["code"]
        try:
            got = json.loads(common.fetch(index_url(cfg, code), cfg))["data"]["items"]
        except Exception as e:                                   # noqa: BLE001
            record(con, "fetches", {"run_id": run_id, "ticker": code, "ok": 0,
                                    "items": None, "error": str(e)[:800],
                                    "fetched_at": common.now_iso()})
            continue
        ok += 1
        record(con, "fetches", {"run_id": run_id, "ticker": code, "ok": 1,
                               "items": len(got), "error": None,
                               "fetched_at": common.now_iso()})
        time.sleep(cfg["http"]["pause_seconds"] / 2)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, help="limit the sweep, for testing")
    ap.add_argument("--no-probe", action="store_true",
                    help="skip the per-ticker liveness probe")
    ap.add_argument("--dry-run", action="store_true",
                    help="sweep and record, download no documents")
    args = ap.parse_args()

    cfg = common.load_config()
    universe = common.load_universe()
    codes = {t["code"] for t in universe}
    if args.pages:
        # --pages is a test flag. Scale the completeness guard with it, or every
        # deliberate short run exits 1 and the exit code stops meaning anything.
        cfg["feed_max_pages"] = args.pages
        cfg["feed_min_pages_ok"] = args.pages

    # Rebuild from the ledger. corpus.db is gitignored, so a CI checkout has
    # none, and opening an empty one made every announcement look new.
    con = common.rebuild_db()
    run_id = uuid.uuid4().hex[:12]
    started_at = common.now_iso()
    con.execute("INSERT INTO runs(run_id,started_at,tickers) VALUES(?,?,?)",
                (run_id, started_at, len(universe)))
    con.commit()

    tmp = common.ROOT / "data" / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    probe_ok = 0
    if not args.no_probe:
        probe_ok = probe_universe(cfg, con, run_id, universe)
        con.commit()
        print(f"liveness probe: {probe_ok}/{len(universe)} universe indexes answered",
              flush=True)

    items, pages_ok, pages = sweep_market(cfg, con, run_id)
    con.commit()
    dates = sorted({i["date"][:10] for i in items}) or ["?", "?"]
    print(f"sweep: {len(items):,} announcements over {dates[0]}..{dates[-1]} "
          f"from {pages_ok}/{pages} pages", flush=True)

    new_ann = new_doc = 0
    parse_failures: list[str] = []

    for it in items:
        key, code = it["documentKey"], it["symbol"]
        in_universe = code in codes

        # Record metadata for universe tickers (all types) and for anything the
        # ASX flagged price-sensitive market-wide. Everything else - director
        # interests, quotation applications, substantial holdings for 1,800
        # companies we do not follow - is 74% of the feed and will never be read.
        if not (in_universe or it.get("isPriceSensitive")):
            continue

        if not con.execute("SELECT 1 FROM announcements WHERE document_key=?",
                           (key,)).fetchone():
            record(con, "announcements", {
                "document_key": key, "ticker": code,
                "announced_at": it["date"], "headline": it["headline"],
                "announcement_type": (it.get("announcementTypes") or [None])[0]
                                     if isinstance(it.get("announcementTypes"), list)
                                     else it.get("announcementTypes"),
                "price_sensitive": int(bool(it.get("isPriceSensitive"))),
                "file_size": it.get("fileSize"),
                "first_seen": common.now_iso()}, when=it["date"])
            new_ann += 1

        if not in_universe or args.dry_run:
            continue
        if con.execute("SELECT 1 FROM documents WHERE document_key=? "
                       "UNION SELECT 1 FROM rejections WHERE document_key=?",
                       (key, key)).fetchone():
            continue

        keep, why = wanted(it["headline"], cfg)
        if not keep:
            record(con, "rejections", {"document_key": key, "ticker": code,
                                       "headline": it["headline"], "reason": why,
                                       "detail": None,
                                       "rejected_at": common.now_iso()})
            continue

        kb = size_kb(it.get("fileSize", ""))
        if kb > cfg["max_document_kb"]:
            record(con, "rejections", {"document_key": key, "ticker": code,
                                       "headline": it["headline"],
                                       "reason": "too-large", "detail": f"{kb}KB",
                                       "rejected_at": common.now_iso()})
            continue

        try:
            raw = common.fetch(doc_url(cfg, key), cfg, binary=True)
        except Exception as e:                                   # noqa: BLE001
            # Retryable and NOT settled: the document is still in the window.
            print(f"{code}: doc fetch failed {key}: {str(e)[:90]}", flush=True)
            continue

        if not common.pdf_is_complete(raw):
            print(f"{code}: TRUNCATED {len(raw):,}B {key} (retry tomorrow)", flush=True)
            continue

        path = tmp / f"{key}.pdf"
        try:
            path.write_bytes(raw)
            reader = PdfReader(path)
            text = "".join((p.extract_text() or "") for p in reader.pages)
            pages_n = len(reader.pages)
        except Exception as e:                                   # noqa: BLE001
            # RETRYABLE. The first CI run wrote 32 of these down as permanent
            # verdicts about the documents when the real cause was a missing
            # cryptography extra on the runner.
            print(f"{code}: parse failed {key}: {str(e)[:110]} (retry tomorrow)",
                  flush=True)
            parse_failures.append(f"{code} {it['headline'][:40]}: {str(e)[:80]}")
            continue
        finally:
            path.unlink(missing_ok=True)

        s = cfg["substance"]
        fwd = forward_markers(text, cfg)
        if len(text) > s["max_chars"]:
            record(con, "rejections", {"document_key": key, "ticker": code,
                                       "headline": it["headline"], "reason": "too-long",
                                       "detail": f"{pages_n}pp {len(text)}ch",
                                       "rejected_at": common.now_iso()})
            continue
        if pages_n < s["min_pages"] or len(text) < s["min_chars"] \
                or fwd < s["min_forward_markers"]:
            record(con, "rejections", {"document_key": key, "ticker": code,
                                       "headline": it["headline"], "reason": "thin",
                                       "detail": f"{pages_n}pp {len(text)}ch fwd={fwd}",
                                       "rejected_at": common.now_iso()})
            continue

        out = common.TEXT_DIR / code / f"{key}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        record(con, "documents", {
            "document_key": key, "ticker": code, "bytes": len(raw),
            "pages": pages_n, "chars": len(text), "forward_markers": fwd,
            "sha256": common.sha256(raw),
            "text_path": str(out.relative_to(common.ROOT)).replace("\\", "/"),
            "stored_at": common.now_iso()})
        new_doc += 1
        print(f"{code}: STORED {pages_n}pp {len(text):,}ch fwd={fwd}  "
              f"{it['headline'][:50]}", flush=True)
        con.commit()

    record(con, "runs", {"run_id": run_id, "started_at": started_at,
                         "finished_at": common.now_iso(), "tickers": len(universe),
                         "tickers_ok": probe_ok, "new_announcements": new_ann,
                         "new_documents": new_doc})
    con.commit()

    print(f"\nrun {run_id}: {len(items):,} announcements swept, "
          f"{new_ann} new recorded, {new_doc} new documents")

    # A sweep that stopped early looks exactly like a quiet day from the outside.
    if pages_ok < cfg["feed_min_pages_ok"]:
        print(f"FAIL: sweep reached only {pages_ok} pages, "
              f"minimum {cfg['feed_min_pages_ok']}", file=sys.stderr)
        return 1
    if parse_failures and new_doc == 0:
        print(f"FAIL: {len(parse_failures)} documents fetched and NONE could be "
              f"opened. First: {parse_failures[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
