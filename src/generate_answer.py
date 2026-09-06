#!/usr/bin/env python3
"""
Answer a compliance question from the knowledge base, doing generation by hand.

RetrieveAndGenerate is not supported on managed knowledge bases, so this does
the same job in two explicit steps:

    1. retrieve()  - bedrock-agent-runtime, returns chunks
    2. converse()  - bedrock-runtime, answers from those chunks only

Doing it this way is not just a workaround. The prompt, the exact context the
model receives, and the citation format are all visible here rather than
assembled inside a managed call - which is what you need when a refusal test
fails and the question is whether the model ignored the passages or never had
them.

Usage:
    python generate_answer.py --kb-id 5H4SDBSUIF --managed \
        --question "What are the FCA requirements for complaint handling timeframes?"

    python generate_answer.py --kb-id 5H4SDBSUIF --managed --qid Q30
    python generate_answer.py --kb-id 5H4SDBSUIF --managed --qid Q11 --jurisdiction UK
    python generate_answer.py --kb-id 5H4SDBSUIF --managed --qid Q30 --show-context
"""

import argparse
import json
import os
import re
from pathlib import Path

import boto3

QUESTIONS_FILE = Path("eval-questions.json")

NOVA_LITE = "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"

# The grounding contract. Deliberately strict: in a compliance setting a
# fabricated obligation is worse than no answer, so refusal is the safe
# default rather than a fallback.
SYSTEM_PROMPT = """\
You answer questions about financial regulation using ONLY the numbered \
passages provided. You are used by compliance staff, where an invented or \
misattributed rule is a regulatory breach, not merely an error.

Rules:
1. Use only the passages. Do not use anything you know from training.
2. After every factual claim, cite the passage it came from as [1], [2], etc.
3. If the passages do not answer the question, say so plainly and stop. Do not \
substitute a related rule, a different jurisdiction's rule, or a general \
principle.
4. The passages are tagged with a jurisdiction. Never present one \
jurisdiction's requirement as another's. If passages from only one \
jurisdiction are present, say which one your answer covers.
5. If passages conflict, say so rather than choosing silently.

Preferred refusal wording when the passages do not cover the question:
"The provided sources do not address this."\
"""

USER_TEMPLATE = """\
Question: {question}

Passages:
{passages}

Answer the question using only the passages above."""


def jurisdiction_from_uri(uri: str) -> str:
    if "/uk-fca/" in uri:
        return "UK"
    if "/au-asic/" in uri:
        return "AU"
    if "/distractors/" in uri:
        return "DISTRACTOR"
    return "UNKNOWN"


def retrieve(client, kb_id: str, question: str, top_k: int,
             jurisdiction: str | None, managed: bool) -> list:
    """Fetch chunks. Same call shape as run_eval.py, kept in step with it."""
    search_config = {"numberOfResults": top_k}
    if jurisdiction:
        search_config["filter"] = {
            "equals": {"key": "jurisdiction", "value": jurisdiction}
        }

    key = "managedSearchConfiguration" if managed else "vectorSearchConfiguration"
    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": question},
        retrievalConfiguration={key: search_config},
    )

    chunks = []
    for item in response.get("retrievalResults", []):
        uri = item.get("location", {}).get("s3Location", {}).get("uri", "")
        chunks.append({
            "score": item.get("score"),
            "uri": uri,
            "filename": os.path.basename(uri),
            "jurisdiction": jurisdiction_from_uri(uri),
            "text": item.get("content", {}).get("text", ""),
        })
    return chunks


def format_passages(chunks: list) -> str:
    """Number the passages and tag each with jurisdiction and source.

    The model can only respect a jurisdiction boundary it can see, so the tag
    goes in the context rather than being left implicit in the filter.
    """
    blocks = []
    for i, c in enumerate(chunks, start=1):
        blocks.append(
            f"[{i}] jurisdiction={c['jurisdiction']} source={c['filename']}\n"
            f"{c['text']}"
        )
    return "\n\n".join(blocks)


def generate(client, model_arn: str, question: str, passages: str,
             guardrail_id: str | None, guardrail_version: str) -> dict:
    """Answer from the passages. Optionally routed through a guardrail."""
    kwargs = {
        "modelId": model_arn,
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [{
            "role": "user",
            "content": [{"text": USER_TEMPLATE.format(
                question=question, passages=passages)}],
        }],
        "inferenceConfig": {"temperature": 0.0, "maxTokens": 800},
    }
    if guardrail_id:
        kwargs["guardrailConfig"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": guardrail_version,
        }

    response = client.converse(**kwargs)
    return {
        "text": response["output"]["message"]["content"][0]["text"],
        "stop_reason": response.get("stopReason"),
        "usage": response.get("usage", {}),
    }


def load_question(qid: str) -> dict:
    data = json.loads(QUESTIONS_FILE.read_text())
    for q in data["questions"]:
        if q["id"] == qid:
            return q
    raise SystemExit(f"{qid} not found in {QUESTIONS_FILE}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kb-id", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--managed", action="store_true",
                   help="knowledge base is managed-type")
    p.add_argument("--question", default=None, help="ask a one-off question")
    p.add_argument("--qid", default=None,
                   help="use a question from eval-questions.json, e.g. Q30")
    p.add_argument("--jurisdiction", default=None, choices=["UK", "AU"],
                   help="apply a jurisdiction filter before retrieval")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--model", default=NOVA_LITE)
    p.add_argument("--guardrail-id", default=None,
                   help="attach a Bedrock guardrail to the generation call")
    p.add_argument("--guardrail-version", default="DRAFT")
    p.add_argument("--show-context", action="store_true",
                   help="print the full passage text sent to the model")
    args = p.parse_args()

    if not args.question and not args.qid:
        raise SystemExit("Give either --question or --qid")

    meta = None
    if args.qid:
        meta = load_question(args.qid)
        question = meta["question"]
    else:
        question = args.question

    agent = boto3.client("bedrock-agent-runtime", region_name=args.region)
    runtime = boto3.client("bedrock-runtime", region_name=args.region)

    chunks = retrieve(agent, args.kb_id, question, args.top_k,
                      args.jurisdiction, args.managed)

    print(f"QUESTION: {question}")
    if meta:
        print(f"category: {meta['category']}   expected_doc: {meta['expected_doc']}")
        if meta["expected_doc"] == "NONE":
            print("EXPECTED BEHAVIOUR: refuse - no answer exists in the corpus")
    print(f"filter: {args.jurisdiction or 'none'}   retrieved: {len(chunks)} chunks\n")

    if not chunks:
        print("No chunks retrieved. Nothing to ground an answer in.")
        return

    for i, c in enumerate(chunks, start=1):
        score = f"{c['score']:.3f}" if c["score"] is not None else "-"
        print(f"  [{i}] {score}  {c['jurisdiction']}  {c['filename']}")
    print()

    passages = format_passages(chunks)
    if args.show_context:
        print("-" * 72)
        print(passages)
        print("-" * 72 + "\n")

    result = generate(runtime, args.model, question, passages,
                      args.guardrail_id, args.guardrail_version)

    print("ANSWER:")
    print(result["text"])
    print()
    print(f"stop_reason: {result['stop_reason']}   tokens: {result['usage']}")

    if result["stop_reason"] == "guardrail_intervened":
        print("\nNOTE: the guardrail blocked or rewrote this response.")

    # A citation-free answer on an answerable question means the grounding
    # contract was ignored - worth flagging even before scoring is automated.
    # Match any bracketed index, not just [1]: the model often cites [2][3]
    # without ever using [1].
    cited = set(re.findall(r"\[(\d+)\]", result["text"]))
    if not cited and "do not address" not in result["text"]:
        print("\nWARNING: answer contains no citations and is not a refusal.")

    # Citations pointing past the number of passages supplied are fabricated
    # references - a distinct failure from citing the wrong passage.
    out_of_range = sorted(int(c) for c in cited if not 1 <= int(c) <= len(chunks))
    if out_of_range:
        print(f"\nWARNING: cites passages that were not supplied: {out_of_range}")


if __name__ == "__main__":
    main()
