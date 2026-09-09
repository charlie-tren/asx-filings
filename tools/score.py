"""Score the extraction layer against the hand-labelled gold set.

Reports CATCHES AND FALSE POSITIVES PER CLASS, never one accuracy figure. One
number hides the only thing worth knowing: the majority-class baseline for
stance is 58%, so a model that answers "positive" every time already scores
better than a coin toss and has demonstrated nothing.

Scored PER MODEL. A corpus written by two models is two calibrations, and
Ghostwriters shipped a front page ranking both in one column because a quota
fallback was never recorded.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import common

GOLD = common.ROOT / "gold"
FIELDS = ("next_period_guide", "stance", "horizon")


def load_gold() -> dict[str, dict]:
    out = {}
    for name in ("labels.json", "labels_negative.json"):
        path = GOLD / name
        if not path.exists():
            continue
        for d in json.loads(path.read_text(encoding="utf-8"))["documents"]:
            d["half"] = "negatives" if "negative" in name else "results"
            out[d["document_key"]] = d
    return out


def confusion(pairs: list[tuple[str, str]]) -> str:
    """Per class: how many were caught, and how many things wrongly claimed it."""
    truth = Counter(t for t, _ in pairs)
    got = Counter(p for _, p in pairs)
    hit = Counter(t for t, p in pairs if t == p)
    rows = []
    for cls in sorted(truth | got):
        n = truth[cls]
        caught = hit[cls]
        false_pos = got[cls] - caught
        rows.append(f"    {cls:22} n={n:<3} caught {caught}/{n:<3} "
                    f"false positives {false_pos}")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="score only this model")
    args = ap.parse_args()

    gold = load_gold()
    feats = common.read_ledger("features")
    if args.model:
        feats = [f for f in feats if f["model"] == args.model]
    if not feats:
        print("no features extracted yet", file=sys.stderr)
        return 1

    by_model = defaultdict(list)
    for f in feats:
        if f["document_key"] in gold:
            by_model[(f["provider"], f["model"], f["prompt_version"])].append(f)

    if not by_model:
        print("features exist but none are for gold-set documents", file=sys.stderr)
        return 1

    for (provider, model, pv), rows in sorted(by_model.items()):
        rows = {r["document_key"]: r for r in rows}.values()   # last wins
        print(f"\n{'=' * 70}\n{provider}/{model}  prompt v{pv}\n"
              f"{len(rows)} of {len(gold)} gold documents extracted\n{'=' * 70}")
        halves = Counter(gold[r["document_key"]]["half"] for r in rows)
        print(f"  from: {dict(halves)}")

        for field in FIELDS:
            pairs = [(gold[r["document_key"]][field], r[field]) for r in rows]
            agree = sum(1 for t, p in pairs if t == p)
            base = Counter(t for t, _ in pairs).most_common(1)[0]
            print(f"\n  {field}: {agree}/{len(pairs)} agree "
                  f"({agree / len(pairs):.0%}), majority-class baseline "
                  f"{base[1] / len(pairs):.0%} (always '{base[0]}')")
            print(confusion(pairs))

        # The error that costs money is not a miss, it is a SIGN FLIP: calling a
        # negative document positive, or the reverse. Counted separately, always.
        flips = [(gold[r["document_key"]]["ticker"],
                  gold[r["document_key"]]["stance"], r["stance"])
                 for r in rows
                 if {gold[r["document_key"]]["stance"], r["stance"]}
                 == {"positive", "negative"}]
        print(f"\n  SIGN FLIPS (positive<->negative): {len(flips)}")
        for tk, t, p in flips:
            print(f"    {tk}: gold {t} -> model {p}")

        # Where the model and the label disagree at all, worth reading by hand.
        dis = [(gold[r["document_key"]]["ticker"], f,
                gold[r["document_key"]][f], r[f])
               for r in rows for f in FIELDS
               if gold[r["document_key"]][f] != r[f]]
        print(f"\n  all disagreements: {len(dis)}")
        for tk, f, t, p in dis[:25]:
            print(f"    {tk:5} {f:20} gold={t:22} model={p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
