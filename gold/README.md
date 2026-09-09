# Gold set

**43 documents from 31 ASX companies, hand-labelled 09/09/2026**, in two halves
that were sampled differently and must stay separable:

- **33 results documents** from the collector's own universe (`labels.json`).
- **10 downgrades and profit warnings** found by sweeping the market-wide
  announcement feed (`labels_negative.json`), because the results half is 25
  positive to 1 negative and could not measure stance at all.

A model scored on the combined set is being scored on a **deliberately balanced
sample, not a natural one**. Say which half any number came from.

`build_labels.py` and `build_negatives.py` are where the labels are written and
reviewed; they emit the two JSON files. `extract_candidates.py` pulls the
forward-looking passages that were read to assign them, and `find_negatives.py`
sweeps the market for the second half.

**Nothing here was produced by a model.** The point of the set is to have
something a model can be wrong against.

## Read this before quoting an accuracy number off it

**Stance is now measurable, but only just.** The majority-class baseline is
**58%** across the combined set (25 positive of 43), down from 76% on the
results half alone. A model has to beat 58% before it has demonstrated anything,
and the number worth reporting is **sign errors on the 14 negative and mixed
documents**, not overall accuracy.

The results half on its own remains unusable for stance: 25 positive to 1
negative.

**Guide type is measurable.** `next_period_guide` runs 25 / 9 / 7 / 1 / 1
across its five classes, spread enough to catch a model that collapses them.
That is the label to score first.

**Horizon still is not.** One split-horizon document in 43.

## Distribution

Combined, n = 43:

| stance | n | | next_period_guide | n |
|---|---|---|---|---|
| positive | 25 | | none | 25 |
| negative | 7 | | relational | 9 |
| mixed | 7 | | full | 7 |
| neutral | 4 | | segment | 1 |
| | | | deferred | 1 |

Horizon: 34 next_year, 6 current_trading_only, 2 medium_term, 1 split.
Current trading disclosed in 6 documents, five positive or flat and one
negative (SSG).

## How the negatives were found

The per-ticker index keeps five items and will not page. The **market-wide**
feed at `/markets/announcements` is different: it pages back to a hard cap of
100 pages of 100 items, about **9,899 announcements over 20 days**, every listed
company. `find_negatives.py` sweeps it, filters to price-sensitive
downgrade-shaped headlines, and the survivors were read by hand.

That is the only way to find a downgrade without knowing in advance who issued
it, and **it is a better collection mechanism than per-ticker polling** - see
the note in the repo README.

Headlines do not give it away. Of 83 price-sensitive candidates, the genuine
downgrades were titled "Market Update", "Business Update" and "Non-cash
impairment". Several headlines that sounded bad were records or upgrades.

## What the larger sample changed

**"One in ten gives a number" was wrong.** That came from ten documents, one per
company, all presentations. With releases included and 21 companies, **four
companies give a full quantified guide for the next period** — GNP, LYL, NWH,
and DRO for its current year — so it is closer to one in five. Still a minority,
still not enough to build a numeric series on, but not as thin as the first pass
said.

**Sentence-based extraction misses the best guidance in the corpus.**
Lycopodium's FY27 guidance is revenue between $540m and $580m and NPAT between
$54m and $58m, +50% and +40% on FY26. It is the most quantified statement
anywhere in these 33 documents and `extract_candidates.py` does not surface a
word of it, because it is a slide layout rather than prose and nothing in it
forms a sentence. It was found by grepping the raw text. Any extractor that
splits on sentence boundaries scores Lycopodium as giving no guidance.

**Which document you read changes the answer a third of the time.** 12 companies
filed both a presentation and a release. **Four of them disagree on stance**
between the two: ADH, CCX, MND, UNI.

The Adairs pair is the one to look at. The presentation says *"H1 FY27 will
remain difficult as the weaker fourth-quarter order book carries into the new
financial year"* — the clearest negative statement in the entire corpus. The
release, same company, same day, does not contain it. A pipeline that reads one
document per company has a one-in-three chance of reading the wrong one, and on
Adairs it would miss the only genuine downgrade in the set.

City Chic is the same fault in miniature: the presentation leads with *"Total SH
trading revenue flat in first 7 weeks"* and the release leads with *"first 7
weeks maintaining momentum, ANZ store comp sales growth of 11.4%"*. Same seven
weeks, opposite framing.

## The traps a model has to survive

Each of these is a real document in the set, not a hypothetical.

- **Backward-looking guidance reads exactly like forward guidance.** WGN's
  "exceeding top-end of guidance range" and VEE's "Upper End of Guidance" are
  both about FY26. VEE uses the word guidance four times and never about FY27.
- **A half-year report's forward period is the current year.** DRO guides
  FY2026 in a 1H26 deck. Mapping document date to "next FY" labels it wrong.
- **Order book is not guidance.** DUR's record $650.8m is backlog. It is the
  commonest false positive for anything hunting for a large number near a
  forward verb.
- **A four-year target is not next-year guidance.** SLC explicitly defers FY27
  guidance to November and then gives an FY29 ambition of $1bn revenue and $200m
  EBITDA. Scoring that as next-year guidance is a category error.
- **Qualifiers carry the signal.** MAQ says "modest growth in FY27, assuming
  IC3 SuperWest Phase 1 revenue commences in 2H FY27". A polarity score returns
  positive and loses both the size and the condition.
- **Null signals must score as null.** UNI's "The Group is well positioned
  heading into FY27" is boilerplate with no content. If a model scores it like
  NWH's "$320 million to $330 million", the feature is measuring house style.
- **The safe-harbour block outranks real guidance.** STP had five of seven
  candidate passages come back as disclaimer text.

- **Guidance held is not guidance safe.** TerraCom is producing "below plan
  during the early part of FY2027" and *maintains* its production guidance
  "at this time", promising to update "should its expectations materially
  change". A model keying on "maintains its guidance" scores this positive.
  It is a pre-downgrade and the best single document in the set.
- **A cut and a record in one breath.** Select Harvests cuts external grower
  volumes from 15,400MT to 13,800-14,200MT and calls the crop "near record" and
  "an exceptional result" in the same update. One line down, another up.
- **The number can be in the table and never in the prose.** Embark reports a
  swing from +$4.0m to -$12.7m as a line in an interim accounts table, third,
  under a bank facility renewal and a dividend. The word "loss" never appears.
- **Attach the number to the right entity.** Dicker Data's group profit before
  tax rose 50.1% while New Zealand fell to $4.0m on "softer market conditions".
  Both numbers are in the same release.
- **A loss is not always bad news.** Actinogen's loss widened to $15.4m, which
  is the expected state of a pre-revenue biotech. Included on purpose: a model
  that scores every loss as negative is wrong about a whole sector.

## How to score a model against this

Report **catches and false positives per class**, not one accuracy figure.
Start with `next_period_guide`, which is the only label with enough spread.
Sign errors on `stance` are the ones that would cost money, so count those
separately from misses even once the class balance is fixed.