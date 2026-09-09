"""The extraction layer: text in, features out.

ARCHITECTURE, and it is deliberate. The model converts language into structured
features and stops there. It does not score, rank, or decide anything. Whatever
reads the features afterwards is ordinary code over ordinary columns, and the
model is never in a runtime loop - this runs as an offline batch and writes to
the ledger like every other producer here.

WHAT THE MODEL IS AND IS NOT FOR. tools/passages.py already narrows a 33,000
character deck to ~2,000 characters of forward-looking text with regexes, for
free. Rules can also pull most of the numbers: a sweep over the corpus found
current-trading figures for CCX and LOV and the quantified guide for GNP without
any model at all. What rules could NOT do was attach a number to the right
claim - the regex grabbed Lovisa's +11.7% DIVIDEND increase and reported it as
the eight-week sales figure, which is +16.4% in a different sentence. That
disambiguation is the job.

EVERY RECORD SAYS WHICH MODEL ANSWERED. Ghostwriters shipped a corpus half
scored by one model and half by another after a quota fallback nobody recorded,
and ranked them in one column. A fallback is fine. An unrecorded fallback is
invisible for days.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import common
import passages

PROMPT_VERSION = "1"

SCHEMA_NOTE = """Return ONE JSON object, no prose around it, with exactly these keys:

"next_period_guide": one of
   "full"       a number or numeric range for the NEXT period's earnings,
                revenue, EBITDA or production. A guided figure.
   "relational" a forward constraint with no number: "modest growth",
                "expenses to grow below revenue", "H2 conditions to continue".
   "segment"    a number for one segment or line only, not the group.
   "deferred"   explicitly declines to guide, now or at all.
   "none"       no forward figure and no forward constraint.
"stance": "positive" | "negative" | "mixed" | "neutral" - about the FORWARD
   period only.
"horizon": "next_year" | "split" | "medium_term" | "current_trading_only".
   Use "split" when near-term and later are given opposite directions.
"guided_period": the period the forward statement is about, e.g. "FY27",
   "1H FY27", or null.
"current_trading": an object {"window","metric","value"} if the document
   discloses trading for a period that has ALREADY ELAPSED, else null.
"quote": the single most load-bearing forward-looking line, verbatim.
"confidence": "high" | "low".

RULES, each from a real document:
- An achievement against LAST year's guidance is NOT forward guidance.
  "exceeding top-end of guidance range" and "Upper End of Guidance" describe the
  year just reported. If the only mention of guidance is backward, answer "none".
- A HALF-YEAR report's forward period is the CURRENT financial year, not the
  next one. Read the period from the document, never from the date.
- An order book, backlog or pipeline figure is NOT guidance.
- A three or four year ambition is NOT next-period guidance. If a company defers
  next-year guidance and gives an FY29 target, that is "deferred".
- Qualifiers carry the signal. "modest growth ... assuming Phase 1 revenue
  commences in 2H" is relational and conditional, not a confident positive.
- Boilerplate optimism with no content ("well positioned heading into FY27") is
  stance "neutral" and guide "none".
- Guidance MAINTAINED alongside bad news is not reassurance. If a company is
  producing below plan and holds guidance "at this time", the stance is negative.
- A loss at a pre-revenue company is its normal state, not a downgrade."""


# --------------------------------------------------------------------------
# providers
# --------------------------------------------------------------------------

class ProviderError(Exception):
    """Carries the WHOLE response body. A 200-character cap on an error body
    produced three wrong diagnoses on this estate, because the field naming the
    real cause sits past the cut - Gemini's daily-quota id is one of them."""

    code: int = 0
    transient: bool = False
    suspect_key: bool = False


def _post(url: str, payload: dict, headers: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 # urllib sends Python-urllib/3.x and Cloudflare blocks it with
                 # error 1010 before the key is ever checked, which reads as an
                 # auth failure.
                 "User-Agent": "asx-outlook-watch/0.1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.loads(fh.read().decode())
    except urllib.error.HTTPError as e:
        err = ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        err.code = e.code
        # 429 is a wall and retrying spends time to fail anyway - Gemini's
        # daily-quota 429 even carries a "retry in 59s" hint that is a
        # bucket-refill estimate and a lie for that quota. 500/503 are weather.
        err.transient = e.code in (500, 502, 503, 504)
        # MEASURED 09/09/2026: this API returns 400 API_KEY_INVALID for a key
        # that is valid, when the model behind it is overloaded. The same key
        # answered a probe seconds earlier and seconds later. Treating that
        # message at face value stopped a whole batch and would have killed a
        # nightly run with a diagnosis pointing at the wrong thing entirely.
        # Verified, not assumed: see verify_key().
        # ...and it is treated as TRANSIENT rather than terminal. A key that is
        # genuinely dead fails every retry, extracts nothing and exits non-zero,
        # which is visible. A key that is fine and was libelled once must not be
        # allowed to stop a nightly batch.
        if e.code == 400 and "API_KEY_INVALID" in str(err):
            err.transient = True
        raise err


VERIFY_MODELS = {
    "gemini": ["gemini-3-flash-preview", "gemini-flash-lite-latest",
               "gemini-3.6-flash"],
    "groq": ["llama-3.3-70b-versatile"],
}


def verify_key(provider: str, key: str) -> bool:
    """One cheap call to settle whether a reported bad key is really bad.

    "A secret is set" and "the secret works" are different claims, and so are
    "the service said the key is invalid" and "the key is invalid".
    """
    for model in VERIFY_MODELS[provider]:
        try:
            if provider == "gemini":
                call_gemini(model, 'Reply {"ok":true}', key)
            else:
                call_groq(model, 'Reply {"ok":true}', key)
            return True
        except ProviderError as e:
            # Only an AUTH failure is evidence about the key. A 503 on the
            # verification model says nothing at all, and reading it as "key
            # rejected" is the same mistake one level down.
            if e.code in (401, 403) or "API_KEY_INVALID" in str(e):
                continue          # try the next model before concluding
            return True           # not an auth problem, so not a key problem
    return False


def call_gemini(model: str, prompt: str, key: str) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = _post(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }, {})
    return body["candidates"][0]["content"]["parts"][0]["text"]


def call_groq(model: str, prompt: str, key: str) -> str:
    body = _post("https://api.groq.com/openai/v1/chat/completions", {
        "model": model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }, {"Authorization": f"Bearer {key}"})
    return body["choices"][0]["message"]["content"]


PROVIDERS = {
    "gemini": (call_gemini, "GEMINI_API_KEY"),
    "groq": (call_groq, "GROQ_API_KEY"),
}

VALID = {
    "next_period_guide": {"full", "relational", "segment", "deferred", "none"},
    "stance": {"positive", "negative", "mixed", "neutral"},
    "horizon": {"next_year", "split", "medium_term", "current_trading_only"},
    "confidence": {"high", "low"},
}


def build_prompt(ticker: str, headline: str, announced: str, text: str) -> str:
    return (
        "You are reading one ASX company announcement and extracting facts about "
        "what the company said about its FUTURE. Extract only. Do not judge "
        "whether it is a good investment.\n\n"
        f"Company: {ticker}\nHeadline: {headline}\nFiled: {announced}\n\n"
        f"{SCHEMA_NOTE}\n\n"
        "PASSAGES (already filtered to forward-looking text; '---' separates "
        f"them):\n{text}\n")


def parse(raw: str) -> dict:
    """Parse and VALIDATE. A small model will invent an enum value, and an
    invalid label that reaches the ledger is worse than a refusal because it
    silently becomes a sixth class nobody scores."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    obj = json.loads(raw)
    for field, allowed in VALID.items():
        if obj.get(field) not in allowed:
            raise ValueError(f"{field}={obj.get(field)!r} not in {sorted(allowed)}")
    if not isinstance(obj.get("quote"), str) or not obj["quote"].strip():
        raise ValueError("missing quote")
    return obj


def extract_one(doc: dict, ann: dict, provider: str, model: str,
                key: str) -> dict:
    text = (common.ROOT / doc["text_path"]).read_text(encoding="utf-8")
    selected = passages.select(text)
    prompt = build_prompt(doc["ticker"], ann["headline"],
                          ann["announced_at"][:10], selected)
    fn, _ = PROVIDERS[provider]
    raw = fn(model, prompt, key)
    obj = parse(raw)
    return {
        "document_key": doc["document_key"], "ticker": doc["ticker"],
        "next_period_guide": obj["next_period_guide"], "stance": obj["stance"],
        "horizon": obj["horizon"],
        "guided_period": obj.get("guided_period"),
        "current_trading": json.dumps(obj.get("current_trading"),
                                      ensure_ascii=False),
        "quote": obj["quote"][:600], "confidence": obj["confidence"],
        # Pinned to the record, not to a config file, so a corpus written by two
        # models can always be split apart afterwards.
        "provider": provider, "model": model, "prompt_version": PROMPT_VERSION,
        "selected_chars": len(selected),
        "extracted_at": common.now_iso(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="gemini", choices=sorted(PROVIDERS))
    # gemini-2.5-flash is LISTED by models?key= and answers 404 "no longer
    # available to new users". Being listed is not being usable: enumerate, then
    # walk a candidate list, and never trust a model name from memory.
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--limit", type=int, default=10,
                    help="call budget. Gemini's free tier is 20 PER DAY PER "
                         "MODEL, so this is the parameter that matters.")
    ap.add_argument("--only", help="comma-separated tickers")
    ap.add_argument("--gold", action="store_true",
                    help="extract the GOLD SET, including the ten negatives, "
                         "which live in gold/negatives_raw rather than in the "
                         "corpus because they were found by a market sweep")
    ap.add_argument("--redo", action="store_true",
                    help="re-extract documents already done by this model")
    args = ap.parse_args()

    key = os.environ.get(PROVIDERS[args.provider][1], "")
    if not key:
        env = common.ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k.strip() == PROVIDERS[args.provider][1]:
                    key = v.strip().strip('"').strip("'")
    if not key:
        print(f"FAIL: {PROVIDERS[args.provider][1]} is not set", file=sys.stderr)
        return 1

    # In memory: this database is a lookup index over the ledger, nothing more,
    # and writing it to disk would fight the collector for the same file.
    con = common.rebuild_db(":memory:")
    ann = {a["document_key"]: a for a in common.read_ledger("announcements")}
    docs = [d for d in common.read_ledger("documents") if d["document_key"] in ann]

    if args.gold:
        import json as _json
        gold_docs, gold_ann = [], {}
        for name in ("labels.json", "labels_negative.json"):
            path = common.ROOT / "gold" / name
            if not path.exists():
                continue
            for g in _json.loads(path.read_text(encoding="utf-8"))["documents"]:
                key = g["document_key"]
                gold_ann[key] = {"headline": g["headline"],
                                 "announced_at": g["announced"]}
                existing = next((d for d in docs if d["document_key"] == key), None)
                if existing:
                    gold_docs.append(existing)
                elif g.get("text_path"):
                    gold_docs.append({"document_key": key, "ticker": g["ticker"],
                                      "text_path": g["text_path"]})
        docs, ann = gold_docs, gold_ann
        print(f"gold mode: {len(docs)} labelled documents")
    if args.only:
        keep = {t.strip().upper() for t in args.only.split(",")}
        docs = [d for d in docs if d["ticker"] in keep]

    done = {(f["document_key"], f["model"]) for f in common.read_ledger("features")}
    todo = [d for d in docs
            if args.redo or (d["document_key"], args.model) not in done]
    todo = todo[:args.limit]
    print(f"{len(docs)} documents, {len(todo)} to extract with "
          f"{args.provider}/{args.model}")

    ok = 0
    for d in todo:
        row = None
        for attempt in (1, 2, 3, 4):
            try:
                row = extract_one(d, ann[d["document_key"]], args.provider,
                                  args.model, key)
                break
            except ProviderError as e:
                # Print the whole body. The daily-quota id lives past 900 chars.
                print(f"{d['ticker']} attempt {attempt}: {e}", file=sys.stderr)
                if not e.transient:
                    print("  not retryable, stopping the batch", file=sys.stderr)
                    row = "stop"
                    break
                # 15s, 30s, 45s. The earlier 6s ladder gave up inside the
                # window: AEF failed five times in a row with API_KEY_INVALID
                # and the same prompt succeeded on the same key minutes later.
                time.sleep(15 * attempt)
            except Exception as e:                               # noqa: BLE001
                print(f"{d['ticker']}: {type(e).__name__}: {str(e)[:300]}",
                      file=sys.stderr)
                break
        if row == "stop":
            break
        if row is None:
            continue
        common.append("features", row)
        cols = common.COLUMNS["features"]
        con.execute(f"INSERT OR REPLACE INTO features "
                    f"VALUES({','.join('?' * len(cols))})",
                    [row.get(c) for c in cols])
        con.commit()
        ok += 1
        print(f"  {d['ticker']:5} {row['next_period_guide']:10} "
              f"{row['stance']:8} {row['horizon']:22} {row['quote'][:44]}")
        time.sleep(1.0)

    print(f"\n{ok}/{len(todo)} extracted")
    return 0 if ok or not todo else 1


if __name__ == "__main__":
    raise SystemExit(main())
