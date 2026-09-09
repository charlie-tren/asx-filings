"""Hand labels for the negative half of the gold set.

These did NOT come from the per-ticker collector. They were found by sweeping
the market-wide announcement feed - 9,899 announcements over 20 days, every
listed company - and reading the price-sensitive candidates by hand. That is the
only way to find a downgrade without knowing in advance who issued it.

The set needed them: the results-season half is 25 positive to 1 negative, so
answering "positive" every time scored 76% and stance could not be measured at
all.

Same schema as build_labels.py, plus:
  source   "market_sweep" - to keep the two halves separable, because they were
           sampled differently and a model scored on the combined set is being
           scored on a deliberately balanced sample, not a natural one.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "gold" / "negatives_raw"

N = [
 dict(ticker="TER", announced="2026-08-31", headline="Market Update",
      period="FY27", next_period_guide="full", stance="negative",
      horizon="next_year", current_trading=None,
      quote="Blair Athol Mine ... has continued to produce below plan during the early part of FY2027 ... As a result, TerraCom maintains its FY2027 production guidance of between 2.0 and 2.2 million tonnes at this time.",
      notes="THE BEST CASE IN THE SET. Bad news, guidance HELD, and 'at this time' plus 'will provide further guidance should its expectations materially change'. A model that keys on 'maintains its guidance' scores this neutral or positive. It is a pre-downgrade."),
 dict(ticker="SHV", announced="2026-09-07", headline="SHV Business Update",
      period="FY26", next_period_guide="full", stance="mixed",
      horizon="next_year", current_trading=None,
      quote="External grower volumes 13,800MT - 14,200MT, an 88-94% increase on FY25 (previous guidance 15,400MT) ... The Company now expects a near record crop of 28,800MT - 29,600MT (+16-19% on pcp) which is an exceptional result",
      notes="An explicit NUMERIC GUIDANCE CUT (15,400 down to 13,800-14,200) printed beside 'near record crop' and 'exceptional result'. One line down, another up, in one sentence. Any single score erases it."),
 dict(ticker="SSG", announced="2026-08-26",
      headline="SSG - FY26 Results Announcement & Trading Update",
      period="FY26", next_period_guide="none", stance="negative",
      horizon="current_trading_only",
      current_trading={"window": "1 Jul to 22 Aug", "metric": "total sales", "value": "-3.2%"},
      quote="Shaver Shop has experienced a softer than anticipated start to FY27 with total sales down -3.2% YTD. Total sales over the first two weeks of FY27 were down -9.5% versus pcp",
      notes="The negative mirror of Lovisa's +16.4%. Same feature, opposite sign, and the release still opens on 'record sales and gross profit results' for the year just closed."),
 dict(ticker="PPT", announced="2026-08-20", headline="Non-cash impairment",
      period="FY26", next_period_guide="none", stance="negative",
      horizon="next_year", current_trading=None,
      quote="Perpetual expects to recognise a non-cash impairment charge of A$63.5 million against the carrying value of goodwill for TSW ... The redemption of circa US$4.6 bn is expected to occur in Q2 of FY27.",
      notes="The impairment is the headline and the REDEMPTION is the signal: US$4.6bn leaving in FY27. Wrapped in 'non-cash ... does not affect liquidity, compliance with its banking covenants or impact UPAT'. Mitigating framing around a real forward hit."),
 dict(ticker="EVO", announced="2026-08-27", headline="EVO Market Update 28 August 26",
      period="1H26", next_period_guide="none", stance="negative",
      horizon="next_year", current_trading=None,
      quote="Profit after income tax attributable to shareholders of the company (12,743) [vs] 4,036",
      notes="A swing from +$4.0m to -$12.7m, reported third, under a renewed bank facility and a dividend declaration. The document never uses the word loss. Tests whether a model reads the table or only the prose."),
 dict(ticker="APX", announced="2026-08-26",
      headline="H1FY26 Results and FY26 Outlook & Guidance",
      period="1H26", next_period_guide="relational", stance="mixed",
      horizon="next_year", current_trading=None,
      quote="Appen Global first half revenue was $43.7 million (-27% vs pcp) with an underlying EBITDA loss of $4.5 million. The decrease in revenue reflects the continued turnaround with lower volumes from traditional work",
      notes="Segment down 27% with an EBITDA loss, framed as a turnaround in progress, alongside a $12m incremental cost-reduction target. Decline plus self-help is the commonest shape of a real downgrade."),
 dict(ticker="CMA", announced="2026-08-30", headline="FY26 Results and Trading Update",
      period="FY26", next_period_guide="none", stance="negative",
      horizon="next_year", current_trading=None,
      quote="Market conditions changed in the final quarter. Fuel prices rose sharply from March 2026, dealer demand for wholesale vehicles fell, used car prices declined and cars took longer to sell.",
      notes="Four independent negatives in one sentence, all external. Sits beside 'Q4 was a record quarter for both retail and wholesale deliveries' with gross profit per unit lower. Volume up, margin down."),
 dict(ticker="DDR", announced="2026-08-27",
      headline="H1 FY26 Results & FY26 Guidance Update",
      period="1H26", next_period_guide="relational", stance="mixed",
      horizon="next_year", current_trading=None,
      quote="reported gross revenue of $269.4 million, down 7.6% versus pcp ... Profit before tax decreased to $4.0 million, reflecting softer market conditions in New Zealand",
      notes="A segment decline inside a group result where profit before tax rose 50.1%. Tests whether an extractor attaches the number to the right entity: group up, New Zealand down."),
 dict(ticker="MTS", announced="2026-09-08",
      headline="2026 Annual General Meeting and Trading Update",
      period="FY27", next_period_guide="none", stance="mixed",
      horizon="next_year", current_trading=None,
      quote="a year of mixed trading conditions, ongoing cost-of-living pressures and sector-specific challenges ... the loss of around $1.8 billion of tobacco sales since FY21, largely to illicit trade, as well as lower earnings from the market downturn in Hardware and Tools",
      notes="AGM trading updates are the classic downgrade vehicle. This one names a $1.8bn structural revenue loss and then reports offsetting at least $65m of earnings. The mitigation is real and so is the hole."),
 dict(ticker="ACW", announced="2026-08-27", headline="ACW FY2026 results and outlook",
      period="FY26", next_period_guide="none", stance="negative",
      horizon="next_year", current_trading=None,
      quote="The Net loss after tax for the twelve months ended 30 June 2026 was $15,379,848 (FY2025: loss of $14,732,263).",
      notes="A widening loss at a pre-revenue biotech, where a loss is the expected state and not a downgrade. Included deliberately: a model that scores every loss as negative news will be wrong about the whole sector."),
]


def main() -> None:
    keys = {}
    for f in RAW.glob("*.txt"):
        keys.setdefault(f.stem.split("_")[0], f)
    out = []
    for lab in N:
        f = keys.get(lab["ticker"])
        assert f is not None, f"no saved text for {lab['ticker']}"
        out.append({"document_key": f.stem.split("_", 1)[1],
                    "text_path": str(f.relative_to(ROOT)).replace("\\", "/"),
                    "source": "market_sweep", **lab})
    (ROOT / "gold/labels_negative.json").write_text(
        json.dumps({"labelled": "2026-09-09", "by": "hand",
                    "found_via": "market-wide announcement sweep, 9899 announcements "
                                 "over 2026-08-20..2026-09-09",
                    "n": len(out), "documents": out}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"{len(out)} negative/mixed documents labelled")


if __name__ == "__main__":
    main()
