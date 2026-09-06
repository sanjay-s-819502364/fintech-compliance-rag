# Fintech Compliance KB — Pass 1 Baseline Findings

*Multi-jurisdictional regulatory RAG system on AWS Bedrock. Baseline measurements before any tuning.*

---

## Architecture as built

| Component | Choice | Notes |
|---|---|---|
| Corpus | 16 PDFs, ~1,055 pages | UK FCA (~572pp) + AU ASIC (~325pp) |
| Storage | S3, jurisdiction-prefixed | `corpus/uk-fca/`, `corpus/au-asic/` |
| Parser | Bedrock Data Automation | Extracts text + describes images/tables |
| Chunking | Fixed, 300 tokens | Default; Pass 1 will vary this |
| Embeddings | Titan Text Embeddings V2 | 1024 dimensions |
| Vector store | Aurora PostgreSQL Serverless v2 + pgvector | min 0 / max 1 ACU |
| Index | HNSW (`vector_cosine_ops`) + GIN on text and jsonb | |
| Generation | Nova Lite / Nova Micro | |

**Ingestion result:** 16 scanned, 16 indexed, 0 failed. ~3,000 chunks.

---

## Build obstacles worth remembering

Each of these cost real time and each is a genuine production-relevant lesson.

1. **Free Tier restricts Aurora creation** to express configuration only — full manual configuration is blocked with `FreeTierRestrictionError`.
2. **Data API would not enable** via `modify-db-cluster --enable-http-endpoint`; the call succeeded silently but the flag never flipped. The dedicated `rds enable-http-endpoint` command worked immediately.
3. **CLI version mattered** — `--with-express-configuration` didn't exist in 2.31.35. Required upgrade to 2.36.x.
4. **Managed Knowledge Base ≠ vector Knowledge Base.** The Managed type (`"type": "MANAGED"`) provisions storage internally and removes all vector-store, embedding, and chunking choices. Not appropriate when those decisions are the point.
5. **Aurora as a vector store requires manual indexes Bedrock does not create.** KB creation fails with explicit errors until you add:
   - `CREATE INDEX ON ... USING gin (to_tsvector('simple', chunks));`
   - `CREATE INDEX ON ... USING gin (custom_metadata);`
6. **Multimodal storage destination rejects sub-folders** — bucket root only.
7. **Nova Micro as a Foundation Models parser fails on every document.** Document parsing is a vision task; Nova Micro is text-only. Symptom was a generic "internal error" with 16/16 failures and no partial success. Model capability must match task modality.
8. **Auto-pause at 300s interferes with long ingestion.** Parse and embed phases don't touch the database, so the cluster can pause mid-job. Raise `SecondsUntilAutoPause` during ingestion, lower it after.
9. **Changing a data source URI clears previously indexed rows.** Sync reconciles rather than appends — convenient for re-running chunking experiments, surprising the first time.

---

## Baseline retrieval measurements

### Test 1 — jurisdiction stated explicitly in the query

**Query:** *"What are the FCA requirements for complaint handling timeframes?"*

| Rank | Source | Type | Score |
|---|---|---|---|
| 1 | FCA-related | image | 0.54 |
| 2 | — | image | 0.53 |
| 3 | RG 267 (AU/ASIC) | text | — |
| 4 | RG 267 (AU/ASIC) | text | — |
| 5 | RG 267 (AU/ASIC) | text | — |

**Findings:**

- **Explicit jurisdiction in the query does not steer retrieval.** Naming "FCA" returned majority Australian content. The only UK-associated hit was an image chunk, not the Approach Document's complaints prose.
- **Semantic drift to adjacent-but-wrong obligations.** RG 267 governs ASIC's *oversight of AFCA*, not what a firm must do when a customer complains (that's RG 271). The embeddings matched vocabulary — "complaints," "time limits" — rather than the obligation itself.
- **Scores are uniformly weak (0.53–0.54)** on a topic the corpus covers well in both jurisdictions. Suggests relevant passages may be fragmenting across chunk boundaries at 300 tokens.
- **Image-derived chunks outrank substantive prose.** Possibly because image descriptions are short and dense, scoring well on cosine similarity without carrying much retrievable content.

### Test 2 — jurisdiction omitted

**Query:** *"What are the timeframes for responding to a customer complaint?"*

Returned 2 chunks, both RG 271 (AU), scores 0.54 (image) and 0.53 (text). **Zero UK chunks**, despite the FCA Approach Document containing a full complaints chapter with different requirements.

---

## Root cause hypothesis

"FCA" is a small share of the token content in a query otherwise dominated by topic — complaints, timeframes, customer response. The embedding is driven by that topic. Regulatory guidance across jurisdictions uses near-identical vocabulary for the same subject matter, so chunks about complaints cluster together in vector space regardless of country.

**This is not fixable by better embeddings or better prompts.** Jurisdiction is a hard constraint, not a soft preference. It needs a filter applied *before* similarity search runs, not a hope that the vector captures it.

---

## Next actions

**Fix the contamination**
- [ ] Add `.metadata.json` sidecars tagging jurisdiction, regulator, doc_type, doc_id, status
- [ ] Re-ingest and confirm metadata lands in `custom_metadata`
- [ ] Apply metadata filtering at retrieval; re-run both tests
- [ ] Measure: cross-jurisdiction contamination rate before vs after

**Investigate weak scores**
- [ ] Re-ingest at 300 / 1000 tokens and hierarchical, holding queries constant
- [ ] Determine whether low scores are a chunking artifact

**Investigate image chunk ranking**
- [ ] Inspect what the high-ranking image chunks actually contain
- [ ] Decide whether to down-weight or exclude them

**Build the eval set**
- [ ] 30–50 questions with known answers, spanning: single-document lookups, jurisdiction-specific, cross-jurisdiction bait, and unanswerable
- [ ] Score baseline before any further changes
