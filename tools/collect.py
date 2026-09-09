"""Daily collector. Reads every ticker's announcement index, records what it
saw, and stores the text of anything results-shaped.

THE POINT OF RUNNING DAILY: the free index returns the last five announcements
per ticker and will not paginate, so a document that falls out of the window is
gone with no way to fetch it again. Of 20 tickers probed on 09/09/2026, eight
had already lost their August FY26 results. A missed week in reporting season
is a permanent hole in the corpus.

The PDF is transport, not corpus. Text is extracted here and committed; the PDF
is discarded, because 200 names of 3MB decks a year does not belong in git.
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


def record(con, table: str, row: dict) -> None:
    """Write one record to the committed ledger AND the derived database.

    Ledger first, and fsynced, because it is the artifact that survives. The
    database is an index over it and is rebuilt by `common.rebuild_db()`.
    """
    common.append(table, row)
    cols = common.COLUMNS[table]
    con.execute(f"INSERT OR REPLACE INTO {table} "
                f"VALUES({','.join('?' * len(cols))})",
                [row.get(c) for c in cols])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated tickers, for testing")
    ap.add_argument("--dry-run", action="store_true",
                    help="read indexes and record them, download no documents")
    args = ap.parse_args()

    cfg = common.load_config()
    universe = common.load_universe()
    if args.only:
        keep = {t.strip().upper() for t in args.only.split(",")}
        universe = [t for t in universe if t["code"] in keep]

    con = common.connect()
    run_id = uuid.uuid4().hex[:12]
    started_at = common.now_iso()
    con.execute("INSERT INTO runs(run_id,started_at,tickers) VALUES(?,?,?)",
                (run_id, started_at, len(universe)))
    con.commit()

    tmp = common.ROOT / "data" / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    ok_tickers = new_ann = new_doc = 0

    for entry in universe:
        code = entry["code"]
        try:
            items = json.loads(common.fetch(index_url(cfg, code), cfg))["data"]["items"]
        except Exception as e:                                  # noqa: BLE001
            # Recorded, not swallowed. A ticker whose index fails every day is
            # otherwise indistinguishable from a ticker with nothing to announce,
            # and the window will have moved on before anyone notices.
            record(con, "fetches", {"run_id": run_id, "ticker": code, "ok": 0,
                                    "items": None, "error": str(e)[:800],
                                    "fetched_at": common.now_iso()})
            con.commit()
            print(f"{code}: INDEX FAIL {str(e)[:120]}", flush=True)
            continue

        ok_tickers += 1
        record(con, "fetches", {"run_id": run_id, "ticker": code, "ok": 1,
                                "items": len(items), "error": None,
                                "fetched_at": common.now_iso()})

        for it in items:
            key = it["documentKey"]

            if not con.execute("SELECT 1 FROM announcements WHERE document_key=?",
                               (key,)).fetchone():
                record(con, "announcements", {
                    "document_key": key, "ticker": code,
                    "announced_at": it["date"], "headline": it["headline"],
                    "announcement_type": it.get("announcementType"),
                    "price_sensitive": int(bool(it.get("isPriceSensitive"))),
                    "file_size": it.get("fileSize"),
                    "first_seen": common.now_iso()})
                new_ann += 1

            settled = con.execute(
                "SELECT 1 FROM documents WHERE document_key=? "
                "UNION SELECT 1 FROM rejections WHERE document_key=?",
                (key, key)).fetchone()
            if settled or args.dry_run:
                continue

            keep, why = wanted(it["headline"], cfg)
            if not keep:
                record(con, "rejections", {"document_key": key, "ticker": code,
                                           "headline": it["headline"],
                                           "reason": why, "detail": None,
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
            except Exception as e:                              # noqa: BLE001
                # Deliberately NOT recorded as a rejection. This is retryable and
                # the document is still in the window, so leaving it unsettled
                # means tomorrow's run picks it up again.
                print(f"{code}: doc fetch failed {key}: {str(e)[:100]}", flush=True)
                continue

            if not common.pdf_is_complete(raw):
                print(f"{code}: TRUNCATED {len(raw):,}B {key} (retry tomorrow)",
                      flush=True)
                continue

            path = tmp / f"{key}.pdf"
            try:
                path.write_bytes(raw)
                reader = PdfReader(path)
                text = "".join((p.extract_text() or "") for p in reader.pages)
                pages = len(reader.pages)
            except Exception as e:                              # noqa: BLE001
                record(con, "rejections", {"document_key": key, "ticker": code,
                                           "headline": it["headline"],
                                           "reason": "parse-failed",
                                           "detail": str(e)[:400],
                                           "rejected_at": common.now_iso()})
                continue
            finally:
                path.unlink(missing_ok=True)

            s = cfg["substance"]
            fwd = forward_markers(text, cfg)
            if len(text) > s["max_chars"]:
                # Statutory accounts and the like. Recorded rather than dropped,
                # so it is visible that the document was seen and judged.
                record(con, "rejections", {
                    "document_key": key, "ticker": code,
                    "headline": it["headline"], "reason": "too-long",
                    "detail": f"{pages}pp {len(text)}ch",
                    "rejected_at": common.now_iso()})
                continue
            if pages < s["min_pages"] or len(text) < s["min_chars"] \
                    or fwd < s["min_forward_markers"]:
                # The webcast-notice trap: headline says results, document is a
                # one-page link to a video.
                record(con, "rejections", {
                    "document_key": key, "ticker": code,
                    "headline": it["headline"], "reason": "thin",
                    "detail": f"{pages}pp {len(text)}ch fwd={fwd}",
                    "rejected_at": common.now_iso()})
                continue

            out = common.TEXT_DIR / code / f"{key}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            record(con, "documents", {
                "document_key": key, "ticker": code, "bytes": len(raw),
                "pages": pages, "chars": len(text), "forward_markers": fwd,
                "sha256": common.sha256(raw),
                "text_path": str(out.relative_to(common.ROOT)).replace("\\", "/"),
                "stored_at": common.now_iso()})
            new_doc += 1
            print(f"{code}: STORED {pages}pp {len(text):,}ch fwd={fwd}  "
                  f"{it['headline'][:50]}", flush=True)

        con.commit()
        time.sleep(cfg["http"]["pause_seconds"])

    # The run row is only appended to the ledger once it is COMPLETE, so a
    # killed run leaves no finished_at and the health check sees it as missing
    # rather than as a successful run that stored nothing.
    record(con, "runs", {"run_id": run_id, "started_at": started_at,
                         "finished_at": common.now_iso(), "tickers": len(universe),
                         "tickers_ok": ok_tickers, "new_announcements": new_ann,
                         "new_documents": new_doc})
    con.commit()

    print(f"\nrun {run_id}: {ok_tickers}/{len(universe)} indexes read, "
          f"{new_ann} new announcements, {new_doc} new documents")

    # A run that reached almost nothing is a failure even though every individual
    # step "handled" its own error. Exit non-zero so CI goes red rather than
    # committing a day of near-nothing and reporting success.
    if universe and ok_tickers < 0.6 * len(universe):
        print(f"FAIL: only {ok_tickers} of {len(universe)} indexes reachable",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
