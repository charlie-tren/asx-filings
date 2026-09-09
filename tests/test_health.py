"""The health check is the only thing standing between a dead collector and a
permanently incomplete corpus, so it is tested by being FED KNOWN-BAD FIXTURES.

A green result you have never seen come out red is not evidence. Each test
below builds a database in a specific broken state and asserts the check
notices, and one asserts it passes on a healthy one so the failures mean
something.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import common  # noqa: E402
import health  # noqa: E402


def iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(
        timespec="seconds")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh corpus.db, with both modules pointed at it."""
    path = tmp_path / "corpus.db"
    monkeypatch.setattr(common, "DB_PATH", path)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(common.SCHEMA)
    yield con
    con.close()


def healthy(con, run_age_hours: float = 2.0, tickers: int = 50, ok: int = 50):
    con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                ("r1", iso(run_age_hours + 0.1), iso(run_age_hours),
                 tickers, ok, 12, 3))
    for i in range(ok):
        con.execute("INSERT INTO fetches VALUES(?,?,?,?,?,?)",
                    ("r1", f"T{i:02d}", 1, 5, None, iso(run_age_hours)))
    con.commit()


def test_passes_on_a_healthy_corpus(db, capsys):
    healthy(db)
    assert health.main() == 0


def test_fails_when_nothing_has_ever_run(db):
    assert health.main() == 1


def test_fails_when_the_last_run_is_stale(db, capsys):
    """The producer is dead. Clock is set well past the boundary rather than
    just over it: a threshold test that only fails inside a narrow window reads
    as flakiness later."""
    healthy(db, run_age_hours=health.STALE_RUN_HOURS + 24)
    assert health.main() == 1
    assert "stale" in capsys.readouterr().err


def test_fails_when_the_run_reached_almost_nothing(db, capsys):
    """Every individual ticker error was handled, so the job exited cleanly and
    stored a run row. That is exactly the shape this has to catch."""
    healthy(db, tickers=50, ok=4)
    assert health.main() == 1
    assert "reached only" in capsys.readouterr().err


def test_fails_when_a_ticker_breaks_consecutively(db, capsys):
    """A ticker whose index 400s every night looks like a quiet ticker unless
    the fetch outcome is recorded per run. It is."""
    healthy(db)
    for n in range(health.TICKER_FAIL_STREAK):
        db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
                   (f"r{n}", "BROKE", 0, None, "HTTP 400", iso(n * 24 + 1)))
    db.commit()
    assert health.main() == 1
    assert "BROKE" in capsys.readouterr().err


def test_a_delisted_code_warns_but_does_not_fail(db, capsys):
    """IFM, JLG and RUL all answered "Symbol not found" on 09/09/2026. That is
    universe maintenance. Failing on it every night until someone edits a JSON
    file trains everyone to ignore the check."""
    healthy(db)
    for n in range(health.TICKER_FAIL_STREAK):
        db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
                   (f"r{n}", "RUL", 0, None,
                    'HTTP 400: {"error":{"message":"Bad Request: Symbol not found"}}',
                    iso(n * 24 + 1)))
    db.commit()
    assert health.main() == 0
    assert "RUL" in capsys.readouterr().out


def test_a_real_outage_still_fails_alongside_a_delisting(db, capsys):
    """The delisting carve-out must not become a hole a genuine outage fits
    through."""
    healthy(db)
    for n in range(health.TICKER_FAIL_STREAK):
        db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
                   (f"r{n}", "RUL", 0, None, "Symbol not found", iso(n * 24 + 1)))
        db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
                   (f"r{n}", "LOV", 0, None, "HTTP 503: upstream", iso(n * 24 + 1)))
    db.commit()
    assert health.main() == 1
    err = capsys.readouterr().err
    assert "LOV" in err and "RUL" not in err


def test_a_ticker_that_recovers_is_not_reported(db):
    healthy(db)
    db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
               ("r0", "FLAKY", 0, None, "timeout", iso(50)))
    db.execute("INSERT OR REPLACE INTO fetches VALUES(?,?,?,?,?,?)",
               ("r1", "FLAKY", 1, 5, None, iso(2)))
    db.commit()
    assert health.main() == 0


def test_running_is_not_the_same_as_kept(db, capsys):
    """Reporting season, the job runs every night, every index reads fine, and
    nothing is being stored. Every other check on this page is green."""
    healthy(db)
    monkey_month = datetime.now(timezone.utc).month
    if monkey_month not in health.REPORTING_MONTHS:
        pytest.skip("season check only binds in Feb/Aug; covered by the unit below")
    assert health.main() == 1
    assert "nothing stored" in capsys.readouterr().err


def test_season_check_binds_in_reporting_months(db, monkeypatch, capsys):
    """The above only fires in February and August, which would leave this
    untested for ten months of the year. Freeze the month instead."""
    healthy(db)
    monkeypatch.setattr(health, "REPORTING_MONTHS",
                        {datetime.now(timezone.utc).month})
    assert health.main() == 1
    assert "nothing stored" in capsys.readouterr().err


def test_season_check_passes_when_documents_are_arriving(db, monkeypatch):
    healthy(db)
    monkeypatch.setattr(health, "REPORTING_MONTHS",
                        {datetime.now(timezone.utc).month})
    db.execute("INSERT INTO announcements VALUES(?,?,?,?,?,?,?,?)",
               ("k1", "GNP", "2026-08-24", "FY2026 Results Presentation",
                "RESULTS", 1, "3178KB", iso(2)))
    db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)",
               ("k1", "GNP", 3468435, 22, 27401, 19, "abc",
                "data/text/GNP/k1.txt", iso(2)))
    db.commit()
    assert health.main() == 0
