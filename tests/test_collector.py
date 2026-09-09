"""Every test here is aimed at a failure that actually happened on 09/09/2026
while the corpus was being assembled by hand. None of them are aimed at Python.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import collect  # noqa: E402
import common  # noqa: E402


@pytest.fixture()
def cfg():
    return common.load_config()


# --------------------------------------------------------------------------
# the truncation bug
# --------------------------------------------------------------------------

def test_truncated_pdf_is_rejected():
    """A 2.6MB deck came back short from asx.api.markitdigital.com with no
    error: %PDF- header, plausible length, no %%EOF. It parsed as a valid
    download and blew up in the extractor much later."""
    assert not common.pdf_is_complete(b"%PDF-1.7\n" + b"x" * 5000)


def test_complete_pdf_is_accepted():
    assert common.pdf_is_complete(b"%PDF-1.7\n" + b"x" * 5000 + b"\n%%EOF\n")


def test_non_pdf_is_rejected():
    assert not common.pdf_is_complete(b'{"error":"not found"}')


def test_document_host_is_the_cdn_gateway(cfg):
    """The api host truncates large documents and the gateway does not. This is
    an assertion rather than a comment because a comment stating an external
    fact rots silently, and this one costs the whole corpus."""
    assert "cdn-api.markitdigital.com" in cfg["doc_host"]
    assert "asx.api.markitdigital.com" not in cfg["doc_host"]


# --------------------------------------------------------------------------
# headline triage: every case below is a real headline
# --------------------------------------------------------------------------

@pytest.mark.parametrize("headline", [
    "FY26 Full Year Results Presentation",          # LOV, ADH
    "FY26 Results ASX Announcement",                # SLC
    "AEF FY26 Results Announcement",                # AEF
    "Appendix 4E and Full Year Accounts",
    "FY26 Investor Presentation",                   # AD8
])
def test_real_results_headlines_are_kept(headline, cfg):
    keep, _ = collect.wanted(headline, cfg)
    assert keep, headline


@pytest.mark.parametrize("headline,why", [
    # Both announced as results; both are one-page PDFs linking to a video.
    ("FY26 Full Year Results Briefing - Webcast Recording", "MAD"),
    ("PolyNovo FY26 Results Presentation Webinar Recording", "PNV"),
    # Admitted by a filter matching "fy2026". A year token is not a doc type.
    ("Corporate Governance Statement FY2026", "ARB"),
    # 153 pages, 420,635 characters, 188 forward markers almost all of which are
    # in the notes to the financial statements. Cleared every other filter.
    ("Full Year Statutory Accounts", "MND"),
    ("Annual Financial Report 2026", "financial report"),
    ("Notice of Annual General Meeting", "routine"),
    ("Update - Dividend/Distribution - BHP", "routine"),
    ("Becoming a substantial holder", "routine"),
])
def test_known_traps_are_rejected(headline, why, cfg):
    keep, reason = collect.wanted(headline, cfg)
    assert not keep, f"{why}: {headline}"
    assert reason


def test_size_kb_parses_the_index_format():
    assert collect.size_kb("2210KB") == 2210
    assert collect.size_kb("") == 0
    assert collect.size_kb(None) == 0


# --------------------------------------------------------------------------
# substance floor
# --------------------------------------------------------------------------

def test_forward_markers_ignores_a_deck_with_none(cfg):
    """The webcast cover note, in full. 1,722 characters, zero markers."""
    assert collect.forward_markers(
        "Mader Group Limited advises that the FY26 results briefing "
        "webcast recording is now available on the company website.", cfg) == 0


def test_forward_markers_counts_real_guidance(cfg):
    assert collect.forward_markers(
        "Genus is forecasting to deliver circa $200m - $205m EBITDA FY2027. "
        "The integration remains on track and we are confident in the outlook.",
        cfg) >= 3


# --------------------------------------------------------------------------
# the first CI run: three bugs, none of which failed anything
# --------------------------------------------------------------------------

def test_requirements_pin_the_pypdf_crypto_extra():
    """ASX PDFs are AES-encrypted with an empty password. pypdf needs the
    optional `cryptography` extra to open them, and it happens to be installed
    on the laptop as a transitive dependency of something else. The plain
    requirement passed locally and rejected 32 of 32 documents on the first
    clean CI runner with "cryptography>=3.1 is required for AES algorithm"."""
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "pypdf[crypto]" in req, "the extra is not optional here"
    import cryptography          # noqa: F401  - must be importable, not just listed


def test_a_parse_failure_is_not_recorded_as_settled():
    """It is an environment fault as often as a document fault, and there is no
    backfill: a document written off today cannot be fetched again once it
    leaves the five-item window."""
    src = (ROOT / "tools" / "collect.py").read_text(encoding="utf-8")
    body = src.split("PdfReader(path)", 1)[1].split("s = cfg[", 1)[0]
    assert "parse-failed" not in body, \
        "parse failures must stay retryable, not become a rejection row"
    assert "parse_failures.append" in body


def test_the_collector_rebuilds_the_database_from_the_ledger():
    """corpus.db is gitignored, so a CI checkout has none. Opening an empty one
    made every announcement look new: the first CI run appended all 227 a second
    time and reported success."""
    src = (ROOT / "tools" / "collect.py").read_text(encoding="utf-8")
    assert "common.rebuild_db()" in src
    assert "con = common.connect()" not in src


def test_ledgers_hold_no_duplicate_keys():
    """Guards the repaired ledger against the bug coming back."""
    import json
    for name, key in (("announcements", "document_key"), ("documents", "document_key"),
                      ("rejections", "document_key"), ("runs", "run_id")):
        path = ROOT / "data" / f"{name}.jsonl"
        if not path.exists():
            continue
        keys = [json.loads(l)[key]
                for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(keys) == len(set(keys)), f"{name} has duplicate {key} rows"


# --------------------------------------------------------------------------
# the gold set
# --------------------------------------------------------------------------

def test_gold_labels_are_complete_and_valid():
    """build_labels.py asserts every document is labelled and every label matched
    a document. This asserts the vocabulary, so a typo in a class name cannot
    quietly create a sixth category nobody scores against."""
    import json
    g = json.loads((ROOT / "gold" / "labels.json").read_text(encoding="utf-8"))
    docs = g["documents"]
    assert len(docs) == g["n"] >= 30, "the gold set is meant to be 30+"
    for d in docs:
        assert d["next_period_guide"] in {"full", "relational", "segment", "none", "deferred"}
        assert d["stance"] in {"positive", "negative", "mixed", "neutral"}
        assert d["horizon"] in {"next_year", "split", "medium_term", "current_trading_only"}
        assert d["period"] in {"FY26", "1H26"}
        assert d["quote"].strip(), f"{d['ticker']} has no load-bearing quote"


def test_the_readme_states_the_baseline_it_actually_has():
    """Recompute the documented figure rather than matching a phrase.

    The first version of this test asserted the README contained the words
    "unusable as a benchmark", and it broke the moment the imbalance was fixed
    and the wording changed - a test about the prose, not the fact. This one
    fails when the set is rebalanced and the stated number is left behind,
    which is the failure worth catching."""
    import json
    import re
    from collections import Counter
    docs = []
    for f in ("labels.json", "labels_negative.json"):
        docs += json.loads((ROOT / "gold" / f).read_text(encoding="utf-8"))["documents"]
    counts = Counter(d["stance"] for d in docs)
    baseline = round(100 * counts.most_common(1)[0][1] / len(docs))
    readme = (ROOT / "gold" / "README.md").read_text(encoding="utf-8")
    stated = [int(x) for x in re.findall(r"baseline is\s+\*\*(\d+)%", readme)]
    assert stated, "the README no longer states a majority-class baseline"
    assert baseline in stated, (
        f"README says {stated}%, the labels say {baseline}%")


def test_gold_set_stance_is_now_measurable():
    """The results-season half was 25 positive to 1 negative, so answering
    "positive" every time scored 76% and stance could not be measured. Ten
    negatives found via the market-wide sweep bring the majority-class baseline
    down. This fails if a future edit unbalances it again."""
    import json
    from collections import Counter
    docs = []
    for f in ("labels.json", "labels_negative.json"):
        docs += json.loads((ROOT / "gold" / f).read_text(encoding="utf-8"))["documents"]
    assert len(docs) >= 40
    counts = Counter(d["stance"] for d in docs)
    baseline = counts.most_common(1)[0][1] / len(docs)
    assert baseline < 0.65, f"majority-class baseline back up to {baseline:.0%}"
    assert counts["negative"] >= 5, "too few negatives to count sign errors"


def test_the_two_halves_of_the_gold_set_stay_separable():
    """They were sampled differently - one from results season, one from a
    deliberate hunt for downgrades - so a model scored on the combined set is
    being scored on a balanced sample, not a natural one. Anyone reporting a
    number off it has to be able to say which half."""
    import json
    neg = json.loads((ROOT / "gold" / "labels_negative.json").read_text(encoding="utf-8"))
    assert all(d["source"] == "market_sweep" for d in neg["documents"])
