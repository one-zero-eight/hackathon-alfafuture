# Light retrieval + Haiku vs whole-set LLM: experiment findings

Corpus: 2,681 Russian news items -> 2,008 deduplicated stories (one week).
Personas (role @ company): P1 CFO (RU electronics importer), P2 Procurement (RU pasta maker), P3 General Counsel (RU marketplace),
P4 CISO (German bank), P5 COO (Kazakh freight forwarder), P6 HR/Security (French retailer).

## Reference
Gold = 8 Sonnet screeners read ALL 2,008 stories and labelled relevance per persona; 6 Opus agents wrote a fully informed memo per persona
(key issues, decisions, traps, ideal top-10). Judge = Opus with a strict rubric; "overall" = share of the reference's decision value captured (0-10).

## Scoreboard (judge overall, mean of 6 personas)
| Arm | Input to decision model | Model | Score |
|---|---|---|---|
| v2 | top-10 by e5-small multi-query | Haiku-low | 3.67 |
| f5 | top-10, e5-large, theme-capped | Haiku-low | 3.83 |
| c2 / p10 | 10 cards + related headlines, playbook prompt | Haiku-low | 4.83 |
| c1 | 10 cards + related headlines, prompt v2 | Haiku-low | 5.17 |
| oracle | gold's ideal top-10 (perfect retrieval) | Haiku-low | 5.17-5.33 |
| p10_sonnet | same 10 cards as p10 | Sonnet | 5.33 |
| p13 | 10 theme cards, related stories WITH leads | Haiku-low | 5.33 |
| **p14** | **p13 + 40 more one-line headlines** | **Haiku-low** | **5.50** |
| ws_sonnet | whole screened week (independent run) | Sonnet | 8.58* |
*Inflated: it read the same screened input as gold.

## Findings
1. Retrieval quality: bge-m3 >> e5-large > e5-small (nDCG@10 0.73 vs 0.67 vs 0.61). Cross-encoder reranking with a persona-as-query failed (0.18).
   PRF and a learned ranker did not help. Blind (news-agnostic) multi-query profiles were the biggest single gain over persona/group profiles.
2. Duplicates were the first failure: theme capping (single-link at bge-m3 sim 0.74) is required; nDCG penalises it, the judge rewards it.
3. A strict 10-item input caps at ~5.3 regardless of retrieval (oracle) or model (Sonnet). The binding constraint is BREADTH:
   gold memos combine 5-8 issues from 50-140 stories.
4. Breadth helps: 10 theme cards with related leads + 40 headlines (p14) is the best light setup (5.5) and covers 100% of gold issues by proxy.
5. Remaining gap is Haiku reasoning: financial direction errors (P1 fixes debt at peak rates in 4 of 6 runs, despite playbook), under-acting
   (alert levels, pay talks left at "monitor"), misreading a story's mechanism (QR-code turnbacks read as congestion).

## Recommended pipeline (p14)
bge-m3 embeddings (title + 300-char lead) -> per-persona blind query set (20 queries + keywords), score = mean of top-3 query sims + 0.02*kw hits
-> single-link theme grouping among top-300 (sim>=0.74), 1 story per theme -> top-10 theme cards (lead + up to 6 related stories with
220-char leads) + next 40 as one-liners -> Haiku with prompt v3 (playbook + act-vs-monitor rules).
Cost: ~6k input tokens per persona vs ~450k for a whole-set read (~75x cheaper).

## What would close the remaining gap
- Use Sonnet (or Haiku with higher effort) for the finance persona only; numerical/direction reasoning is the weakest point.
- Explicit two-pass decision step: first list mechanisms per card ("what exactly happened, to whom"), then decide.
- Collect user feedback on which items mattered and retrain the ranker per persona (the 2-fold learned ranker had too few labels to help yet).
- Judge variance: single judge run per arm; differences under ~0.5 are noise.
