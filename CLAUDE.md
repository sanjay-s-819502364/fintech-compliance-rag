# fintech-compliance-rag

Multi-jurisdictional regulatory RAG system (UK FCA + AU ASIC) on AWS Bedrock.
Full context: [README.md](README.md) (what the project found), [docs/baseline-findings.md](docs/baseline-findings.md)
(measurements behind that finding), [SOURCES.md](SOURCES.md) (where the corpus PDFs come from).

## Core finding — don't relitigate this

Naive semantic retrieval mixes jurisdictions because regulatory text uses
near-identical vocabulary across regimes. Naming a jurisdiction in the query
text does not steer retrieval. The fix is a hard metadata filter applied
*before* similarity search (`jurisdiction` in `custom_metadata`), not better
embeddings or prompting. Treat this as settled unless new measurements say
otherwise — see docs/baseline-findings.md before proposing a prompt-only or
embedding-only fix to cross-jurisdiction contamination.

## Corpus is not in this repo

`corpus/` is gitignored — PDFs are not committed (FCA/ASIC licensing — see
SOURCES.md). Don't assume the corpus is present; scripts that need it
(`generate_metadata.py`) fail loudly with `SystemExit` if `corpus/` is
missing, which is correct behavior, not a bug to work around.

## Pipeline order

```
corpus/<jurisdiction>/*.pdf
  → generate_metadata.py     (writes .metadata.json sidecars: jurisdiction, regulator, doc_id, doc_type, status, topic)
  → aws s3 sync + KB sync    (manual — see script's printed "Next" steps)
  → run_generation.py        (retrieve + generate over eval/eval-questions.json, writes eval/results/*.json)
  → triage_eval.py           (human-in-the-loop check of retrieval vs answer key)
```

`generate_answer.py` is the single-question debugging tool underneath
`run_generation.py` — same `retrieve`/`generate` functions, imported not
duplicated. When retrieval or grounding looks wrong, reproduce with
`generate_answer.py --qid <id> --show-context` before changing the pipeline.

## Conventions this codebase already follows

- Comments in `src/` explain *why* a check exists (often tied to a specific
  eval question, e.g. Q11) — match that style rather than describing what the
  code does.
- New DOC_INFO entries in `generate_metadata.py` need `doc_id`, `doc_type`,
  `status`, `topic` (a list) — run `--check` after adding corpus files to
  confirm nothing fell back to `UNKNOWN`.

Eval-specific conventions (retrieval filtering defaults, scoring granularity,
refusal handling): @.claude/rules/eval-conventions.md

## Setup for local runs

```bash
pip install -r requirements.txt
cp .env.example .env   # AWS_REGION, BEDROCK_AGENT_ID, BEDROCK_KNOWLEDGE_BASE_ID
```

AWS credentials come from the standard boto3 chain — never hardcode them.
