# ASX Outlook Watch

A daily collector for ASX results announcements. It reads each ticker's
announcement index, records everything it saw, and stores the extracted text of
anything results-shaped.

It exists to build a corpus that cannot be built later.

## Why it runs every day

The free ASX announcement index returns **the last five announcements per
ticker and will not paginate.** Tested on 09/09/2026 with `pageSize`, `count`,
`page`, `pageIndex`, `dateFrom`/`dateTo` and `years`, against both hosts: every
one returns the same five items.

There is no backfill and no archive. When a sixth announcement lands, the oldest
is gone.

Of 20 tickers probed on 9 September, **eight had already lost their August FY26
results**: NCK, TPW, JIN, SDR, NAN, CTD, IEL and BAP. Those documents were three
weeks old.

Three things follow, and they shape everything here:

1. **A missed day is a permanently missed document.** Not a gap to repair later.
2. **The job cannot run seasonally.** A busy fortnight removes a name.
3. **A silent failure is unrecoverable.** So the health check is not optional
   decoration, it is the point. See `tools/health.py`.

## What it stores

The PDF is transport. The **text** is the corpus, and it is what gets committed:
200 names of 3MB decks a year does not belong in git, and roughly 30KB of text
per document does.

| Table | What it is for |
|---|---|
| `announcements` | every announcement ever seen, keyed by `documentKey` |
| `documents` | the ones whose text was extracted and kept |
| `rejections` | why a seen document was not kept, so a rejected document and an unexamined one are distinguishable |
| `fetches` | one row per ticker per run, recording whether the index read itself worked |
| `runs` | one row per run |

`fetches` is the load-bearing one. **A ticker whose index fails every night looks
exactly like a ticker with nothing to announce** unless the fetch outcome is
recorded, and by the time anyone notices, the window has moved on.

## Two hosts, and they are not interchangeable

- **Index**: `asx.api.markitdigital.com`
- **Documents**: `cdn-api.markitdigital.com` (the apiman gateway)

A 2.6MB presentation **truncates silently** on the api host: `%PDF-` header,
plausible length, no error, and no `%%EOF`. It parses as a valid download and
fails much later in the extractor. The same file arrives whole from the gateway
in 8 seconds. `common.pdf_is_complete()` checks the EOF marker on every
download, and `tests/test_collector.py` asserts the configured host rather than
leaving it as a comment.

The old `asx.com.au/asx/1/company/<code>/announcements` API is dead (404).

## What the filters are for

Headline triage happens before download, substance is checked after extraction,
and both are needed because **the headline lies about the document.**

- MAD and PNV both announced "FY26 Results Presentation" in August 2026. Both
  are one-page PDFs linking to a webcast recording: ~1,700 characters, zero
  forward-looking markers.
- ARB's "Corporate Governance Statement FY2026" was admitted by an early filter
  matching `fy2026`. **A year token is not a document type.**
- SIQ's "Half Year Results 2026" was admitted as a full-year document.

The safe-harbour disclaimer is the biggest source of false positives in any
downstream text analysis: it is written out of the exact vocabulary a
forward-looking keyword filter looks for, and it appears in every deck. It is
not filtered here, because this repo stores whole documents. Anything reading
the text has to exclude it explicitly.

## Running it

```bash
pip install -r requirements.txt
python tools/collect.py                 # the daily job
python tools/collect.py --only GNP,ADH  # one or two names
python tools/collect.py --dry-run       # read indexes, download nothing
python tools/health.py                  # is it running, and is it keeping things
python -m pytest tests -q
```

## The universe

`universe.json`, hand-curated. **There is no free point-in-time Small Ordinaries
constituent list**, so this is not index membership and must not be described as
one anywhere it is published. Adding codes is free: the collector keys on
`documentKey`, so re-running is idempotent.

## Scheduling

The GitHub cron in `.github/workflows/collect.yml` is the **backstop**. The
primary trigger is a `repository_dispatch` from `site-stats/heartbeat`, because
GitHub's scheduler on this account has been measured 3 to 7 hours late with no
open incident, and a job whose whole purpose is not missing a day cannot depend
on it.

**Not yet registered in the heartbeat Worker.** Adding it means an entry in
`TARGETS` in `site-stats/heartbeat/src/` alongside the `repository_dispatch`
trigger already in the workflow here. One without the other is silent.

## What this is not

It does not extract features, score anything, or publish. It builds the corpus
those things would need, starting now, because starting later means starting
with less.

The first like-for-like pair for a year-on-year guidance comparison lands in
**August 2027**. February 2027 gives halves against fulls, which is a different
claim.
