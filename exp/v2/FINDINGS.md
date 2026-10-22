# Findings: parameter-driven news selection (experiment run of 2026-10-22)

Executes `PLAN.md` phases P0–P5b. All numbers are means over 16 parameter-only profiles; ± is the standard error over profiles. Reader = Haiku (low effort, stand-in for an approved model); judge = Sonnet (blinded, shuffled order); labels and nuggets = Sonnet.

## 1. Answers to the research questions

| RQ | Answer | Evidence |
|---|---|---|
| Profile representation | **The dominant factor.** LLM need sentences (+ fixed role templates) beat raw parameter labels by 4× | test nDCG@10: Q0 labels 0.12 → Q2 needs 0.51 → Q1+Q2 0.53 |
| Event cards (A1) | Small, consistent gain over raw leads | Q2: A0 0.44 → A1/A2 0.51 (test); dev 0.33 → 0.40 |
| Hybrid BM25 (E2) | Hurts with need-sentence queries | A2-Q2: E1 0.52 → E2 0.40 |
| Cross-encoder rerank (E3) | No gain; lowers diversity | α-nDCG 0.45 → 0.38; memo 5.22 vs base 5.53 (ns) |
| Encoders (E4) | **Instruction-tuned encoders win offline** | test nDCG: bge-m3 0.53, e5-large-instruct **0.60**, Qwen3-Emb-0.6B 0.56, FRIDA 0.48, USER-bge-m3 0.50. Not yet tested end to end |
| Graph arms | **Lose end to end**; useful only as a slot-reserving supplement | memo: G1 3.68, X1 4.12 vs base 5.53 (both p<0.05, Holm). Union "top-5 dense + top-5 X1": 5.68 (tie) |
| Diversification (xQuAD over Q4 aspects) | **Best system.** Ties offline, wins in the memo | memo 6.17 ± 0.37 vs base 5.53 (p=0.036, Holm); fewest unsupported claims (1.3 %) |
| Breadth (RQ7) | **More context helps; no overload observed** | B1 cards 4.91, B2 +related 4.25, B3 +40 headlines 6.08, B4 two-pass 5.70 (B1, B2 < B3 significant; B4 ns) |

## 2. Round 3 (end to end, 7 configs, 3 judge runs)

| Config | Overall /10 | Nugget coverage | Decision accuracy | Unsupported claims | Cited IDs in packet |
|---|---|---|---|---|---|
| xQuAD | **6.17 ± 0.37** | **0.40** | **0.86** | **1.3 %** | 88.8 % |
| 5+5 (dense + X1) | 5.68 ± 0.32 | 0.38 | 0.80 | 2.9 % | 95.1 % |
| base (A2-Q1Q2-E1) | 5.53 ± 0.27 | 0.37 | 0.78 | 4.5 % | 95.6 % |
| E3 rerank | 5.22 ± 0.36 | 0.35 | 0.84 | 1.9 % | 94.1 % |
| P14 (pilot method, templates only) | 4.29 ± 0.37 | 0.30 | 0.62 | 3.6 % | 91.2 % |
| X1 cross-breed | 4.12 ± 0.40 | 0.27 | 0.62 | 4.4 % | 99.0 % |
| G1 tag graph | 3.68 ± 0.27 | 0.23 | 0.64 | 6.1 % | 99.4 % |

## 3. Interpretation

1. **Retrieval is near its ceiling for this corpus.** Recall@50 ≈ 0.97 for the leading arms, while memos cover only ~40 % of vital nuggets. Further retrieval tuning moves scores by hundredths; the remaining gap is in the reader.
2. **Breadth, not depth, feeds the reader.** The 40 one-line headlines (B3) add +1.2 to +1.8 points over card-only inputs. Related-story leads (B2) without headlines are worse than cards alone: they add redundant text on topics already covered.
3. **Diversity matters more than precision.** xQuAD and the headline tail both widen topic coverage, and both give the largest memo gains. Rerankers that sharpen precision narrow coverage and do not help.
4. **The sector graph is too coarse to rank.** With 18 OKVED sections and ~640 extracted cause → effect edges, graph scores tie on many stories. Its packets are the most "traceable" (99 % of cited IDs are real), but they carry less decision-relevant content. Keep the graph as an explanation layer and an optional reserved-slot supplement, not as the ranker.
5. **Two-pass reading did not help** (5.70 vs 6.08, ns) and raised unsupported claims (8 %). A digest step on its own does not fix the reader bottleneck.

## 4. Recommended configuration

Event cards (A1) → profile = fixed role templates + LLM need sentences (cached per parameter combination) → dense retrieval, max over raw and card vectors → xQuAD over the profile's weighted aspects → 10 cards + related leads + 40 headlines → reader with the role playbook. Optional: swap bge-m3 for multilingual-e5-large-instruct (offline +0.07 test nDCG, not yet verified end to end).

## 5. Deviations from PLAN.md

- Temporal split by time (21 Oct 14:00 UTC), not by day: 64 % of stories are from 21 Oct. Dev 1,200 / test 808.
- No third adjudication pass for labels: the two runs agree (linear κ = 0.73; 60 of 32,128 pairs differ by ≥ 2) and gold = their mean.
- Nuggets by Sonnet (2 runs, vital = matched across runs by story overlap), not Opus.
- E2 uses BM25 only (no bge-m3 sparse vectors).
- Round 2 encoder bake-off ran on CPU/MPS; E3 rerank is top-60 only.
- P14 baseline = pilot method on template queries (the pilot's hand-written personas are not allowed with login parameters only).
- Breadth ablation used 2 judge runs instead of 3 (token budget). B4 two passes were done in one reader call with a separate digest section, stripped before judging.
- Round 3 was not re-run with the e5-instruct encoder (bake-off finished after round 3 started).

## 6. Threats to validity

- Haiku and Sonnet stand in for the approved models; absolute scores will differ with Qwen/GLM/DeepSeek readers.
- One corpus week, 16 synthetic profiles; small n (Wilcoxon on 16 pairs).
- The same model family (Claude) labels, extracts nuggets and judges; the judge never saw labels, but correlated preferences are possible.
- Judge source excerpts are truncated (~250 characters), so unsupported-claim rates are a lower bound.
- The treasury playbook rule 2 ("strengthening ruble → convert export FX sooner") is ambiguous; one judge scored decisions following it as wrong. This affects the treasury profiles (U02, U11) in all arms equally.
- Haiku readers invented 1–11 % of cited IDs (worst: xQuAD B3 11 %). A production system needs an ID whitelist check after generation.

## 7. Cost (Claude tokens, this run)

≈ 1.6M (cards) + 2.3M (labels) + 0.6M (nuggets) + 0.3M (profile expansions) + 1.9M (round 3 readers) + 4.4M (round 3 judges) + 0.8M (ablation readers) + 1.0M (ablation judges) ≈ **13M tokens**. Production cost per stage: cards once per story; need sentences once per parameter combination; per user per day only retrieval (CPU) plus one reader call of ~10k input tokens.

## 8. Next experiments (by expected impact)

1. **Reader model and prompt with approved models** (Qwen3.6, GLM-5.3-Flash, DeepSeek-V4.1-Flash) on the recommended configuration; this is where the remaining gap is.
2. e5-large-instruct end to end (one config, 16 memos, judge).
3. Post-generation ID whitelist and claim check against cards.
4. Fix treasury playbook rule 2 and rerun U02/U11.

## 9. Files

`p0/` profiles, vocabulary, split · `p1/cards.jsonl` event cards · `p2/gold.json`, `p2/nuggets.json` labels and nuggets · `p3/out/` profile expansions · `p4/r1.py`, `r2.py`, `union.py` retrieval harness and results · `p5/` packets, memos, judge inputs and outputs, `agg.py`, `r3_summary.json`, `b_summary.json`.
