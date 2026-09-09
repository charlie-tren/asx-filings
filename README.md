# ASX Outlook Watch

A daily collector for ASX results announcements. It sweeps the market-wide
announcement feed, records what it saw, and stores the extracted text of
anything results-shaped from the companies in `universe.json`.

It exists to build a corpus that cannot be built later.

## Why it runs every day

Ingestion pages back about **20 days** before the feed's 100-page cap. That is
more slack than the per-ticker index, which returns **the last five
announcements and will not paginate** under any parameter tried, but it is still
a window with a hard edge.

There is no archive behind it. Once an announcement falls past the cap it cannot
be fetched again.

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
| `fetches` | one row per sweep PAGE and one per universe ticker, per run, recording whether each read worked |
| `runs` | one row per run |

`fetches` is the load-bearing one, and it holds two kinds of row. `page:N` rows
say whether the sweep finished, because **a sweep that stopped at page 12 looks
exactly like a quiet market**. Ticker rows say whether a code still exists,
because **a ticker whose index fails every night looks exactly like a ticker
with nothing to announce**. Neither question can be answered by the other's
rows.

## Ingestion is the market-wide feed

`/markets/announcements` returns announcements for **every listed company** and,
unlike the per-ticker index, it **pages**:

    /markets/announcements?itemsPerPage=100&page=N

`itemsPerPage` is the parameter that works. `pageSize` is silently ignored and
returns 25. `startDate`, `endDate`, `date` and `days` are ignored too. Hard cap
at 100 pages of 100 items: measured **9,900 announcements over 20 calendar
days**, about 550 a day across 1,845 tickers.

**Coverage was checked before migrating, not assumed.** Against the per-ticker
index for all 67 universe tickers, the feed carried **227 announcements the
five-item index could not see**, and missed 23. Every one of the 23 was a
substantial-holding notice or an index rebalance - the S&P DJI rebalance is
filed under MIN rather than under each affected company, and shareholding
notices are filed under the HOLDER's symbol (NXL, AFG) rather than the company
held. Two were absent outright. **Not one was a results, outlook, guidance or
trading document.**

The first migrated run took the corpus from 33 documents across 17 tickers to
**77 across 45**, because the feed still held results the per-ticker windows had
already dropped.

### The per-ticker loop survives as a liveness probe

It does not download anything and it costs about a minute. It is kept because
**the sweep cannot tell a delisted code from a company with nothing to say** -
absence from a market-wide feed is the normal state. Only asking a ticker's own
index returns `400 Symbol not found`, which is how IFM, JLG and RUL were found.

### What is recorded

Announcement metadata for universe tickers (all types) plus **everything the ASX
flagged price-sensitive, market-wide**. The remaining 74% is director-interest
notices, quotation applications and substantial holdings for 1,800 companies
this project does not follow, and it will never be read. Documents are
downloaded only for universe tickers.

`data/announcements/` is **sharded by month**, keyed on the announcement's own
date so a backfill lands in the month it belongs to. At ~145 recorded rows a day
a single file would reach ~53,000 rows a year and re-diff itself on every
commit.

### The new failure mode

A sweep that stops early looks exactly like a quiet market. Every page outcome
is recorded as a `page:N` row in `fetches`, and both the collector and the health
check fail the run below 80 of 100 pages.

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
python tools/collect.py --pages 3       # short sweep, for testing
python tools/collect.py --no-probe      # skip the per-ticker liveness probe
python tools/collect.py --dry-run       # sweep and record, download nothing
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

**Registered and deployed 09/09/2026.** `TARGETS` in
`site-stats/heartbeat/src/index.js`, content slot, verified against the Worker's
own status endpoint rather than assumed:

    curl -s https://heartbeat.charlie-rochfordgroup.workers.dev | python -m json.tool

**This repo must stay PUBLIC.** That Worker's token is scoped `public_repo`, so
a private target 404s on every dispatch and the only symptom is a job that never
runs.

## What this is not

It does not extract features, score anything, or publish. It builds the corpus
those things would need, starting now, because starting later means starting
with less.

The first like-for-like pair for a year-on-year guidance comparison lands in
**August 2027**. February 2027 gives halves against fulls, which is a different
claim.

## The extraction layer

`tools/passages.py` narrows a document to its forward-looking text with regexes,
`tools/extract.py` sends that to a model for the one thing rules cannot do, and
`tools/score.py` measures the result against `gold/`. The model returns
structured fields and stops; nothing here ranks, scores or decides, and no model
call happens inside anything serving a page.

Passage selection has two modes and needs both. Sentences for prose releases,
character WINDOWS around anchors for slides - Lycopodium's FY27 guidance
($540-580m revenue, $54-58m NPAT) contains no sentence at all, and a splitter
scores it as no guidance.

### Correction, 09/09/2026: the provider was right and this code was wrong

An earlier commit message and a block of comments here claimed that this API
returns `400 API_KEY_INVALID` for a valid key when the model behind it is
overloaded. **That was false.** In `--gold` mode a loop variable named `key`
shadowed the API key, so a 23-character document key was being sent as
credentials, deterministically, for hours. The service said the key was not
valid because the key was not valid.

Retry ladders and a `verify_key()` probe were built for the imagined provider
fault and have been removed. `API_KEY_INVALID` is terminal again.

Worth keeping, because the failure was legible the whole time and the debugging
was not: the difference between the failing batch and every passing manual test
was never inspected directly. One `print(len(key))` at the call site settled in
seconds what an afternoon of theories about the provider did not.

### Free tier

`gemini-2.5-flash` and `gemini-2.5-flash-lite` are LISTED by `models?key=` and
answer 404 "no longer available to new users". Being listed is not being usable:
enumerate, then walk a candidate list.

The quota is **20 calls per day, per model** - the 429 body names it exactly
(`limit: 20, model: gemini-3-flash`). Per-model is the useful half: trial work
goes on a sibling so it cannot starve a scheduled run. The "Please retry in
29.5s" hint on that error is a bucket-refill estimate and is not true of the
daily cap.

`GROQ_API_KEY` in `.env` is dead (401) and needs re-issuing. Groq's 100K
tokens/day suits this far better than 20 calls/day, since a selected passage
bundle is ~1,500 tokens.
