"""Shared plumbing: config, HTTP with retries, and the SQLite store.

Nothing here knows what guidance language is. It exists so that the collector
and the health check read the same schema and fail the same way.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Windows consoles default to cp1252 and die on the first ligature glyph lifted
# out of a PDF. Every tool imports this module, so fix it once here.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "corpus.db"
TEXT_DIR = ROOT / "data" / "text"

# WHAT IS COMMITTED IS THE LEDGER, NOT THE DATABASE.
#
# corpus.db is a derived index and is gitignored. A SQLite file rewrites large
# parts of itself on every write, so committing one daily stores a whole new
# blob each time: at 200 tickers the `fetches` table alone is ~73,000 rows a
# year, and a decade of that is gigabytes of git objects for a few megabytes of
# actual data.
#
# The ledgers below are append-only JSONL, which git stores as small deltas and
# a human can read, diff and grep. rebuild_db() reconstructs the database from
# them, so losing corpus.db costs nothing.
LEDGERS = {
    "announcements": ROOT / "data" / "announcements.jsonl",
    "documents": ROOT / "data" / "documents.jsonl",
    "rejections": ROOT / "data" / "rejections.jsonl",
    "fetches": ROOT / "data" / "fetches.jsonl",
    "runs": ROOT / "data" / "runs.jsonl",
}


def load_config() -> dict:
    with open(ROOT / "config.yml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_universe() -> list[dict]:
    with open(ROOT / "universe.json", encoding="utf-8") as fh:
        return json.load(fh)["tickers"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class FetchError(Exception):
    """Carries the whole response body. Never truncate it: on this estate a
    200-character cap on an error has produced three wrong diagnoses, because
    the field that names the real cause sits past the cut."""


def fetch(url: str, cfg: dict, binary: bool = False, attempts: int | None = None):
    h = cfg["http"]
    attempts = attempts or h["attempts"]
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={"User-Agent": h["user_agent"]})
        try:
            with urllib.request.urlopen(req, timeout=h["timeout_seconds"]) as fh:
                raw = fh.read()
            return raw if binary else raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}: {body}"
            # 4xx other than 429 will not improve on a retry.
            if 400 <= e.code < 500 and e.code != 429:
                break
        except Exception as e:                      # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise FetchError(last or "unknown")


def pdf_is_complete(raw: bytes) -> bool:
    """A truncated PDF from the api host looks like a successful download.

    It has the %PDF- header, a plausible length and no error anywhere, and it
    only fails later in the extractor. The EOF marker is the only cheap proof
    that the whole file arrived.
    """
    return raw[:5] == b"%PDF-" and b"%%EOF" in raw[-3000:]


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
  document_key    TEXT PRIMARY KEY,
  ticker          TEXT NOT NULL,
  announced_at    TEXT NOT NULL,
  headline        TEXT NOT NULL,
  announcement_type TEXT,
  price_sensitive INTEGER,
  file_size       TEXT,
  first_seen      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ann_ticker ON announcements(ticker, announced_at);

CREATE TABLE IF NOT EXISTS documents (
  document_key TEXT PRIMARY KEY REFERENCES announcements(document_key),
  ticker       TEXT NOT NULL,
  bytes        INTEGER NOT NULL,
  pages        INTEGER NOT NULL,
  chars        INTEGER NOT NULL,
  forward_markers INTEGER NOT NULL,
  sha256       TEXT NOT NULL,
  text_path    TEXT NOT NULL,
  stored_at    TEXT NOT NULL
);

-- Why a document seen in the index was NOT stored. Without this a rejected
-- document and a document nobody ever looked at are indistinguishable, and
-- "we have no results for this ticker" has two very different causes.
CREATE TABLE IF NOT EXISTS rejections (
  document_key TEXT PRIMARY KEY,
  ticker       TEXT NOT NULL,
  headline     TEXT NOT NULL,
  reason       TEXT NOT NULL,
  detail       TEXT,
  rejected_at  TEXT NOT NULL
);

-- One row per ticker per run, recording whether the INDEX FETCH itself worked.
-- This is the load-bearing table. A ticker whose index 500s every day looks
-- exactly like a ticker with nothing to announce, and the corpus cannot be
-- repaired later because the window has already moved on.
CREATE TABLE IF NOT EXISTS fetches (
  run_id    TEXT NOT NULL,
  ticker    TEXT NOT NULL,
  ok        INTEGER NOT NULL,
  items     INTEGER,
  error     TEXT,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (run_id, ticker)
);

CREATE TABLE IF NOT EXISTS runs (
  run_id       TEXT PRIMARY KEY,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  tickers      INTEGER NOT NULL,
  tickers_ok   INTEGER,
  new_announcements INTEGER,
  new_documents     INTEGER
);
"""


COLUMNS = {
    "announcements": ["document_key", "ticker", "announced_at", "headline",
                      "announcement_type", "price_sensitive", "file_size",
                      "first_seen"],
    "documents": ["document_key", "ticker", "bytes", "pages", "chars",
                  "forward_markers", "sha256", "text_path", "stored_at"],
    "rejections": ["document_key", "ticker", "headline", "reason", "detail",
                   "rejected_at"],
    "fetches": ["run_id", "ticker", "ok", "items", "error", "fetched_at"],
    "runs": ["run_id", "started_at", "finished_at", "tickers", "tickers_ok",
             "new_announcements", "new_documents"],
}


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def append(table: str, row: dict) -> None:
    """Append one record to the committed ledger.

    Written with flush + fsync because the point of this file is to survive a
    runner that dies mid-run. A record that reached the OS buffer and not the
    disk is a document the five-item window will have eaten by tomorrow.
    """
    path = LEDGERS[table]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_ledger(table: str) -> list[dict]:
    path = LEDGERS[table]
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # A half-written final line is the expected shape of a killed run.
            # Anything earlier is corruption and must not pass silently.
            if n != len(path.read_text(encoding="utf-8").splitlines()):
                raise
    return rows


def rebuild_db() -> sqlite3.Connection:
    """Reconstruct corpus.db from the ledgers. The ledgers are the truth."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = connect()
    for table, cols in COLUMNS.items():
        for row in read_ledger(table):
            values = [row.get(c) for c in cols]
            con.execute(
                f"INSERT OR REPLACE INTO {table} VALUES({','.join('?' * len(cols))})",
                values)
    con.commit()
    return con


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
