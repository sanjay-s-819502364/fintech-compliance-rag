# Eval conventions

Rules specific to `src/run_generation.py`, `src/generate_answer.py`, and
`eval/`. See root `CLAUDE.md` for the project-wide picture.

- Retrieval is **unfiltered by default**. Filtering by `expected_jurisdiction`
  (`--filter-from-key`) reads the answer key, so it exists only for a
  deliberate filtered-vs-unfiltered comparison — never make it the default,
  and never suggest it as a fix for cross-jurisdiction contamination (that
  would make `jurisdiction_specific` pass by construction and
  `cross_jurisdiction_bait` meaningless).
- Eval scoring is **claim-level**, not document-level: `check_numbers` and
  the grounding/relevance guardrail scores catch a fabricated number even
  when the right document was retrieved. Don't regress to "expected_doc
  present in results = pass."
- **Refusal is the safe default** when passages don't cover a question (see
  `SYSTEM_PROMPT` in `generate_answer.py`). Over-refusal is tracked as its
  own failure mode (`false_refusal_answerable` in the summary), not treated
  as harmless caution.
- Four outcomes per record, not pass/fail: `REFUSED_CORRECTLY`,
  `ANSWERED_UNANSWERABLE`, `REFUSED_ANSWERABLE`, `ANSWERED`. The first two
  matter most — `ANSWERED_UNANSWERABLE` is a fabrication, the failure mode
  the whole eval exists to catch.
- `REFUSAL_MARKERS` in `run_generation.py` is intentionally loose-matched
  (substring, not exact phrase) because the model paraphrases the refusal
  wording. If refusal detection looks wrong, check whether an answer that
  *contains* one of the markers mid-sentence is being miscounted, before
  tightening the match.
- Drift (`--repeats > 1`) is what turns a single run into a measurement
  rather than an anecdote — see the module docstring's note on Q11/Q30 being
  anecdotes found by luck, not method. Don't treat a single passing run as
  sufficient evidence for a claim about the pipeline's behavior.
