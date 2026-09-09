"""The extraction layer, tested where it can be tested without a model:
passage selection, response validation, and the error handling that decides
whether a nightly batch survives a bad night.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import common  # noqa: E402
import extract  # noqa: E402
import passages  # noqa: E402


# --------------------------------------------------------------------------
# passage selection
# --------------------------------------------------------------------------

LYL_SLIDE = (
    "Contract mix - predominantly EPCM, however the order book reflects a blend "
    "of contract styles in FY27. FY27 OUTLOOK 18 FY27 GUIDANCE Growing volume of "
    "work underpinning future earnings 18 $540m & $580m Between Revenue $54m & "
    "$58m Between Net Profit After Tax (NPAT) The Company will continue to update "
    "shareholders as the financial year progresses"
)


def test_a_slide_layout_survives_selection():
    """Lycopodium's FY27 guidance is the most quantified statement in the gold
    set and contains no sentence. A sentence splitter returns nothing and scores
    LYL as giving no guidance, which is how the first pass got it wrong."""
    out = passages.select(LYL_SLIDE)
    for token in ("540m", "580m", "NPAT", "FY27 GUIDANCE"):
        assert token in out, f"{token} lost in selection"


def test_sentence_splitting_alone_would_have_missed_it():
    """The counter-check. Without this, the test above could pass for the wrong
    reason and nobody would know windows were doing the work."""
    sents = [s for s in passages.sentences(LYL_SLIDE) if "540m" in s]
    assert sents, "fixture is wrong"
    # It survives only because it is glued to a neighbouring sentence, not
    # because a splitter found it - the whole slide is one 'sentence'.
    assert len(sents[0]) > 200


def test_the_safe_harbour_block_is_removed():
    """It is written out of the exact vocabulary the anchor regex looks for and
    appears in every deck. Five of Step One's seven candidate passages were
    disclaimer text before this."""
    text = ("This presentation contains forward-looking statements which may be "
            "identified by words such as expects, anticipates and outlook. "
            "Actual results may differ materially. "
            "FY27 revenue is expected to be between $540m and $580m.")
    out = passages.select(text)
    assert "540m" in out
    assert "may be identified by words" not in out


def test_selection_is_capped():
    out = passages.select("The FY27 outlook is strong. " * 4000)
    assert len(out) <= passages.MAX_CHARS + 400


def test_the_personal_use_watermark_is_stripped():
    """Stamped down the side of every ASX PDF, and it lands mid-sentence."""
    assert "personal use" not in passages.select(
        "FY27 guidance For personal use only is $540m to $580m revenue.").lower()


# --------------------------------------------------------------------------
# response validation
# --------------------------------------------------------------------------

GOOD = {
    "next_period_guide": "full", "stance": "positive", "horizon": "next_year",
    "guided_period": "FY27", "current_trading": None,
    "quote": "Forecast EBITDA for FY2027 to be in the range of $200-205 million.",
    "confidence": "high",
}


def test_a_valid_response_parses():
    assert extract.parse(json.dumps(GOOD))["next_period_guide"] == "full"


def test_a_fenced_response_parses():
    assert extract.parse("```json\n" + json.dumps(GOOD) + "\n```")["stance"] == "positive"


@pytest.mark.parametrize("field,bad", [
    ("next_period_guide", "partial"),
    ("stance", "very positive"),
    ("horizon", "FY27"),
    ("confidence", "medium"),
])
def test_an_invented_enum_value_is_refused(field, bad):
    """A model will invent a label. One that reaches the ledger becomes a sixth
    class nobody scores against, silently."""
    obj = dict(GOOD, **{field: bad})
    with pytest.raises(ValueError, match=field):
        extract.parse(json.dumps(obj))


def test_a_missing_quote_is_refused():
    with pytest.raises(ValueError, match="quote"):
        extract.parse(json.dumps(dict(GOOD, quote="")))


def test_the_valid_sets_match_the_gold_vocabulary():
    """If the prompt's enum and the gold labels ever drift apart, every score is
    measured against classes that cannot be produced."""
    docs = []
    for f in ("labels.json", "labels_negative.json"):
        docs += json.loads((ROOT / "gold" / f).read_text(encoding="utf-8"))["documents"]
    for field in ("next_period_guide", "stance", "horizon"):
        used = {d[field] for d in docs}
        assert used <= extract.VALID[field], (
            f"{field}: gold uses {used - extract.VALID[field]} which the model "
            f"is never asked to produce")


# --------------------------------------------------------------------------
# the error handling that decides whether a nightly batch survives
# --------------------------------------------------------------------------

def test_api_key_invalid_is_treated_as_transient():
    """MEASURED 09/09/2026: this API returns 400 API_KEY_INVALID for a key that
    is valid, when the model behind it is overloaded. The same key answered a
    probe seconds before and seconds after. Believing it stopped a whole batch
    with a diagnosis pointing at the wrong thing.

    A genuinely dead key still fails every retry, extracts nothing and exits
    non-zero, so nothing is lost by not believing the message the first time."""
    src = (ROOT / "tools" / "extract.py").read_text(encoding="utf-8")
    block = src.split("API_KEY_INVALID", 1)[1].split("raise err", 1)[0]
    assert "transient = True" in block


def test_a_quota_wall_is_not_retried():
    """Gemini's daily-quota 429 carries a "retry in 59s" hint that is a
    bucket-refill estimate and a lie for that quota. Following it spends three
    minutes to fail anyway."""
    src = (ROOT / "tools" / "extract.py").read_text(encoding="utf-8")
    line = [l for l in src.splitlines() if "err.transient = e.code in" in l][0]
    assert "429" not in line, "429 must not be retried"
    assert "503" in line


def test_every_feature_row_records_which_model_answered():
    """A fallback is fine. An unrecorded fallback put two calibrations in one
    ranked column on Ghostwriters and was invisible for days."""
    for col in ("provider", "model", "prompt_version"):
        assert col in common.COLUMNS["features"]
    rows = common.read_ledger("features")
    for r in rows:
        assert r.get("model") and r.get("provider"), r


def test_features_are_keyed_per_model_not_per_document():
    """Two models must be able to answer the same document without one
    overwriting the other, or they cannot be compared."""
    assert "PRIMARY KEY (document_key, model, prompt_version)" in common.SCHEMA
