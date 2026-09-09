# Gold set

33 documents from 21 ASX companies, FY26 results, hand-labelled 09/09/2026.
`labels.json` is the machine-readable version; `build_labels.py` is where the
labels are written and reviewed. `extract_candidates.py` pulls the
forward-looking passages that were read to assign them.

**Nothing here was produced by a model.** The point of the set is to have
something a model can be wrong against.

## Read this before quoting an accuracy number off it

**Stance is unusable as a benchmark.** 25 of 33 documents are positive and
exactly **one** is negative. A model that answers "positive" to everything
scores 76%, so any stance accuracy measured here is measuring the base rate, not
the model. Before stance can be scored, the set needs negatives on purpose:
either a reporting season with more bad news in it, or a deliberate hunt for
downgrades and profit warnings.

**Guide type is measurable.** `next_period_guide` runs 19 / 7 / 5 / 1 / 1 across
its five classes, which is spread enough to catch a model that collapses them.
That is the one label to score first.

**Horizon is not measurable either.** One split-horizon document in 33.

## Distribution

| next_period_guide | n | | stance | n |
|---|---|---|---|---|
| none | 19 | | positive | 25 |
| relational | 7 | | neutral | 4 |
| full | 5 | | mixed | 3 |
| segment | 1 | | negative | 1 |
| deferred | 1 | | | |

Period: 31 full-year, 2 half-year. Current trading disclosed in 5 documents
(CCX x2, LOV x2, MND).

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

## How to score a model against this

Report **catches and false positives per class**, not one accuracy figure.
Start with `next_period_guide`, which is the only label with enough spread.
Sign errors on `stance` are the ones that would cost money, so count those
separately from misses even once the class balance is fixed.
