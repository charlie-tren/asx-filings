"""Pull the forward-looking passages out of each stored document, for hand
labelling. Not part of the collector: this exists to build the gold set.

The safe-harbour disclaimer is stripped aggressively because it is written out
of the exact vocabulary a forward-looking filter looks for, and on the first
pass it outranked the real guidance in several decks.
"""
import json, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FWD = re.compile(
    r"\b(expect\w*|outlook|guidance|FY\s?27|FY\s?2027|anticipat\w*|on track|"
    r"confiden\w*|forecast\w*|target\w*|well positioned|well placed|remain\w*|"
    r"continue\w*|momentum|first \d+ weeks|year to date|intend\w*|"
    r"start to FY|enter\w* FY|into FY)\b", re.I)
BOILER = re.compile(
    r"forward.{0,3}looking statement|not a recommendation|no representation|"
    r"disclaimer|indicative only|past performance|to the maximum extent|"
    r"can generally be identified|similar expressions|cannot be relied upon|"
    r"actual results may|no obligation to update|not a prospectus|"
    r"disclosure document|offering document|will not be lodged|"
    r"nothing contained in it|no assurance that|registered under the U\.S|"
    r"seek independent|financial product advice|before making any investment|"
    r"subject to change without notice|accepts no (?:liability|responsibility)",
    re.I)
NOISE = re.compile(r"^(note|source|comparable store growth|underlying|statutory|"
                   r"pcp|appendix|page \d|for personal use)", re.I)

def candidates(text: str, limit: int = 12) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+|\n(?=[•▪\-\*●])"
                     r"|[•▪●]", text)
    out, seen = [], set()
    for p in parts:
        p = " ".join(p.split())
        if not (45 < len(p) < 330) or BOILER.search(p) or NOISE.match(p):
            continue
        if not FWD.search(p):
            continue
        k = re.sub(r"\W", "", p[:50]).lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    # A mention of the NEXT year is worth more than a generic "momentum".
    out.sort(key=lambda s: (0 if re.search(r"FY\s?20?27|first \d+ weeks", s, re.I)
                            else 1))
    return out[:limit]

def main() -> None:
    ann = {json.loads(l)["document_key"]: json.loads(l)
           for l in (ROOT / "data/announcements.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    docs = [json.loads(l) for l in
            (ROOT / "data/documents.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = {}
    for d in sorted(docs, key=lambda r: (r["ticker"], -r["chars"])):
        text = (ROOT / d["text_path"]).read_text(encoding="utf-8")
        out[d["document_key"]] = {
            "ticker": d["ticker"],
            "headline": ann[d["document_key"]]["headline"],
            "announced": ann[d["document_key"]]["announced_at"][:10],
            "pages": d["pages"], "chars": d["chars"],
            "candidates": candidates(text),
        }
    (ROOT / "gold/candidates.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} documents, "
          f"{sum(len(v['candidates']) for v in out.values())} candidate passages")

if __name__ == "__main__":
    main()
