# Parameter-Driven News Selection for Corporate Decision-Makers: An Experimental Plan

*Status: draft for approval. Scope: offline experiments only; no team module or contract is changed.*

## Abstract

We study how to select, from a weekly stream of ~2,000 Russian-language news stories, the small set that is decision-relevant for a corporate user described **only by structured login parameters**: role, industry (OKVED), region and company size/products. A pilot study (six free-text personas; Section 2) showed that (i) a ten-item input caps decision quality at ~5.3/10 against a fully informed reference regardless of retrieval quality or reader model, (ii) breadth-preserving inputs ("theme cards" plus headlines) raise this to 5.5, and (iii) the evaluation itself was biased and noisy. This plan tests three families of rankers — dense/sparse embeddings, simulated tag-and-graph traversal (the team's planned design), and hybrids of both — under a stricter evaluation design built from a review of 63 sources (`research/embeddings_research.md`, `research/evaluation_research.md`).

## 1. Problem statement

Given a profile *u* = (role, OKVED code, region, size band, product set) and a corpus *D* of news stories, produce an ordered, diverse selection *S(u) ⊂ D* and a decision memo *M(u)* such that *M(u)* captures as much as possible of the decision value available in *D* for *u*. Constraints from the case brief: interpretation must be traceable to sources, and production LLM calls must use the organiser-approved models within 500 ₽/day. In this study Claude Haiku stands in for the approved models (proof of concept); Claude Sonnet/Opus are used only for offline reference construction and judging.

## 2. Pilot findings that motivate this plan

| Observation (pilot, 6 personas) | Implication |
|---|---|
| Oracle top-10 → Haiku: 5.3; same cards → Sonnet: 5.3; whole set → Sonnet: 8.6 (leaky) | The bottleneck is input breadth, not ranking or reader model |
| bge-m3 > e5-large > e5-small (nDCG@10 0.73 / 0.67 / 0.61); cross-encoder with persona-as-query: 0.18 | Encoder choice matters; rerankers need item-shaped queries |
| Query–document cosine scores compressed into 0.80–0.83 (e5) | Style and genre dominate the similarity signal |
| Proxy "issue coverage" 1.00 vs judge 0.66 | Lexical presence ≠ use; need entailment-based nugget scoring |
| Same-family reference, judge and comparator; one judge run per arm | Circularity and noise of ±0.5 on a 10-point scale |

## 3. Research questions and hypotheses

- **RQ1 (profile → signal).** How should structured parameters be turned into a retrieval signal?
  *H1:* LLM-expanded "information needs" and hypothetical event cards (HyDE-style) beat raw label text and fixed templates on recall of indirectly relevant items.
- **RQ2 (document normalisation).** Does rewriting each story into a standardised *event card* before embedding improve retrieval across heterogeneous sources?
  *H2:* Event-card embeddings reduce genre/style noise (wider score spread, fewer opinion pieces in top-k) and raise nDCG and aspect coverage over headline+lead embeddings. Prior evidence: contextual enrichment cut retrieval failures by 35–67% [E: contextual retrieval].
- **RQ3 (encoder and scoring).** Which encoder and fusion scheme is best for Russian business news?
  *H3:* Hybrid dense + sparse (bge-m3 dense/sparse, lemmatised BM25) with reciprocal rank fusion and rank-based calibration beats any single signal.
- **RQ4 (graph vs embedding).** Does sector-graph traversal recover second-order relevance (e.g. customs rules → freight forwarders) better than embeddings?
  *H4:* Pure graph traversal has higher precision on direct sector matches but lower recall; a cross-breed (graph expansion of the profile + embedding ranking within reached sectors) dominates both. The review found no direct evidence that graphs beat dense retrieval for item selection, so H4 is genuinely open.
- **RQ5 (selection).** Does aspect-aware diversification (xQuAD/PM2 over profile needs) improve memo quality more than relevance-only ranking?
- **RQ6 (sensitivity).** Does the output change appropriately when exactly one profile parameter changes?
- **RQ7 (reader load).** How much input breadth can the reader use before quality falls?
  *H7:* Breadth helps up to the p14 format (~6–8k tokens); a two-pass read recovers stories the one-pass reader leaves unused.

## 4. Data

- **Corpus.** `news_full.csv`: 2,681 items, 20 outlets, one week (13–21 Oct 2026), merged into 2,008 stories (cosine ≥ 0.93 within 72 h).
- **Temporal split.** Development: stories before 21 Oct 14:00 UTC (60%, 1,200). Test: after it (40%, 808); 64% of the corpus is from 21 Oct, so a day cutoff was not possible. All hyperparameters, prompts and vocabularies are fixed on development data; test data is used once per configuration. This addresses the pilot's tuning-on-test risk and the brief's criterion of stable quality on unseen news.
- **Profiles.** 16 parameter-only profiles built by controlled variation, not free text:
  - 6 OKVED industries that the corpus covers (oil and gas extraction; retail incl. marketplaces; road freight and logistics; food manufacturing; financial services; IT);
  - 4 roles from the brief (owner/CEO, CFO, chief accountant, treasury head);
  - 3 regions (Moscow, Volga region, Siberia/Far East);
  - 2–3 size bands and 3 product sets (credit + leasing; FX + deposits; salary project only).
  The design includes *minimal pairs* (profiles differing in one parameter) to support RQ6.
- **Exclusions this round.** Alfa-Bank analytics PDFs (files not yet available); counterparty and payment links (thin data).

## 5. Methods (experimental arms)

All arms output the same structure (10 theme cards with related stories' leads + 40 one-line headlines, the pilot's best format), so differences come from ranking alone. Stage A is computed once per story; stage B once per distinct profile (cacheable); stage C per profile per day.

### 5.1 Document side (stage A)
- **A0 Raw:** headline + first 300 characters (pilot baseline).
- **A1 Event card:** one LLM pass per story producing a fixed-schema card: event, actors, geography, OKVED sections affected, event type (regulation / prices / sanctions / security / labour / …), impact mechanism, time horizon, genre (news / analysis / opinion), and **cause → effect pairs** at the sector × event-type level (e.g. "customs rule change → road freight: delays, costs"). The card is embedded instead of the lead. The genre field also allows down-weighting opinion pieces; the cause → effect pairs are the edge source for G2, G3 and X1, so no second extraction pass is needed.
- **A2 Raw + card:** two vectors per story, scored by max.

### 5.2 Profile side (stage B)
- **Q0 Label text:** OKVED name + role + region + products concatenated.
- **Q1 Templates:** fixed role × parameter templates (no LLM).
- **Q2 LLM needs:** one LLM call per parameter combination, producing ~20 information-need sentences.
- **Q3 Hypothetical event cards (HyDE):** the LLM writes ~15 example cards in the A1 schema that would matter to the profile; this matches card-to-card.
- **Q4 Aspect profile:** Q2 needs grouped into 5–8 aspects with weights, used by RQ5 diversification.

### 5.3 Rankers (stage C)
- **E1** bge-m3 dense; **E2** bge-m3 dense + sparse + BM25 with reciprocal rank fusion; **E3** E2 + cross-encoder rerank of the top 100 using *need sentences* (not persona text) as queries; **E4** encoder bake-off on the best configuration: bge-m3, USER-bge-m3, FRIDA, multilingual-e5-large-instruct, Qwen3-Embedding (licences checked; jina-v3 excluded as non-commercial).
- **G1 Tag graph + BFS:** stories and profile linked through shared card tags (sector, region, event type); 2-hop breadth-first traversal; score = sum of path weights.
- **G2 Sector graph:** fixed OKVED-section × section matrix, weights from the cause → effect pairs in the dev-period cards (A1); spreading activation from the profile's sector to neighbours, then to stories tagged with them.
- **G3 Causal graph + personalised PageRank:** the same extracted edges at the event-type × sector level, ranked by PageRank restarted at the profile's nodes.
- **X1 Cross-breed (graph expansion → embedding ranking):** G2 yields a weighted sector set *W(u)*; stories are ranked by embedding similarity to Q3 within each reached sector and weighted by *W(u)*. Each selected story carries its graph path as an explanation (traceability).
- **X2 Cross-breed (embedding candidates → graph re-scoring):** E2 top-300 candidates re-scored by G1 path weight; fusion by RRF.
- **Selection:** theme grouping by average-link clustering on card vectors (replacing single-link), then relevance-only or xQuAD/PM2 over Q4 aspects (RQ5).

### 5.4 Reader
Haiku (low effort) with the pilot's best prompt (v3: playbook, act-vs-monitor rule, direction checks), held fixed across arms.

### 5.5 Arm matrix (to bound cost)
A full factorial design is not affordable. Arms are run in three rounds, each fixing the winner of the previous one:
1. **Retrieval only** (no reader): A0/A1/A2 × Q0–Q3 × E1/E2, plus G1–G3, X1, X2. About 25 configurations, all scored offline against labels.
2. **Refinement:** best of round 1 × {E3 rerank, E4 encoders, relevance vs xQuAD}.
3. **End to end:** the top 4 configurations, plus the best pure-graph arm (G1–G3) and the best cross-breed (X1/X2) regardless of their retrieval rank, plus the pilot p14 baseline go through the reader and the judge panel. Graph arms are guaranteed a slot because their main advantage, a traceable "why" path per story, is only observable in the memo.
4. **Breadth ablation (RQ7):** on the best round-3 configuration, vary only what the reader sees:
   - B1: 10 cards, lead text only;
   - B2: B1 + related stories with leads;
   - B3: B2 + 40 one-line headlines (= p14 format);
   - B4: B3 read in two passes, first one line per card stating what happened and to whom, then the decisions.
   This tests whether added breadth helps or overloads the reader. The pilot hinted at overload: key stories were present (proxy coverage 1.00) but used only partly (judge 0.66).

## 6. Evaluation design

Informed by `research/evaluation_research.md`, the pilot's single-judge, single-reference design is replaced by:

1. **Relevance labels.** Sonnet screeners label every story for every profile (0–3) on the full corpus. Labels are produced twice with different prompt orderings; disagreements are adjudicated by a third pass. Inter-run agreement is reported as Cohen's κ.
2. **Nugget set per profile.** From the labelled set, an Opus pass extracts *nuggets*: atomic decision-relevant facts and decisions, each with supporting story IDs. Nuggets are de-duplicated across two independent extraction runs; only nuggets found by both are "vital".
3. **Retrieval metrics (round 1–2).** nDCG@10 on graded labels; **α-nDCG@10** with nuggets as aspects (penalises redundancy, the pilot's main failure); nugget recall@50 over all text the reader sees; share of opinion pieces in the top 10.
4. **Memo metrics (round 3).**
   - *Nugget coverage* judged by entailment (does the memo state the nugget's substance?), not by ID presence. This fixes the 100%-vs-66% proxy gap.
   - *Decision correctness* on a per-decision rubric (lever, direction, size, timing).
   - *Attribution precision:* every claim in the memo is checked against the cited card (ALCE-style); unsupported claims count as errors.
   - *Holistic score* (0–10) for comparability with the pilot.
   - The judge runs 3 times per memo with permuted section order; report mean ± standard error (expected SE ≈ 0.3).
5. **Comparator without leakage.** The whole-set baseline reads the raw corpus with no screener notes, so it is a fair upper bound.
6. **Sensitivity (RQ6).** Metamorphic tests on minimal pairs:
   - *region change:* top-10 overlap should fall for region-specific stories only;
   - *product change:* FX stories should rise when FX products are added;
   - *role change:* CFO and chief accountant should share macro items but differ on tax and reporting items;
   - *invariance:* an equivalent paraphrase of a parameter label should not change the output.
   Reported as pass rates.
7. **Cost.** LLM tokens per story (stage A), per profile combination (stage B) and per user per day (stage C), converted to the approved models' prices against the 500 ₽/day budget.

**Statistical analysis.** Profiles are the unit of analysis (n = 16). Arms are compared with paired Wilcoxon signed-rank tests on per-profile scores, with Holm correction across comparisons. Effects below one standard error of the judge are reported as ties.

## 7. Threats to validity

- **Same-family circularity.** Reference, labels and judge are Claude models, and the reader is Claude Haiku. Mitigations: entailment-based nuggets over holistic scores, attribution checks against source text, and a follow-up with approved open models as a second judge family.
- **Synthetic profiles.** Parameter combinations are hand-picked, not sampled from real users. Mitigation: minimal-pair design, and reporting per-profile results, not only means.
- **One week of news.** Temporal and topical generalisation is limited. The test split covers only two days.
- **Haiku as a stand-in.** Absolute scores will differ for the approved models; relative arm ordering is the claim.
- **Unverified figures in the reviews.** Several cited numbers come from abstracts or leaderboard snapshots and are flagged as such in the research files.

## 8. Procedure and budget

| Phase | Work | LLM cost (approx.) |
|---|---|---|
| P0 | Profile set, temporal split, event-card schema, tag vocabulary | — |
| P1 | Stage A cards for 2,008 stories (Haiku) | ~2.5M tokens |
| P2 | Labels (2 runs + adjudication) and nuggets for 16 profiles | ~8–10 Sonnet screeners ×2, 32 Opus nugget runs |
| P3 | Stage B expansions (Q2–Q4) per profile | ~50 Haiku calls |
| P4 | Round 1–2 retrieval experiments | CPU/GPU only (embeddings; V100 server optional) |
| P5 | Round 3: 7 configs × 16 profiles readers + 3 judge runs each | ~112 Haiku + ~336 judge calls (batched per arm) |
| P5b | Breadth ablation: 4 variants × 16 profiles (B3 reused from P5) | ~64 Haiku (B4 two calls) + ~144 judge calls |
| P6 | Sensitivity suite, write-up | ~30 Haiku runs |

Embeddings and caches are computed once and stored, so new arms reuse them. Background jobs run in parallel; each job writes to its own run directory to avoid races.

## 9. Deliverables

1. A results table per round (retrieval and end-to-end), with confidence intervals.
2. A recommended production configuration (stages A–C) with token cost per user per day.
3. An updated version of the interactive pipeline page.
4. A short Russian summary for `docs/`, proposed to the team before writing, per AGENTS.md.

## References

Literature is in `research/embeddings_research.md` (35 references: encoders and ruMTEB, contextual retrieval, doc2query, HyDE/query2doc, RRF, xQuAD/PM2, RankGPT, GraphRAG, Promptagator/GPL) and `research/evaluation_research.md` (28 references: UMBRELA, LLM relevance assessors, judge bias and panels, AutoNuggetizer, FActScore, ALCE, α-nDCG, metamorphic testing). Citations in this plan point to those files rather than being repeated here.

## 10. Addendum (2026-10-22): symmetric keys, query library, story bundles

Motivated by the round-3 and ablation results (FINDINGS.md): retrieval recall is near ceiling, top-10 precision is low (topic match ≠ decision impact), and the reader uses ~40 % of the vital nuggets in a 60-story context.

**S1. Symmetric keys (offline, labels only).** News key in a fixed template `<sector>: <event> → <effect, for whom>`; queries in the same template.
- K1: key rendered deterministically from the A1 card (no LLM). K2: key written by the LLM (only if K1 shows promise).
- L1: query-block library, keyed by role, OKVED section, region, product and role × OKVED; drafted once by an LLM, reviewed by a human; filled per user with no LLM.
- Compare {Q1+Q2 current, L1} × {A2 current, K1, K2} on nDCG@10, α-nDCG, P@10.

**S2. Story bundles (end to end).** Story–story graph over the full corpus (shared actors, cause→effect chains, time proximity, mid-band semantic similarity). Candidate bundles = connected sets of 1–3 stories within the user's top 30. Each bundle is judged by the reader model in a short separate call (insight yes/no, decision, direction, confidence, value). Accepted bundles, ordered by value, form the recommendations and the memo input.

**S3. Bundle pre-ranking (no LLM).** Pre-score from member relevance, edge type and strength, aspect coverage and novelty. All bundles are judged once, so variants are scored without extra calls: acceptance precision@k and correlation with judged value; then feed top-5/10/15 by pre-score vs all vs random-10, measuring nugget coverage, memo score and number of LLM calls.

**S4. Reader ceiling.** Sonnet reader on the xQuAD B3 packets (16 memos), judged as in round 3, with a cross-model judge check on a subset to control for self-preference.

Order: S1 (cheap) → S4 → S2 → S3. Each step is tested on one profile before the full run.
