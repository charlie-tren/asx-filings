"""Health check. Answers the two questions that matter about this collector,
which are not the same question:

  1. Is it running?
  2. Is what it pulls being KEPT?

Both, because a job that runs every night and stores nothing looks identical
from the outside to a job that is working. And because there is no backfill
here, a silent failure is not a gap that can be repaired later: the five-item
window moves on and the document is gone for good.

Exits non-zero on any FAIL so the workflow goes red. A log line is not loud.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common

# A run older than this means the producer is dead. The job is daily, so two
# days allows for one dropped GitHub schedule without crying wolf. GitHub's
# scheduler on this account has been measured 3 to 7 hours late with no open
# incident, so anything tighter than a day is noise.
STALE_RUN_HOURS = 40

# Consecutive failed index reads for one ticker before it counts as broken
# rather than unlucky.
TICKER_FAIL_STREAK = 3

# A delisted or taken-over code is a stale universe, not a broken collector, and
# the two must not be reported the same way. IFM, JLG and RUL all answered this
# on 09/09/2026. Conflating them means either the check cries wolf every night
# until someone edits universe.json, or the threshold gets raised and a genuine
# outage stops being reported.
DELISTED_MARKER = "symbol not found"

# ASX full-year reporting is August, halves are February. A universe that
# produces no stored documents during those months is not a quiet market, it is
# a broken collector.
REPORTING_MONTHS = {2, 8}

# Measured sweeps reach 99-100 of the server's 100-page cap. Anything well under
# that is the sweep failing, not the market being quiet.
MIN_PAGES_OK = 80


def hours_since(iso: str) -> float:
    then = datetime.fromisoformat(iso)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def main() -> int:
    con = common.connect()
    fails: list[str] = []
    warns: list[str] = []

    # ---- 1. is it running at all -----------------------------------------
    last = con.execute(
        "SELECT * FROM runs WHERE finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 1").fetchone()
    if last is None:
        fails.append("no completed run has ever been recorded")
        print("\n".join("FAIL " + f for f in fails))
        return 1

    age = hours_since(last["finished_at"])
    line = f"last run {last['run_id']} finished {age:.1f}h ago"
    if age > STALE_RUN_HOURS:
        fails.append(f"{line} (stale, threshold {STALE_RUN_HOURS}h)")
    else:
        print(f"OK   {line}")

    # ---- 2. did that run actually reach the market ------------------------
    reached = last["tickers_ok"] or 0
    total = last["tickers"] or 0
    if total and reached < 0.6 * total:
        fails.append(f"last run reached only {reached}/{total} indexes")
    else:
        print(f"OK   last run read {reached}/{total} indexes")

    # ---- 3. did the SWEEP finish -----------------------------------------
    # Ingestion is the market-wide feed, and the fetches table now holds one
    # "page:N" row per page alongside the per-ticker liveness rows. A sweep that
    # stopped at page 12 looks exactly like a quiet market from the outside.
    last_run = last["run_id"]
    pages = con.execute(
        "SELECT COUNT(*) n, SUM(ok) ok FROM fetches "
        "WHERE run_id=? AND ticker LIKE 'page:%'", (last_run,)).fetchone()
    if pages["n"]:
        got = pages["ok"] or 0
        if got < MIN_PAGES_OK:
            fails.append(f"sweep reached only {got} pages (minimum {MIN_PAGES_OK})")
        else:
            print(f"OK   sweep read {got}/{pages['n']} pages")
    else:
        fails.append("last run recorded no sweep pages at all")

    # ---- 4. per-ticker liveness: broken, or genuinely quiet ---------------
    # The sweep cannot answer this. Absence from a market-wide feed is the normal
    # state for a company with nothing to announce, so the only way to tell a
    # DELISTED code from a quiet one is to ask its index directly. That is what
    # the liveness probe is for, and it is how IFM, JLG and RUL were found.
    broken, delisted = [], []
    for row in con.execute(
            "SELECT DISTINCT ticker FROM fetches WHERE ticker NOT LIKE 'page:%'"):
        t = row["ticker"]
        recent = con.execute(
            "SELECT ok, error FROM fetches WHERE ticker=? "
            "ORDER BY fetched_at DESC LIMIT ?", (t, TICKER_FAIL_STREAK)).fetchall()
        if len(recent) < TICKER_FAIL_STREAK or any(r["ok"] for r in recent):
            continue
        if all(DELISTED_MARKER in (r["error"] or "").lower() for r in recent):
            delisted.append(t)          # universe maintenance, not an outage
        else:
            broken.append(t)
    if broken:
        fails.append(f"{len(broken)} tickers failing every read: {', '.join(sorted(broken))}")
    else:
        print("OK   no ticker is failing for an unexplained reason")
    if delisted:
        warns.append(f"{len(delisted)} codes no longer exist, drop them from "
                     f"universe.json: {', '.join(sorted(delisted))}")

    # ---- 5. running is not the same as kept -------------------------------
    seen = con.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"]
    kept = con.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    print(f"OK   corpus: {kept} documents kept, {seen} announcements seen")

    if datetime.now(timezone.utc).month in REPORTING_MONTHS:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        recent_docs = con.execute(
            "SELECT COUNT(*) c FROM documents WHERE stored_at > ?", (cutoff,)
        ).fetchone()["c"]
        if recent_docs == 0:
            fails.append("reporting season and nothing stored in 14 days")
        else:
            print(f"OK   reporting season: {recent_docs} documents stored in 14 days")

    # ---- 6. rejections worth a human look ---------------------------------
    # "thin" is expected and fine. "parse-failed" is a document we were entitled
    # to and lost, which is the one rejection reason that costs corpus.
    lost = con.execute(
        "SELECT ticker, headline FROM rejections WHERE reason='parse-failed'").fetchall()
    if lost:
        warns.append(f"{len(lost)} documents failed to parse and are unrecoverable: "
                     + ", ".join(f"{r['ticker']} {r['headline'][:30]}" for r in lost[:5]))

    truncation_prone = con.execute(
        "SELECT COUNT(*) c FROM rejections WHERE reason='too-large'").fetchone()["c"]
    if truncation_prone:
        warns.append(f"{truncation_prone} documents skipped as too large")

    for w in warns:
        print(f"WARN {w}")
    for f in fails:
        print(f"FAIL {f}", file=sys.stderr)

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
