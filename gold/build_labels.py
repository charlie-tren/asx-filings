"""Hand-assigned labels for the gold set. Written by reading the documents, not
by running anything over them. This is what a model gets scored against.

Fields, and why each exists:

  period              FY26 full year, or 1H26 half. A half-year report's forward
                      period is the SAME fiscal year, so "which year is this
                      guidance about" cannot be inferred from the document date.
  next_period_guide   full | relational | segment | none | deferred.
                      Only "full" is a number for the next period's earnings.
                      "relational" is a constraint without a number ("expenses
                      below revenue", "modest growth"). "deferred" is an
                      explicit promise to guide later.
  stance              positive | negative | mixed | neutral.
  horizon             next_year | split | medium_term | current_trading_only.
                      SPLIT matters: Adairs says H1 will be difficult and H2
                      improves. Average those into one score and you get
                      neutral, which is the one reading that is wrong.
  current_trading     A disclosed figure for a period already elapsed. A fact,
                      not a forecast, and a different feature from guidance.
  quote               The load-bearing line, verbatim.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CANDS = json.loads((ROOT / "gold/candidates.json").read_text(encoding="utf-8"))

# Keyed by (ticker, a distinguishing word from the headline).
L = {
 ("AD8", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Improved FY27 cash flow trajectory anticipated, driven by revenue growth and reduced cost base",
  notes="The PRESENTATION has no guide. The market release, same company same day, carries a relational one. One document per company loses it."),
 ("AD8", "Market Release"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="In FY27, US dollar gross profit growth is expected to be in line with or slightly ahead of the rate achieved in FY26, with gross margins maintained and operating costs held flat",
  notes="Relational: a rate compared to last year, no absolute number."),
 ("ADH", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="negative",
  horizon="split", current_trading=None,
  quote="H1 FY27 will remain difficult as the weaker fourth-quarter order book carries into the new financial year",
  notes="Clearest negative in the corpus, and it is ONLY in the presentation. Split horizon: H2 FY27 improves and builds into FY28."),
 ("ADH", "Release"): dict(
  period="FY26", next_period_guide="none", stance="mixed",
  horizon="next_year", current_trading=None,
  quote="Focus on Furniture underperformed, and considerable work remains in its turnaround.",
  notes="Same company, same day, and the H1-will-be-difficult line is absent. A model reading only releases scores Adairs mixed instead of negative."),
 ("AEF", "Investor Presentation"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="medium_term", current_trading=None,
  quote="Targeting CTI in mid-60s over the medium term",
  notes="Medium-term target, not next-year guidance."),
 ("AEF", "Results Announcement"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Australian Ethical is targeting FY27 underlying expense growth to remain below revenue growth (subject to market movements)",
  notes="Relational, and explicitly conditioned on markets."),
 ("BRG", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="mixed",
  horizon="next_year", current_trading=None,
  quote="FY27 net US tariff position remains fluid and the effective tariffs we face will likely continue to evolve",
  notes="Genuinely hedged. Names an external risk it cannot size. Neither pessimism nor confidence."),
 ("CCX", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="mixed",
  horizon="current_trading_only",
  current_trading={"window": "first 7 weeks", "metric": "total trading revenue", "value": "flat vs pcp"},
  quote="Total SH trading revenue flat in first 7 weeks vs PCP",
  notes="Flat headline sales beside +11.4% ANZ comps. The two point different ways."),
 ("CCX", "Results Announcement"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="current_trading_only",
  current_trading={"window": "first 7 weeks", "metric": "ANZ store comp sales", "value": "+11.4%"},
  quote="First 7 weeks of FY27 maintaining momentum, with ANZ store comp sales growth of 11.4%",
  notes="The release leads on the comp figure, the presentation on the flat total. Same seven weeks, opposite framing."),
 ("COS", "Presentation"): dict(
  period="FY26", next_period_guide="segment", stance="positive",
  horizon="next_year", current_trading=None,
  quote="IBM revenue, now representing 25% of the FY26 performance (from zero in FY23) and anticipated to grow to circa 45% of the FY27 revenue",
  notes="A segment-mix number, not an earnings guide."),
 ("COS", "Results Announcement"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Recently secured contracts in digital and data services give COSOL confidence that revenue will grow in FY27.",
  notes="Confidence in growth with no magnitude. Also carries an interim-CEO transition that no tone label captures."),
 ("DRO", "Presentation"): dict(
  period="1H26", next_period_guide="full", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Supports FY2026 outlook range of $250M-$270M",
  notes="HALF-YEAR report, so the guided year is the CURRENT one. A model that maps document date to 'next FY' labels this wrong."),
 ("DUR", "Announcement"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="we enter FY27 with a record order book of $650.8m",
  notes="Order book is backlog, not guidance. The commonest false positive for a number-hunting extractor."),
 ("GNP", "Presentation"): dict(
  period="FY26", next_period_guide="full", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Genus forecasting to deliver circa $200m - $205m EBITDA FY2027",
  notes=""),
 ("GNP", "Announcement"): dict(
  period="FY26", next_period_guide="full", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Forecast EBITDA for FY2027 to be in the range of $200-205 million.",
  notes="Also guides recurring revenue ($764m) and capex ($65-70m)."),
 ("LOV", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="current_trading_only",
  current_trading={"window": "first 8 weeks", "metric": "total sales (constant currency)", "value": "+16.4%"},
  quote="Trading for the first 8 weeks of FY27 saw Total Sales for this period +16.4% (on a constant currency basis)",
  notes="A regex grabbed the +11.7% DIVIDEND increase from a nearby sentence instead of this. The near-miss is where a model earns its place."),
 ("LOV", "Announcement"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="current_trading_only",
  current_trading={"window": "first 8 weeks", "metric": "total sales (constant currency)", "value": "+16.4%"},
  quote="Trading for the first 8 weeks of FY27 saw total sales +16.4% (on a constant currency basis) on the same period in FY26 and comparable store sales +3.0%",
  notes=""),
 ("LYL", "Presentation"): dict(
  period="FY26", next_period_guide="full", stance="positive",
  horizon="next_year", current_trading=None,
  quote="FY27 GUIDANCE ... Between $540m and $580m Revenue ... Between $54m and $58m Net Profit After Tax ... +50% vs FY26 ... +40% vs FY26",
  notes="THE MOST QUANTIFIED GUIDE IN THE CORPUS, and sentence-based extraction misses it entirely: it is a slide layout, not prose. Any extractor that splits on sentences scores this as no guidance."),
 ("MAQ", "Investor Presentation"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="FY27 is expected to deliver modest growth. It is a year of strategic investment",
  notes="'Modest' is the whole signal. A polarity score reads it as positive and loses the qualifier."),
 ("MAQ", "Results Announcement"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="The Company's EBITDA is expected to have modest growth in FY27, assuming IC3 SuperWest Phase 1 revenue commences in 2H FY27.",
  notes="Conditional on a project milestone. The condition is load-bearing and no sentiment label carries it."),
 ("MND", "Reports"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="current_trading_only",
  current_trading={"window": "since 1 July", "metric": "new contracts secured", "value": "more than $680m"},
  quote="more than $680 million in new contracts secured since the beginning of the new financial year",
  notes=""),
 ("MND", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="neutral",
  horizon="next_year", current_trading=None,
  quote="FY27 is a year to consolidate and position for future growth",
  notes="'Consolidate' is a soft word doing real work. It sits beside 'Strong long-term outlook' in the same deck, which is the tension one score erases."),
 ("NWH", "Release"): dict(
  period="FY26", next_period_guide="full", stance="positive",
  horizon="next_year", current_trading=None,
  quote="FY27 Underlying EBITA guidance of $320 million to $330 million",
  notes="Cleanest example in the set: named metric, named range, named year, plus revenue $4.6-4.8bn with ~85% secured."),
 ("PNV", "Announcement"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Construction of PolyNovo's new manufacturing facility was completed, with validation activities progressing ahead of planned transition in FY27",
  notes="Operational milestone. No forward financial statement at all."),
 ("SIQ", "Presentation"): dict(
  period="1H26", next_period_guide="none", stance="neutral",
  horizon="next_year", current_trading=None,
  quote="Distribution partnerships continue to drive growth",
  notes="EXTRACTION POOR. Top candidates were an Acknowledgement of Country and a contents page."),
 ("SLC", "Announcement"): dict(
  period="FY26", next_period_guide="deferred", stance="positive",
  horizon="medium_term", current_trading=None,
  quote="Consistent with previous practice, we will be providing FY27 Guidance in November.",
  notes="Explicitly declines to guide, then gives an FY29 target ($1bn revenue, $200m EBITDA). A four-year target is not next-year guidance and must not be scored as one."),
 ("STP", "Presentation"): dict(
  period="FY26", next_period_guide="deferred", stance="neutral",
  horizon="next_year", current_trading=None,
  quote="No financial guidance will be issued.",
  notes="LABEL CORRECTED 09/09/2026. First labelled 'none' with the note 'extraction poor', because five of the seven candidate passages the old sentence-based selector returned were safe-harbour boilerplate and this line was not among them. tools/passages.py found it. The original note was right about the cause and the label was still wrong, which is what a bad selector costs a hand-labelled set. Filed as 'deferred' as the nearest class: SLC declines to guide UNTIL November, STP declines outright. Different claims, one class, because n=1 each and a sixth class nobody can measure is worse than a noted approximation."),
 ("UNI", "Presentation"): dict(
  period="FY26", next_period_guide="none", stance="neutral",
  horizon="next_year", current_trading=None,
  quote="Store network of 88 with five new stores opened during the year and one planned closure",
  notes="No forward financial statement. Store-count operational detail only."),
 ("UNI", "Results Announcement"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="The Group is well positioned heading into FY27.",
  notes="NULL SIGNAL. Textbook boilerplate optimism with no content. If a model scores this like NWH's guided range, the feature measures house style."),
 ("VEE", "Results Presentation"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="ASC expected to continue to be strong in 1HFY27",
  notes="FY26 landed at the upper end of its own guidance, which is BACKWARD-looking and reads identically to forward guidance to a keyword filter."),
 ("VEE", "Upper End"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="propeller orders increasing into Q4FY26 and continuing into FY27",
  notes="Headline says 'Upper End of Guidance' about FY26. The word guidance appears four times and never about FY27."),
 ("WGN", "Investor Presentation"): dict(
  period="FY26", next_period_guide="none", stance="positive",
  horizon="next_year", current_trading=None,
  quote="Operating EBIT +61% to $67.2 million, exceeding top-end of guidance range",
  notes="Backward-looking guidance achievement. The FY27 outlook is in the release, not here."),
 ("WGN", "Results Announcement"): dict(
  period="FY26", next_period_guide="relational", stance="positive",
  horizon="next_year", current_trading=None,
  quote="FY27 Outlook Market conditions experienced in the second half of FY26 are expected to continue into FY27.",
  notes="Relational: an H2 run-rate carried forward. No number, but a real and checkable claim."),
}


def main() -> None:
    out = []
    unmatched = dict(L)
    for key, v in CANDS.items():
        for (tk, word), lab in L.items():
            if v["ticker"] == tk and word.lower() in v["headline"].lower():
                out.append({"document_key": key, "ticker": tk,
                            "headline": v["headline"], "announced": v["announced"],
                            **lab})
                unmatched.pop((tk, word), None)
                break
    assert not unmatched, f"labels matched no document: {list(unmatched)}"
    assert len(out) == len(CANDS), (
        f"{len(CANDS) - len(out)} of {len(CANDS)} documents unlabelled: "
        f"{[v['ticker'] + ' ' + v['headline'][:30] for k, v in CANDS.items() if k not in {o['document_key'] for o in out}]}")
    (ROOT / "gold/labels.json").write_text(
        json.dumps({"labelled": "2026-09-09", "by": "hand", "n": len(out),
                    "documents": out}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"{len(out)} documents labelled")


if __name__ == "__main__":
    main()
