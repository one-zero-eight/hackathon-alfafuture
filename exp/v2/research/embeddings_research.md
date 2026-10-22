# Dense and Sparse Embeddings for Personalized Business-News Selection in Russian: A Literature and Practice Review

Date: 2026-10-22. Scope: users described only by structured login attributes (role, OKVED, region, company size, bank products); Russian multi-source news stream (~2-3k items/week); baseline = bge-m3 dense on headline+300 chars, ~20 hand-written profile queries, mean-top-3 cosine + keyword bonus, single-link theme dedup, LLM over top-10 cards.

Method note: evidence was gathered through web search and abstract/page fetches. Numbers marked "(abstract)" come from the cited abstract; "(snippet)" from search-result text only; "(prior knowledge)" means the item is classical and was not re-fetched in this session. No Russian news-specific personalization benchmark was found; transfer from generic IR results is by analogy and should be validated on a small in-house labelled set.

---

## 1. Russian / multilingual embedding models

**What matters.** For retrieval-like matching of short profile queries to news, the choice is among (a) bge-m3 (568M, dense + learned sparse + ColBERT-style multivector, 8192 tokens) [5], (b) its Russian-tuned derivative USER-bge-m3 (359M-class Russian-only vocabulary-trimmed model, 1024-d, 8192 tokens) [4], (c) FRIDA (FRED-T5 encoder, CLS pooling, prompt-prefix based, from the ruMTEB authors) [3], (d) GigaEmbeddings (GigaChat-3B decoder, bidirectional attention, latent-attention pooling, 25% layers pruned; 69.1 avg ruMTEB) [2], (e) multilingual-e5-large(-instruct) [6], (f) Qwen3-Embedding 0.6B/4B/8B (instruction-aware; MTEB-multilingual 64.33/69.45/70.58) [7], (g) jina-embeddings-v3 (570M, task-specific LoRA adapters, Matryoshka down to 32-d; CC BY-NC-SA licence) [8].

**Evidence.**
- ruMTEB (23 tasks, 7 categories) [1]: bge-m3 avg 60.8 (retrieval 74.8, reranking 69.7), mE5-large 60.4 (retrieval 74.0), ru-en-RoSBERTa 60.4 (retrieval 66.5). On RiaNewsRetrieval (headline-to-article retrieval, the closest public proxy to our domain) nDCG@10: bge-m3 83.0, mE5-large 80.7, RoSBERTa 78.9 [1].
- Leaderboard snapshot (snippet, retrieval subset): FRIDA avg 77.03 (RiaNews 86.82, RuBQ 72.39, MIRACL-ru 71.88) ranks first; USER-bge-m3 73.63 ranks 7th [3][4]. GigaEmbeddings claims top overall ruMTEB (69.1 on the newer aggregation, which is not comparable to the 60.8 above) [2]. Leaderboard numbers vary by task set and date and should be re-run locally.
- Instruction handling: mE5-large-instruct slightly lowers MIRACL nDCG@10 versus mE5-large (65.7 vs 66.5) but raises R@100 (94.6) [6], i.e. instructions help recall of a broader pool more than precision. Promptriever shows retrievers trained on ~500k instance-level instructions gain +14.3 p-MRR on FollowIR and +12.9 Robustness@10 on InstructIR, plus +1.4 BEIR avg from prompt tuning [10]. E5-Mistral/LLM embedders are trained with a task instruction on the query side only [9]. bge-m3 itself has no instruction convention, so it needs the query to carry the whole intent.
- bge-m3 self-distillation ablation (MIRACL dev nDCG@10): dense 69.2, sparse 53.9, multivector 70.5; combining modes is the intended use [5].

**Cost.** Switching the encoder is cheap: ~3k docs/week, a 0.5-8B model embeds the entire weekly stream in minutes on one GPU. Qwen3-8B and GigaEmbeddings need ~16GB+; bge-m3/FRIDA/USER run on CPU/modest GPU.

**Application.** Keep bge-m3 as the sparse+multivector provider (free lexical signal, see 4) and benchmark FRIDA, USER-bge-m3, Qwen3-Embedding-4B/8B and mE5-large-instruct on a 200-300 pair in-house label set before committing. Expect an encoder swap alone to move nDCG by a few points; it will not fix compressed score range (that is a calibration problem, see 4).

---

## 2. Document-side normalization

**2.1 LLM "event cards" instead of raw headline+lead.** An LLM rewrites each item into a fixed schema (event type, actors, sector/OKVED divisions, geography, affected business functions, mechanism of impact, time horizon, a one-sentence neutral summary; plus a field `genre`: news / analysis / opinion). Embedding the card removes source style (RT vs Kommersant vs Interfax brief), lets one filter out essays by `genre`, and puts documents in the same register as the LLM-written profile queries. Evidence is indirect: LLM-enriched item text boosted content-based news recommendation by up to 19.32% relative (ONCE, abstract) [16]; GENRE-style enrichment is reported for news summarization/profiling (snippet) [17-ctx]. Cost: one small-LLM call per item (~3k/week, negligible). **Strongly applicable.**

**2.2 Contextual retrieval.** Prepend an LLM-generated 50-100-token situating context to each chunk before embedding and BM25 indexing. Anthropic reports top-20 retrieval failure falling 5.7% -> 3.7% (-35%) with contextual embeddings, -49% (2.9%) adding contextual BM25, -67% (1.9%) adding a reranker (figures per secondary coverage; best embedding config) [11]. For us the "context" is the event card (2.1) plus source/date; the technique is essentially the same idea.

**2.3 doc2query / doc2query--.** Generate queries each document could answer and index them. Raw doc2query hallucinates; filtering with a relevance model improves effectiveness by up to 16% and cuts index size ~48% (abstract; another version states 23%/33%) [12]. Applied to us: generate "who would care?" pseudo-queries per item (e.g. "export compliance for freight forwarders"), i.e. doc-side expansions that capture second-order relevance; filter by cross-encoder score. Cost: one more LLM call per item.

**2.4 Title+lead vs summary vs multi-vector.** Late chunking (embed whole text, pool per chunk) preserves context for long documents, no extra training [13] (no numbers in abstract). bge-m3 multivector (ColBERT-style) gave MIRACL 70.5 vs dense 69.2 [5]. Practical recipe for long reads: embed (i) the event card, (ii) title+lead, (iii) optionally 2-3 aspect cards (e.g. "impact on logistics", "impact on lending"); score a document by the max over its vectors. Compared with the current 300-char truncation this fixes long reads whose key fact is late and opinion pieces with decorative leads.

**2.5 Style removal.** No dedicated paper found; the schema-constrained card (2.1) is the de-facto mitigation. Cheap supplement: drop source-name tokens, bylines, boilerplate; add a `genre` classifier (LLM or logistic regression on bge-m3 vectors) and downweight opinion/essay.

---

## 3. User/query side without free text

**3.1 Attribute-to-text templates + LLM expansion.** Convert each attribute combination into natural-language needs: "CFO of a 50-250-employee wholesale company (OKVED 46.x) in Novosibirsk, using FX accounts and acquiring: what news changes her cash, tax, FX, credit and counterparty risk?" Then have an LLM fan this out into N (30-100) short, diverse "information needs" per profile, written at the register of event cards. This is HyDE/query2doc applied to a synthetic user: HyDE has an LLM write a hypothetical relevant document and embeds it, matching fine-tuned retrievers without labels [14]; query2doc appends LLM pseudo-documents and lifts BM25 by 3-15% on MS MARCO/TREC DL and helps dense retrievers (abstract) [15]. Cost: one-off per profile (hundreds of profiles at most). Hazards: hallucinated specifics (GOLFer/doc2query-- style filtering, [12]).

**3.2 Hypothetical event cards (HyDE for news).** Ask the LLM: "write 20 headlines/events from the last week that would materially matter to this profile", in the same card schema. Compare card-to-card; this is the cleanest answer to compressed query-doc scores because both sides are in-distribution short event descriptions.

**3.3 Multi-interest profile.** Single-vector users blur interests; HieRec represents a user as a tree (overall / coarse topic / fine topic) and matches candidates at each level [17]. For attribute-defined users: hierarchy = role duties (level 1), role x industry (level 2), concrete exposures (FX, customs, rates, taxes, labour, sanctions, counterparties; level 3). Score = weighted max (not mean) over levels, with a per-topic quota in selection (4.4).

**3.4 Taxonomy/label embeddings.** Embed OKVED section/class descriptions, the bank-product list and role descriptions; also let an LLM generate, once, an OKVED-to-OKVED "dependency" list (suppliers, customers, regulators, substitutes). Zero-shot "classification by label embedding" tags each news item with OKVED divisions and business functions (cosine to label descriptions, or LLM tagging inside the event card). A profile then matches on tag overlap in addition to free-text similarity. No Russian OKVED-specific evidence found; the method is standard zero-shot label-embedding classification, and its attraction here is that tagging happens once per item, not once per profile-item pair.

**3.5 Cold-start evidence.** LLM listwise ranking shows promise for cold start (Dai et al., abstract) [18]; ONCE-style LLM enrichment of items helps content-only recommendation [16]. A 2026 report of an LLM-produced intermediate query representation of user interests with +4.38% cold-user DAU in an A/B test (snippet, domain unverified) points the same way.

**3.6 Learned projection.** Once even ~1-2k implicit/explicit relevance labels exist (clicks, thumbs, editor picks), train a small linear/MLP map from profile-attribute embedding to a query vector, or fine-tune the encoder (6). Not available at cold start.

---

## 4. Ranking enhancements

**4.1 Hybrid lexical + dense with RRF.** Reciprocal Rank Fusion sums 1/(k+rank) across rankers, k=60, using ranks not scores, so incomparable scales are no issue (Cormack et al., SIGIR 2009) [21]. BEIR found BM25 a robust zero-shot baseline, with rerankers/late interaction best on average and single dense models often behind [19]. SPLADE v2 learned-sparse gains >9% nDCG@10 on TREC DL19 over prior sparse (abstract) [20]. bge-m3 emits sparse weights and multivector scores from the same forward pass, so a three-way fusion costs no extra model (note: its sparse head is weakest standalone, 53.9 vs dense 69.2 on MIRACL, without self-distillation 36.7 [5]). Replace the "keyword bonus" with a proper BM25/bge-m3-sparse list on lemmatised Russian (pymorphy/Snowball) and fuse by RRF.

**4.2 Score calibration.** Compressed cosines are a property of the embedding, not the relevance. Fixes: per-profile z-score or percentile of scores against the week's score distribution (or against a fixed background sample of old news); rank-based fusion (RRF); or train a tiny logistic calibrator on labelled pairs. Use thresholds on the reranker/LLM score, not on cosine.

**4.3 Rerankers.** bge-reranker-v2-m3 (568M multilingual cross-encoder) is the standard open choice, used on top-100 fused candidates in recent RAG work (snippet) [24]. LLM rerankers: RankGPT (listwise permutation) with GPT-4 exceeded supervised monoT5-3B by 2.3 nDCG on BEIR avg over 8 sets; a distilled 440M model beat a 3B supervised one (abstract) [22]. RankZephyr, open 7B listwise, matches or beats GPT-4 in places and is robust to initial order (abstract) [23]. Listwise gave the best cost-quality trade-off for ChatGPT in recsys (abstract) [18]. For us: candidates per profile are small (top-100 of 3k), so even a pointwise LLM judge ("how relevant, 0-3, and why") is affordable and also gives the explanation text the final LLM needs. This is the step that can recognise indirect relevance (customs QR-code -> freight forwarder) if the profile prompt states the business function.

**4.4 Diversity.** MMR (Carbonell and Goldstein 1998), xQuAD (Santos et al. 2010) and PM2 (Dang and Croft 2012) are classical (prior knowledge, not re-fetched). xQuAD/PM2 treat the profile's topics (tax, FX, logistics, regulation, credit...) as aspects and select to cover them proportionally: better fit than MMR for "top-10 across several needs".

**4.5 Event clustering / story detection.** SemEval-2022 Task 8 (~10k article pairs, 18 language pairs, 7 similarity dimensions) shows story-level similarity is not plain topical similarity; top systems reached ~0.82 correlation (snippet) [25]. Single-link chaining is known to merge unrelated items via bridges; prefer agglomerative average/complete link or HDBSCAN on the event-card embedding plus entity/date constraints, then elect a representative per cluster (preferring wire briefs over opinion). Recency: apply a multiplicative time decay by event type after clustering, not before.

---

## 5. Graph + embedding hybrids

- GraphRAG builds an LLM entity graph and community summaries; wins on corpus-global, sense-making questions in comprehensiveness and diversity (qualitative in abstract; ~1M-token corpora) [29]. LightRAG: graph + vector, dual-level retrieval, incremental updates (claims only in abstract) [31].
- GraphRAG-Bench (ICLR 2026): systematic test across fact retrieval, complex reasoning, summarisation, creative generation; premise is that GraphRAG often loses to vanilla RAG on practical tasks, with benefits limited to specific scenarios (abstract) [30]. Practitioner summary of Microsoft's study: 72-83% comprehensiveness and 62-82% diversity win rates on global questions (snippet).
- News recommendation: DKN fuses word and entity (KG) channels in a CNN over titles [32]; KRED enriches any document encoder with KG-neighbourhood entity aggregation, multi-task [33]. Both require entity linking to a KG and click data to train.

**Assessment for our case.** A news-item-by-item selection task is not a global-summarisation task, so full GraphRAG/LightRAG is unlikely to pay off. A thin, hand-built graph does fit the "second-order relevance" problem: nodes = OKVED divisions, regulators, instruments (customs, FX, rates, sanctions), edges = supplier/customer/regulated-by/substitute (seed from Rosstat input-output tables and an LLM, ~100-300 edges). Use it for one-hop query expansion of the profile (freight forwarder -> customs, ports, rail tariffs, import volumes) and for tag-overlap scoring. Evidence that this particular device beats dense retrieval: none found; treat as hypothesis, test cheaply via the LLM-generated "related sectors" list (3.4), which is the same signal without a graph store.

---

## 6. Cheap adaptation

- Promptagator: <=8 examples per task, LLM-generated queries; dual encoders beat ColBERT-v2 by >1.2 nDCG avg on 11 sets and trained rerankers gain ~5.0 nDCG (abstract) [25b]. Open 3B-class LLMs suffice as generators (snippet) [28].
- GPL: synthetic queries + cross-encoder pseudo-labels; up to +9.3 nDCG@10 over an off-the-shelf SOTA dense model on six specialised domains; +1.4 more with TSDAE (abstract) [26].
- InPars: LLM query generation used chiefly to train cross-encoders; toolkit available [27].
- Synthetic-only embedding training (E5-Mistral) reaches strong results without labels in <1k steps; mixing with labelled data gives SOTA [9].
- Application: generate (profile need, news item) pairs by having the LLM produce, per event card, "which roles/industries need this and why" plus negatives from other themes; label with the cross-encoder/LLM; fine-tune bge-m3 (or a LoRA/adapter) contrastively. Expected gain on in-domain ranking: a few nDCG points to ~9 (GPL upper bound). Cost: tens of thousands of LLM calls, 1 GPU-hour. Priority below the zero-training items because the label set from the LLM judge doubles as the evaluation set and should exist first.

---

## 7. Other findings

- Evaluation first: no public Russian business-personalisation benchmark; build ~300 (profile, item, 0-3) judgments (editors + strong-LLM judge, spot-checked) and report nDCG@10 and coverage per aspect. BEIR's lesson that no single retriever dominates across tasks [19] argues for local measurement.
- Matryoshka dimension truncation (jina-v3 to 32-d) [8] and bge-m3 8192-token context are irrelevant at 3k items/week; do not optimise for speed.
- Instruction-tuned embedders: put the task in the query only [9]; for models without it (bge-m3) the profile query must be a self-contained descriptive sentence.
- Licence check: jina-v3 is CC BY-NC-SA 4.0 [8], blocking commercial use.

---

## Ranking of top 8 techniques (expected impact / effort for this setting)

| # | Technique | Impact | Effort | Why |
|---|---|---|---|---|
| 1 | LLM event cards per item (schema incl. sector tags, genre, impact) + embed card | High | Low | Removes style variance, filters essays, enables tagging and matching in one register [16][11][12] |
| 2 | LLM-generated profile "needs" / hypothetical event cards per profile (HyDE/query2doc), replacing 20 hand queries | High | Low | Fixes query-doc register gap and indirect relevance [14][15] |
| 3 | Cross-encoder (bge-reranker-v2-m3) or LLM pointwise/listwise rerank of top-100 with business-function-aware prompt | High | Low-Med | Largest precision gain in all hybrid pipelines; handles second-order cases [22][23][24][11] |
| 4 | Hybrid retrieval: bge-m3 dense + sparse + BM25(lemmatised) fused by RRF; rank/percentile calibration | Med-High | Low | Replaces keyword bonus, cures compressed scores [19][20][21][5] |
| 5 | Aspect-based selection (xQuAD/PM2) over profile topics + better story clustering (avg-link/HDBSCAN on cards) | Med-High | Low-Med | Directly targets duplicates and coverage [25] |
| 6 | Encoder bake-off (FRIDA, USER-bge-m3, Qwen3-Emb-4B/8B, mE5-instruct) on local labels | Medium | Low | Few-point gains; needs labels anyway [1][2][3][7] |
| 7 | OKVED/sector dependency list or thin sector graph for one-hop query expansion, zero-shot taxonomy tagging | Medium (uncertain) | Med | Only mechanism aimed squarely at indirect relevance; no direct evidence vs. dense [30][32][33] |
| 8 | Synthetic-pair contrastive fine-tune (Promptagator/GPL style) | Medium | Med-High | Up to ~9 nDCG on specialised domains, but best done after 1-7 and the label set exist [25b][26][9] |

Not recommended now: full GraphRAG/LightRAG, KG-based DKN/KRED (need click logs and KG) [29][31][32][33].

---

## References

[1] The Russian-focused embedders' exploration: ruMTEB benchmark and Russian embedding model design. Snegirev et al. (ai-forever). 2024. https://arxiv.org/abs/2408.12503
[2] GigaEmbeddings: Efficient Russian Language Embedding Model. Kolodin et al. (SberDevices). 2025. https://arxiv.org/abs/2510.22369
[3] FRIDA model card (ai-forever). 2024-25. https://huggingface.co/ai-forever/frida
[4] USER-bge-m3 model card. deepvk. 2024. https://huggingface.co/deepvk/USER-bge-m3
[5] M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation. Chen et al. (BAAI). 2024. https://arxiv.org/abs/2402.03216
[6] Multilingual E5 Text Embeddings: A Technical Report. Wang et al. (Microsoft). 2024. https://arxiv.org/abs/2402.05672
[7] Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models. Zhang et al. (Alibaba Qwen). 2025. https://arxiv.org/abs/2506.05176
[8] jina-embeddings-v3: Multilingual Embeddings With Task LoRA. Sturua et al. (Jina AI). 2024. https://arxiv.org/abs/2409.10173
[9] Improving Text Embeddings with Large Language Models. Wang et al. (Microsoft). 2024. https://arxiv.org/abs/2401.00368
[10] Promptriever: Instruction-Trained Retrievers Can Be Prompted Like Language Models. Weller et al. 2024. https://arxiv.org/abs/2409.11136
[11] Introducing Contextual Retrieval. Anthropic. 2024. https://www.anthropic.com/news/contextual-retrieval
[12] Doc2Query--: When Less is More. Gospodinov, MacAvaney, Macdonald. ECIR 2023. https://arxiv.org/abs/2301.03266
[13] Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models. Günther et al. (Jina AI). 2024. https://arxiv.org/abs/2409.04701
[14] Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE). Gao et al. 2022. https://arxiv.org/abs/2212.10496
[15] Query2doc: Query Expansion with Large Language Models. Wang, Yang, Wei (Microsoft). 2023. https://arxiv.org/abs/2303.07678
[16] ONCE: Boosting Content-based Recommendation with Both Open- and Closed-source LLMs. Liu et al. 2023. https://arxiv.org/abs/2305.06566
[17] HieRec: Hierarchical User Interest Modeling for Personalized News Recommendation. Qi, Wu et al. ACL 2021. https://arxiv.org/abs/2106.04408
[18] Uncovering ChatGPT's Capabilities in Recommender Systems. Dai et al. 2023. https://arxiv.org/abs/2305.02182
[19] BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models. Thakur et al. 2021. https://arxiv.org/abs/2104.08663
[20] SPLADE v2: Sparse Lexical and Expansion Model for Information Retrieval. Formal et al. 2021. https://arxiv.org/abs/2109.10086
[21] Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods. Cormack, Clarke, Büttcher. SIGIR 2009. https://doi.org/10.1145/1571941.1572114 (not fetched; described via secondary sources)
[22] Is ChatGPT Good at Search? Investigating LLMs as Re-Ranking Agents (RankGPT). Sun et al. EMNLP 2023. https://arxiv.org/abs/2304.09542
[23] RankZephyr: Effective and Robust Zero-Shot Listwise Reranking is a Breeze! Pradeep, Sharifymoghaddam, Lin. 2023. https://arxiv.org/abs/2312.02724
[24] bge-reranker-v2-m3 model card. BAAI. 2024. https://huggingface.co/BAAI/bge-reranker-v2-m3
[25] SemEval-2022 Task 8: Multilingual news article similarity. Chen et al. 2022. https://aclanthology.org/2022.semeval-1.155/
[25b] Promptagator: Few-shot Dense Retrieval From 8 Examples. Dai et al. (Google). 2022. https://arxiv.org/abs/2209.11755
[26] GPL: Generative Pseudo Labeling for Unsupervised Domain Adaptation of Dense Retrieval. Wang, Thakur, Reimers, Gurevych. 2021/22. https://arxiv.org/abs/2112.07577
[27] InPars Toolkit: A Unified and Reproducible Synthetic Data Generation Pipeline for Neural IR. Abonizio et al. 2023. https://arxiv.org/abs/2307.04601
[28] Study on LLMs for Promptagator-Style Dense Retriever Training. 2025. https://arxiv.org/abs/2510.02241
[29] From Local to Global: A Graph RAG Approach to Query-Focused Summarization. Edge et al. (Microsoft). 2024. https://arxiv.org/abs/2404.16130
[30] When to use Graphs in RAG: A Comprehensive Analysis for Graph RAG (GraphRAG-Bench). Xiang et al. ICLR 2026. https://arxiv.org/abs/2506.05690
[31] LightRAG: Simple and Fast Retrieval-Augmented Generation. Guo et al. 2024. https://arxiv.org/abs/2410.05779
[32] DKN: Deep Knowledge-Aware Network for News Recommendation. Wang et al. WWW 2018. https://arxiv.org/abs/1801.08284
[33] KRED: Knowledge-Aware Document Representation for News Recommendations. Liu et al. (Microsoft). RecSys 2020. https://arxiv.org/abs/1910.11494
[34] Maximal Marginal Relevance (MMR). Carbonell, Goldstein. SIGIR 1998. (classical; not fetched) https://doi.org/10.1145/290941.291025
[35] Exploiting query reformulations for web search result diversification (xQuAD). Santos, Macdonald, Ounis. WWW 2010; and PM2: Dang, Croft, "Diversity by proportionality", WSDM 2012. (classical; not fetched)

Corrections to inline cites: "[17-ctx]" in 2.1 refers to GENRE (LLM news enrichment, 2023, found only via search snippet; no URL verified) and should be treated as unverified. Author lists in [7], [8], [15], [31] and the 2026 cold-user paper (arXiv 2602.15005, domain unconfirmed) were not verified on page and are given from memory or snippet.
