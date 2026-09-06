#!/usr/bin/env python3
"""
Print unverified eval questions next to what retrieval actually returned, so
the answer key can be checked without opening every PDF.

The question to hold in mind for each one: do these chunks answer the question,
and do they come from the document named as expected_doc? A mismatch means the
key is wrong, not that the pipeline failed.

Usage:
    python triage_eval.py results/all30-filtered.json
    python triage_eval.py results/all30-filtered.json --all
    python triage_eval.py results/all30-filtered.json --category cross_jurisdiction_bait
    python triage_eval.py results/all30-filtered.json --chars 400
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("results_file")
    p.add_argument("--all", action="store_true",
                   help="include questions already marked verified")
    p.add_argument("--category", default=None,
                   help="only this category, e.g. cross_jurisdiction_bait")
    p.add_argument("--top", type=int, default=3,
                   help="how many retrieved chunks to show (default 3)")
    p.add_argument("--chars", type=int, default=300,
                   help="snippet characters to print (default 300)")
    args = p.parse_args()

    data = json.loads(Path(args.results_file).read_text())
    records = data["records"]

    shown = 0
    for r in records:
        if "score" not in r:
            continue
        if not args.all and r.get("verified"):
            continue
        if args.category and r.get("category") != args.category:
            continue

        shown += 1
        print("=" * 72)
        print(f"{r['id']}  [{r['category']}]  outcome: {r['score']['outcome']}")
        print(f"Q: {r['question']}")
        print(f"expected_doc: {r['expected_doc']}"
              f"   filter_applied: {r['filter_applied']}")

        docs = [x["filename"] for x in r["results"]]
        print(f"returned:     {docs}")
        if r["expected_doc"] not in ("NONE", "AMBIGUOUS", "MULTIPLE"):
            print("MISMATCH: expected_doc not in results"
                  if r["expected_doc"] not in docs else "expected_doc present")
        print()

        for i, x in enumerate(r["results"][:args.top], start=1):
            score = x.get("score")
            score_str = f"{score:.3f}" if score is not None else "-"
            print(f"  [{i}] {score_str}  {x['jurisdiction']}  {x['filename']}")
            print(f"      {x['snippet'][:args.chars]}")
            print()

    print("=" * 72)
    print(f"{shown} question(s) shown.")
    print("\nFor each: keep / fix expected_doc / rewrite / drop.")


if __name__ == "__main__":
    main()
