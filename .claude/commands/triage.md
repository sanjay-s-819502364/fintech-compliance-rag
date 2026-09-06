---
description: Triage unverified eval questions in a results file against what retrieval actually returned
---

Argument (`$ARGUMENTS`): a results file path, e.g. `eval/results/gen-all30-rescored.json`.
If omitted, use the most recently modified file under `eval/results/`.

Run:
```bash
python src/triage_eval.py $ARGUMENTS
```

For each question printed, decide one of: **keep** the expected_doc as-is,
**fix** expected_doc (retrieval was right, the answer key was wrong),
**rewrite** the question (ambiguous or unfair), or **drop** it. Do not
silently "fix" the answer key yourself — the point of this command is to
surface mismatches for a human decision, per the tool's own docstring: "A
mismatch means the key is wrong, not that the pipeline failed" refers to the
key needing review, not an automatic edit.

If the user wants a narrower pass, suggest `--category <name>` (e.g.
`cross_jurisdiction_bait`, the category most likely to surface a real
contamination regression) or `--all` to re-check already-verified questions.
