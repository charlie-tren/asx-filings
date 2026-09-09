"""Select the forward-looking passages of a document, before any model sees it.

This is the cheap half and it does most of the work. A 33,000-character deck
becomes ~2,000 characters of candidate text, which is the difference between an
8,300-token call and a 600-token one - and on a free tier the call budget is the
binding constraint, not accuracy.

TWO EXTRACTION MODES, because one is not enough:

  sentences  prose releases, where guidance is written in sentences.
  windows    presentation slides, where it is NOT. Lycopodium's FY27 guidance -
             revenue $540-580m, NPAT $54-58m, +50% and +40% on FY26, the most
             quantified statement in the whole gold set - extracts as
             "FY27 GUIDANCE Growing volume of work underpinning future earnings
             18 $540m & $580m Between Revenue". No full stops, no sentences.
             A sentence splitter returns nothing and scores LYL as giving no
             guidance at all.

So windows are taken around forward-looking ANCHORS by character offset, which
does not care whether the text is prose.
"""

from __future__ import annotations

import re

# Anchors worth building a window around. Ordered by how much they usually carry.
ANCHOR = re.compile(
    r"\b(FY\s?20?2[6-9]|1H\s?FY?\s?2[6-9]|2H\s?FY?\s?2[6-9]|H[12]\s?FY\s?2[6-9]|"
    r"guidance|outlook|forecast\w*|expect\w*|anticipat\w*|"
    r"first \d{1,2} weeks|year to date|trading (?:update|to date)|"
    r"on track|target\w*|intend\w*)\b", re.I)

# The safe-harbour block is written out of the exact vocabulary above and appears
# in every deck. On the first pass it outranked real guidance in several of them,
# and five of Step One's seven candidate passages were disclaimer text.
BOILER = re.compile(
    r"forward.{0,3}looking statement|not a recommendation|no representation|"
    r"disclaimer|indicative only|past performance|to the maximum extent|"
    r"can generally be identified|similar expressions|cannot be relied upon|"
    r"actual results may|no obligation to update|not a prospectus|"
    r"disclosure document|offering document|will not be lodged|"
    r"nothing contained in it|no assurance that|registered under the U\.?S|"
    r"seek independent|financial product advice|before making any investment|"
    r"subject to change without notice|accepts no (?:liability|responsibility)|"
    r"does not purport to be complete|should not be considered advice|"
    r"may or may not be achieved|inherently uncertain",
    re.I)

NOISE = re.compile(
    r"^(note|source|for personal use|page \d|contents|appendix|"
    r"acknowledgement of country)", re.I)

WINDOW = 260          # characters either side of an anchor
MAX_CHARS = 4000      # hard ceiling on what any model is asked to read


def _clean(text: str) -> str:
    text = text.replace(" ", " ")
    # "For personal use only" is stamped down the side of every ASX PDF and
    # lands mid-sentence in the extracted text.
    text = re.sub(r"For personal use only", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _drop_boiler(text: str) -> str:
    """Blank out the safe-harbour paragraphs before anything else looks."""
    out, last = [], 0
    for m in BOILER.finditer(text):
        # A disclaimer sentence, not just the phrase: widen to the surrounding
        # full stops so the whole clause goes.
        start = text.rfind(".", 0, max(0, m.start() - 1)) + 1
        end = text.find(".", m.end())
        end = len(text) if end == -1 else end + 1
        if start < last:
            start = last
        out.append(text[last:start])
        last = max(last, end)
    out.append(text[last:])
    return "".join(out)


def windows(text: str, width: int = WINDOW) -> list[str]:
    """Character windows around every forward-looking anchor, merged where they
    overlap. Works on slide layouts, which have no sentences."""
    spans: list[list[int]] = []
    for m in ANCHOR.finditer(text):
        lo, hi = max(0, m.start() - width), min(len(text), m.end() + width)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    return [text[a:b].strip() for a, b in spans]


def sentences(text: str) -> list[str]:
    """Sentence-shaped candidates, for prose releases.

    The splitter deliberately does not break on a full stop that follows a
    title, an initial or an abbreviation: Mr., Mrs., Dr., St., No., e.g., and a
    single capital letter. Splitting on those puts "One must admire the
    fortitude of Mrs." at the end of one passage and "Brown, who..." at the
    start of the next.
    """
    parts = re.split(
        r"(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\bNo)(?<!\be\.g)(?<!\b[A-Z])"
        r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts]


def select(text: str, max_chars: int = MAX_CHARS) -> str:
    """The passage bundle a model is asked to read.

    Windows first because they catch slide layouts, then any sentence that
    mentions the next period and was not already covered.
    """
    text = _drop_boiler(_clean(text))
    chosen: list[str] = []
    seen: set[str] = set()

    def add(chunk: str) -> None:
        chunk = chunk.strip()
        if len(chunk) < 30 or NOISE.match(chunk):
            return
        key = re.sub(r"\W", "", chunk[:60]).lower()
        if key in seen:
            return
        seen.add(key)
        chosen.append(chunk)

    for w in windows(text):
        add(w)
    for s in sentences(text):
        if ANCHOR.search(s):
            add(s)

    out, total = [], 0
    for c in chosen:
        if total + len(c) > max_chars:
            break
        out.append(c)
        total += len(c)
    return "\n---\n".join(out)
