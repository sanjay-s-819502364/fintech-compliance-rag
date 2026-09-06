#!/usr/bin/env python3
"""
Run generation across the whole eval set and count what actually happens.

Q11 and Q30 are two anecdotes. Q11 was only found because the correct answer
happened to be known - which is not a method. This runs every question, every
check, and reports distributions instead:

    refusal rate on unanswerable questions   (should be 4/4)
    false refusal on answerable questions    (over-refusal is also a failure)
    unsupported numbers per answer           (the check that caught Q11)
    contextual grounding score distribution  (the check that missed it)

Retrieval runs UNFILTERED by default. Filtering by expected_jurisdiction reads
the answer key, which makes every jurisdiction_specific question pass by
construction and makes cross_jurisdiction_bait meaningless. --filter-from-key
exists to produce the filtered comparison deliberately, not as the default.

Usage:
    python run_generation.py --kb-id 5H4SDBSUIF --managed \
        --guardrail-id io0otkm3wnye --out results/gen-all30.json

    python run_generation.py --kb-id 5H4SDBSUIF --managed --repeats 3 \
        --guardrail-id io0otkm3wnye --out results/gen-drift.json

    python run_generation.py --kb-id 5H4SDBSUIF --managed --limit 3 --dry-run
    python run_generation.py --from-results results/gen-all30.json
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from generate_answer import (
    NOVA_LITE,
    QUESTIONS_FILE,
    check_grounding,
    check_numbers,
    format_passages,
    generate,
    retrieve,
)

# Questions whose correct behaviour is to refuse.
UNANSWERABLE = "unanswerable"

# Matched against the refusal wording the system prompt asks for. Kept loose
# on purpose: the model paraphrases ("do not address", "do not contain"), and
# a refusal counted as an answer would silently inflate the fabrication rate.
REFUSAL_MARKERS = (
    "do not address",
    "does not address",
    "do not contain",
    "does not contain",
    "do not provide",
    "not addressed in the provided",
)


def is_refusal(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in REFUSAL_MARKERS)


def call_with_retry(fn, *args, attempts: int = 5, base_sleep: float = 2.0,
                    **kwargs):
    """Retry on throttling. A 30-question x 3-repeat run hits limits."""
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - botocore types not imported
            name = type(exc).__name__
            throttled = "Throttl" in name or "TooManyRequests" in name \
                or "Throttl" in str(exc)
            if not throttled or i == attempts - 1:
                raise
            wait = base_sleep * (2 ** i)
            print(f"    throttled, retrying in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)


def run_one(agent, runtime, q: dict, args) -> dict:
    """One question, one run. Returns a record; never raises on model output."""
    question = q["question"]
    jurisdiction = None
    if args.filter_from_key:
        expected = q.get("expected_jurisdiction")
        if expected in ("UK", "AU"):
            jurisdiction = expected

    chunks = call_with_retry(retrieve, agent, args.kb_id, question,
                             args.top_k, jurisdiction, args.managed)

    record = {
        "id": q["id"],
        "category": q["category"],
        "verified": q.get("verified"),
        "expected_doc": q["expected_doc"],
        "expected_jurisdiction": q.get("expected_jurisdiction"),
        "filter_applied": jurisdiction,
        "retrieved": [
            {"score": c["score"], "filename": c["filename"],
             "jurisdiction": c["jurisdiction"]}
            for c in chunks
        ],
    }

    if not chunks:
        # No context reached the model, so any answer would be ungrounded by
        # construction. Recorded distinctly rather than scored as a refusal.
        record["outcome"] = "NO_CHUNKS"
        return record

    passages = format_passages(chunks)
    result = call_with_retry(generate, runtime, args.model, question, passages,
                             None, args.guardrail_version)
    answer = result["text"]

    nums = check_numbers(answer, passages, question)
    refused = is_refusal(answer)
    unanswerable = q["category"] == UNANSWERABLE

    record.update({
        "answer": answer,
        "stop_reason": result["stop_reason"],
        "tokens": result["usage"],
        "refused": refused,
        "numbers_checked": nums["checked"],
        "unsupported": [raw for _, raw in nums["unsupported"]],
        "echoed_from_question": [raw for _, raw in nums["echoed_from_question"]],
    })

    # Four outcomes, because over-refusal is a failure too. A system that
    # refuses everything scores a perfect refusal rate and is useless.
    if unanswerable:
        record["outcome"] = "REFUSED_CORRECTLY" if refused else "ANSWERED_UNANSWERABLE"
    else:
        record["outcome"] = "REFUSED_ANSWERABLE" if refused else "ANSWERED"

    if args.guardrail_id:
        g = call_with_retry(check_grounding, runtime, args.guardrail_id,
                            args.guardrail_version, passages, question, answer)
        record["guardrail"] = g
        for s in g["scores"]:
            if s["type"] == "GROUNDING":
                record["grounding_score"] = s["score"]
            if s["type"] == "RELEVANCE":
                record["relevance_score"] = s["score"]

    return record


def summarise(records: list) -> dict:
    """Aggregate. Repeats are kept as separate records and counted as runs."""
    by_outcome = {}
    for r in records:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1

    answerable = [r for r in records if r["category"] != UNANSWERABLE
                  and "answer" in r]
    unanswerable = [r for r in records if r["category"] == UNANSWERABLE
                    and "answer" in r]

    with_unsupported = [r for r in answerable if r["unsupported"]]

    # Values are collected across every answered record. An unanswerable
    # question that gets answered with an invented figure is the worst case in
    # the set, and scoping this to answerable questions would hide it.
    answered = [r for r in records if "answer" in r]
    all_unsupported = sorted({v for r in answered for v in r["unsupported"]})

    grounding = [r["grounding_score"] for r in records
                 if isinstance(r.get("grounding_score"), (int, float))]

    # The Q11 case in aggregate: answers carrying an unsupported number that
    # the grounding filter passed anyway. If this is non-zero the deterministic
    # check is not redundant with the guardrail.
    missed_by_guardrail = [
        r for r in answered if r["unsupported"]
        if r.get("guardrail", {}).get("action") == "NONE"
    ]

    summary = {
        "runs": len(records),
        "questions": len({r["id"] for r in records}),
        "outcomes": by_outcome,
        "refusal_rate_unanswerable": f"{sum(r['refused'] for r in unanswerable)}"
                                     f"/{len(unanswerable)}",
        "false_refusal_answerable": f"{sum(r['refused'] for r in answerable)}"
                                    f"/{len(answerable)}",
        "answers_with_unsupported_numbers": f"{len(with_unsupported)}"
                                            f"/{len(answerable)}",
        "unsupported_values": all_unsupported,
        "unsupported_passed_by_guardrail": len(missed_by_guardrail),
    }

    if grounding:
        summary["grounding"] = {
            "n": len(grounding),
            "min": round(min(grounding), 3),
            "max": round(max(grounding), 3),
            "mean": round(statistics.mean(grounding), 3),
        }

    # Drift across repeats of the same question, which is what decides whether
    # a single run is a measurement or an anecdote.
    drift = {}
    for qid in {r["id"] for r in records}:
        runs = [r for r in records if r["id"] == qid and "answer" in r]
        if len(runs) < 2:
            continue
        entry = {"outcomes": sorted({r["outcome"] for r in runs}),
                 "distinct_answers": len({r["answer"] for r in runs})}
        scores = [r["grounding_score"] for r in runs
                  if isinstance(r.get("grounding_score"), (int, float))]
        if len(scores) >= 2:
            entry["grounding_spread"] = round(max(scores) - min(scores), 3)
        unsup = {tuple(sorted(r["unsupported"])) for r in runs}
        entry["unsupported_stable"] = len(unsup) == 1
        drift[qid] = entry
    if drift:
        summary["drift"] = drift

    return summary


def print_summary(summary: dict) -> None:
    print("\n" + "=" * 72)
    print(f"{summary['runs']} run(s) over {summary['questions']} question(s)")
    print("-" * 72)
    for k, v in summary["outcomes"].items():
        print(f"  {k:<24} {v}")
    print("-" * 72)
    print(f"  refusal on unanswerable      {summary['refusal_rate_unanswerable']}")
    print(f"  false refusal on answerable  {summary['false_refusal_answerable']}")
    print(f"  answers w/ unsupported nums  "
          f"{summary['answers_with_unsupported_numbers']}")
    if summary["unsupported_values"]:
        print(f"  unsupported values           {summary['unsupported_values']}")
    if "grounding" in summary:
        g = summary["grounding"]
        print(f"  grounding score              min {g['min']}  "
              f"mean {g['mean']}  max {g['max']}  (n={g['n']})")
        print(f"  unsupported yet passed       "
              f"{summary['unsupported_passed_by_guardrail']}")
    if "drift" in summary:
        print("-" * 72)
        print("  drift across repeats (qid: distinct answers / grounding spread)")
        for qid, d in sorted(summary["drift"].items()):
            spread = d.get("grounding_spread")
            spread_str = f"{spread:.3f}" if spread is not None else "-"
            flag = "" if d["unsupported_stable"] else "  UNSTABLE unsupported set"
            print(f"    {qid}  {d['distinct_answers']} answer(s)  "
                  f"spread {spread_str}{flag}")
    print("=" * 72)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kb-id")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--managed", action="store_true")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--model", default=NOVA_LITE)
    p.add_argument("--guardrail-id", default=None,
                   help="score each answer with apply_guardrail")
    p.add_argument("--guardrail-version", default="DRAFT")
    p.add_argument("--filter-from-key", action="store_true",
                   help="apply expected_jurisdiction as a retrieval filter; "
                        "reads the answer key, so use only for the deliberate "
                        "filtered comparison")
    p.add_argument("--repeats", type=int, default=1,
                   help="runs per question, for temperature-0 drift")
    p.add_argument("--limit", type=int, default=None,
                   help="first N questions only, for a cheap smoke test")
    p.add_argument("--category", default=None)
    p.add_argument("--sleep", type=float, default=0.0,
                   help="seconds between calls")
    p.add_argument("--out", default=None, help="write results JSON here")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would run, make no AWS calls")
    p.add_argument("--from-results", default=None,
                   help="re-aggregate an existing results file and exit")
    args = p.parse_args()

    if args.from_results:
        data = json.loads(Path(args.from_results).read_text())
        print_summary(summarise(data["records"]))
        return

    questions = json.loads(QUESTIONS_FILE.read_text())["questions"]
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.limit:
        questions = questions[:args.limit]

    if args.dry_run:
        print(f"{len(questions)} question(s) x {args.repeats} repeat(s) = "
              f"{len(questions) * args.repeats} generation call(s)")
        if args.guardrail_id:
            print(f"plus {len(questions) * args.repeats} apply_guardrail call(s)")
        print(f"filter: {'expected_jurisdiction' if args.filter_from_key else 'none'}")
        for q in questions:
            print(f"  {q['id']}  [{q['category']}]  {q['question'][:60]}")
        return

    if not args.kb_id:
        raise SystemExit("--kb-id is required unless --dry-run or --from-results")

    import boto3
    agent = boto3.client("bedrock-agent-runtime", region_name=args.region)
    runtime = boto3.client("bedrock-runtime", region_name=args.region)

    records = []
    total = len(questions) * args.repeats
    n = 0
    for rep in range(1, args.repeats + 1):
        for q in questions:
            n += 1
            print(f"[{n}/{total}] {q['id']} run {rep}", flush=True)
            try:
                rec = run_one(agent, runtime, q, args)
            except Exception as exc:  # noqa: BLE001
                # One bad question should not lose the other 29.
                print(f"    ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
                rec = {"id": q["id"], "category": q["category"],
                       "expected_doc": q["expected_doc"],
                       "outcome": "ERROR", "error": str(exc)}
            rec["repeat"] = rep
            records.append(rec)
            marker = ""
            if rec.get("unsupported"):
                marker = f"   UNSUPPORTED {rec['unsupported']}"
            print(f"    {rec['outcome']}{marker}")
            if args.sleep:
                time.sleep(args.sleep)

    summary = summarise(records)
    print_summary(summary)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "config": {
                "kb_id": args.kb_id, "managed": args.managed,
                "top_k": args.top_k, "model": args.model,
                "guardrail_id": args.guardrail_id,
                "filter_from_key": args.filter_from_key,
                "repeats": args.repeats,
            },
            "summary": summary,
            "records": records,
        }, indent=2))
        print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
