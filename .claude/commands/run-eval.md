---
description: Run the 30-question eval set against the deployed Bedrock KB/agent
---

Run `src/run_generation.py` and summarize the result for the user.

1. Check `.env` for `BEDROCK_KNOWLEDGE_BASE_ID` — if missing, stop and ask for
   `--kb-id` instead of guessing one.
2. Default invocation (retrieval unfiltered — that's the intended default,
   not something to "fix"):
   ```bash
   python src/run_generation.py --kb-id <id> --managed \
       --out eval/results/gen-$(date +%s).json $ARGUMENTS
   ```
   Pass `$ARGUMENTS` through verbatim so the caller can add `--limit`,
   `--category`, `--repeats`, `--guardrail-id`, `--filter-from-key`, etc.
3. After it finishes, report the printed summary block (outcomes, refusal
   rates, unsupported numbers, grounding stats, drift) — don't just say "done."
4. If `outcomes` shows any `ANSWERED_UNANSWERABLE` or a nonzero
   `unsupported_passed_by_guardrail`, call these out explicitly — they're the
   two failure modes this eval exists to catch.
