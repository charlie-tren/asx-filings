"""The ledger is the committed artifact and the database is derived from it, so
the round trip has to be exact. If rebuild_db() loses a column, the loss is
silent: the database still opens, the health check still runs, and the corpus
looks fine until someone asks it a question about the missing field.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import common  # noqa: E402


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "DB_PATH", tmp_path / "corpus.db")
    monkeypatch.setattr(common, "LEDGERS",
                        {t: tmp_path / f"{t}.jsonl" for t in common.LEDGERS})
    return tmp_path


ROWS = {
    "announcements": {
        "document_key": "2924-03121569-2A1689747", "ticker": "AD8",
        "announced_at": "2026-08-16T09:17:50.000Z",
        "headline": "FY26 Investor Presentation",
        "announcement_type": "RESULTS", "price_sensitive": 1,
        "file_size": "2210KB", "first_seen": "2026-09-09T07:30:00+00:00"},
    "documents": {
        "document_key": "2924-03121569-2A1689747", "ticker": "AD8",
        "bytes": 2660040, "pages": 27, "chars": 33046, "forward_markers": 24,
        "sha256": "deadbeef", "text_path": "data/text/AD8/x.txt",
        "stored_at": "2026-09-09T07:30:00+00:00"},
    "rejections": {
        "document_key": "k2", "ticker": "MAD",
        "headline": "FY26 Full Year Results Briefing - Webcast Recording",
        "reason": "thin", "detail": "1pp 1722ch fwd=0",
        "rejected_at": "2026-09-09T07:30:00+00:00"},
    "fetches": {"run_id": "r1", "ticker": "AD8", "ok": 1, "items": 5,
                "error": None, "fetched_at": "2026-09-09T07:30:00+00:00"},
    "runs": {"run_id": "r1", "started_at": "2026-09-09T07:00:00+00:00",
             "finished_at": "2026-09-09T07:30:00+00:00", "tickers": 50,
             "tickers_ok": 47, "new_announcements": 12, "new_documents": 3},
}


def test_every_table_round_trips_every_column(store):
    for table, row in ROWS.items():
        common.append(table, row)
    con = common.rebuild_db()
    for table, row in ROWS.items():
        got = dict(con.execute(f"SELECT * FROM {table}").fetchone())
        assert got == row, f"{table} lost or mangled a column"


def test_columns_match_the_schema_exactly():
    """COLUMNS drives the INSERT, so a schema change that does not update it
    writes values into the wrong fields rather than failing."""
    con = common.connect() if False else None
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.executescript(common.SCHEMA)
    for table, cols in common.COLUMNS.items():
        actual = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
        assert actual == cols, f"{table}: schema {actual} != COLUMNS {cols}"


def test_a_half_written_final_line_is_tolerated(store):
    """The expected shape of a runner killed mid-append."""
    common.append("fetches", ROWS["fetches"])
    with open(common.LEDGERS["fetches"], "a", encoding="utf-8") as fh:
        fh.write('{"run_id": "r2", "ticker": "AD')
    assert len(common.read_ledger("fetches")) == 1


def test_corruption_before_the_last_line_is_not_tolerated(store):
    """A bad line in the middle means the file is damaged, not truncated, and
    passing silently would quietly shrink the corpus."""
    path = common.LEDGERS["fetches"]
    path.write_text('{"run_id": "r1"}\nNOT JSON\n{"run_id": "r3"}\n',
                    encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        common.read_ledger("fetches")


def test_rebuild_is_idempotent(store):
    for table, row in ROWS.items():
        common.append(table, row)
        common.append(table, row)          # the same record seen twice
    con = common.rebuild_db()
    for table in ROWS:
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert n == 1, f"{table} duplicated a record on rebuild"
