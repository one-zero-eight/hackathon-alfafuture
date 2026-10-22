# Evaluating Personalized News Selection and LLM Interpretation Without Real User Feedback: A Literature and Practice Review

Date: 2026-10-22. Scope: review of 23 sources and three proposed evaluation designs for a pipeline in which LLM screeners label about 2,000 news items (relevance 0-3), a candidate pipeline selects about 10 cards, a small LLM writes a decision memo, and an Opus judge compares it with an Opus-built gold memo.

Method note: sources were located through web search; claims are taken from abstracts, search summaries and publisher pages, not full-text reads. Where a figure was not confirmed against the primary paper this is stated. Statements marked (inference) are the reviewer's own reasoning, not findings of the cited work.

## 1. LLMs as relevance assessors

**Agreement with humans.** Thomas et al. [1] collect careful feedback from real searchers, choose an LLM and prompt that agrees with it, and then label at scale. They report accuracy comparable to human labellers and better than third-party crowd workers, at a fraction of the cost. They also find that systematic prompt changes, and even simple paraphrases, alter accuracy. Prompt sensitivity is therefore a first-class noise source. UMBRELA [2] is the open reproduction with GPT-4o. Its judgments correlate highly with the system rankings produced by effective multi-stage retrievers on TREC Deep Learning 2019-2023. It was used to support the TREC 2024 RAG track. A follow-up asks whether it works on other LLMs [3], so the result cannot be assumed to transfer across models.

**Benchmarks of judges.** The LLMJudge challenge [4] released 42 LLM-generated label sets for TREC DL 2023, produced by eight teams [5]. A secondary review, not confirmed against the paper, reports that system rankings are mostly preserved while absolute scores shift. The practical lesson is that LLM labels are safer for ranking systems against each other than for reading absolute values.

**Perspectives and risks.** Faggioli et al. [6] lay out a spectrum of human-machine collaboration and argue that evaluation must ultimately reflect human judgment. Clarke and Dietz [7] argue that LLM assessment still cannot replace humans. They build a system tuned to exploit the automatic metric and obtain inflated scores without real gains. They also simulate every system using UMBRELA as a final re-ranker and show via Kendall's tau that system rankings get distorted. They name "narcissism" of LLMs and overfitting to LLM-based metrics as open problems.

**Self-preference.** Panickssery et al. [8] find that LLM self-recognition correlates linearly with self-preference as a judge. Zheng et al. [9] document self-enhancement, position and verbosity biases. Verga et al. [10] show that a panel of smaller judges from disjoint model families beat a single GPT-4 judge on human correlation, showed less intra-model bias, and cost over seven times less.

**Implication for our setup.** Our screeners label the pool, Opus writes the gold memo, and Opus judges. Labels, reference and judge therefore share an error source, which is exactly the circularity that [7] warns about. The nDCG-vs-memo disagreement may be partly a symptom: nDCG measures agreement with screener opinion, the judge measures agreement with Opus's memo (inference). Mitigations from the literature: calibrate the LLM labeler on a small human-labelled subset [1]; use heterogeneous model families [10]; use LLM labels mainly for comparing systems [4].

## 2. LLM-as-a-judge for long-form outputs

**Bias and agreement.** Zheng et al. [9] report over 80% agreement between GPT-4 and humans, equal to human-human agreement, along with position, verbosity and self-enhancement bias and limited reasoning ability. A study of 12 judges on over 100,000 instances [11] finds that position bias is not random but depends strongly on the quality gap between candidates. A recent study [12] argues that rubric-based pointwise scoring behaves like a multiple-choice task and shows position bias, and proposes balanced permutations of score options. It reports that aggregating across permutations improves correlation with humans. FairJudge [13] names pointwise/pairwise inconsistency as a core problem (same judge, contradictory outputs in different modes).

**Methods.** G-Eval [14] combines chain-of-thought evaluation steps with form filling and a probability-weighted score, reaching Spearman 0.514 on summarization, and the authors themselves flag a preference for LLM-written text. Prometheus [15] shows that rubric-conditioned evaluation with a reference answer reaches Pearson 0.897 with humans on 45 custom rubrics, against 0.882 for GPT-4-0613, and that reference answers are important. A community note (secondary) says it inherits GPT-4 biases and degrades without a good reference. This is relevant because our judge already uses a rubric and a reference, but the reference is itself an LLM opinion.

**Agreement measures and calibration.** Thakur et al. [16] show that percent agreement is insufficient: judges with high agreement can still produce quite different scores, so Cohen's kappa or Scott's pi should be reported. Only the largest judges align well with humans, up to about 5 points off human scores, with a leniency bias. For multiple raters, missing data and ordinal scores, Krippendorff's alpha with an ordinal metric is the standard choice (general statistical practice; not tied to a source above). For a 0-10 scale, also report ICC and the standard deviation across repeated runs.

**Number of runs.** We found no source giving a universal number of runs. The principled approach is empirical: run each judgment k times (k at least 3, with temperature above 0 or with permuted order of memo and reference), estimate the within-item standard deviation sigma (observed about 0.5 on 10), and note that the standard error of the mean is sigma/sqrt(k). With sigma = 0.5, k = 3 gives about 0.29 and k = 5 about 0.22. Paired comparisons between pipelines cancel item-level variance, so a paired bootstrap over profiles is more informative than raising k alone (inference). Panels [10] and balanced permutations [12] reduce systematic rather than random error.

## 3. Nugget and claim-level evaluation

**Nuggets.** The TREC 2024 RAG track revived nugget evaluation (TREC QA, 2003) with the AutoNuggetizer [17], where LLMs both create nuggets and assign them to answers. On 21 topics and 45 runs the automatic scores correlate strongly with mostly manual scores. A follow-up (arXiv 2504.15068, listed in the search results but not read) reports that automating components independently gives stronger agreement. A nugget list decomposes the reference into atomic checkable items, so coverage is measured by item rather than by one holistic number.

**Claims.** FActScore [18] scores the fraction of atomic facts supported by a knowledge source, and its automatic estimator has under 2% error against humans on biographies. RAGAS [19] defines faithfulness as the share of answer statements inferable from the retrieved context, using an LLM to extract statements, with gpt-3.5-turbo-16k as judge in the paper. ALCE [20] evaluates fluency, correctness and citation quality (recall and precision); even the best models lacked full citation support about 50% of the time on ELI5, and its NLI checker cannot detect "partially supports".

**Relevance to us.** The "issue coverage 100% vs judge 66%" gap is typical of a lexical or keyword proxy versus a semantic judge (inference). Nuggets should be decided by an entailment judgment against the memo text, not keyword matching, and should be split by importance (vital/okay as in AutoNuggetizer). Attribution accuracy per memo claim, checked against the 10 selected cards only, measures hallucination independently of the gold memo.

## 4. News recommendation: offline evaluation

**Data and metrics.** MIND [21] provides click logs from 1 million users and over 160k articles, and shows that performance depends strongly on content understanding and user-interest modelling. Our setting lacks clicks, so MIND is useful mainly as a template (impression-based AUC, MRR, nDCG@5/10) and as a source of real behaviour for validating synthetic profile generation (inference).

**Beyond accuracy.** Kaminskas and Bridge [22] survey diversity, novelty, serendipity and coverage and show via re-ranking experiments that these objectives are correlated with each other and trade off with accuracy. For a 10-card digest, intra-list diversity, topic coverage across the profile's interest facets, source diversity and freshness should be reported alongside nDCG.

**Aspect coverage.** alpha-nDCG [23] discounts a document's gain by (1-alpha)^k for each earlier document already covering the same aspect. This directly rewards covering distinct issues and penalizes ten near-duplicate cards. The "aspects" can be each profile's decision issues (from the nugget list), which unifies retrieval metrics with memo evaluation. This likely explains part of the disagreement: nDCG on 0-3 labels rewards redundancy, while the memo judge rewards distinct issues (inference).

**Simulation.** Agent4Rec [24] uses LLM agents as simulated users and reports both alignment and deviation from real preferences, i.e. partial fidelity only. Synthetic users can therefore support relative comparisons and sensitivity tests, but not absolute claims about real users. No counterfactual (off-policy) estimator is applicable without logged propensities, so we rely on simulation and on perturbation tests.

## 5. Robustness tests

**Metamorphic testing.** A metamorphic relation specifies how output should change under an input transformation without needing a ground-truth output [25]. Khirbat et al. [26] apply it to ChatGPT as a recommender via rating transformations and prompt perturbations, measuring list similarity with Kendall tau and RBO, and find lower similarity than expected, indicating instability of LLM recommenders. A 2023 RecPack Tests package (found in search results, not read) implements template metamorphic tests for recommender libraries.

**Relations suited to our case:**
- MR1 (invariance): paraphrase the profile text, or reorder the news pool; the selection and memo decisions should barely change (Jaccard of selected cards, RBO).
- MR2 (monotonicity): raise the weight of one interest/risk factor; related cards should move up and the memo should mention it.
- MR3 (negation): remove an interest; related cards should leave the top 10, and the memo should stop recommending actions about it.
- MR4 (injection): insert a synthetic, clearly critical item matching the profile into the pool; it must be selected and addressed in the memo; insert an irrelevant but high-salience item; it must not be selected.
- MR5 (dose-response): the size of change in output should be roughly proportional to the size of the change in profile.

**Temporal holdout.** Backtests must close leakage channels: retrieval of content written after the event and model training data newer than the event [27][28]. For a news pipeline, split the pool by date and make sure that the model for the memo cannot see post-cutoff items; test whether the LLM's own prior knowledge about known past events contaminates the memo (inference from [27][28]). Our own noted leakage (an arm saw screener notes) is the same class of problem: any information path from the reference to the candidate invalidates the comparison.

## 6. Business usefulness and decision quality

We did not find a single standard benchmark for "actionability" of news digests. Established practice, combined from the forecasting-evaluation literature and common expert-review methods, is:
- **Backtesting with later outcomes.** Take a past date, give the pipeline only the news available then, and check whether the flagged risks materialized afterwards. Forecasting-evaluation work [27][28] shows that temporal leakage is the main threat and that evaluating on realized outcomes is the strongest signal available, though real-world generalization of backtest results is not guaranteed [27].
- **Expert panels.** A small panel (3-5 domain practitioners) rating a stratified sample of memos on a rubric, adjudicated, used to calibrate the LLM judge. This follows the calibration logic of [1], where LLM prompts were selected for agreement with real feedback, and of [6].
- **Actionability rubric (proposed).** For each memo: (a) is the decision explicit; (b) is each claim traceable to a selected card [20]; (c) does it state what changes the decision (trigger/threshold); (d) is the time-sensitivity stated; (e) does it omit a decision-critical item (omission error is weighted higher than extra detail). Scores are binary per criterion for judge stability [12].

## 7. Synthesis: why the current setup is fragile

| Problem | Cause in literature | Mitigation |
|---|---|---|
| Same-family bias | self-preference [8][9], narcissism [7] | judge panel from disjoint families [10]; human-calibrated subset [1] |
| Judge noise about 0.5 | prompt and order sensitivity [1][11][12] | k>=3 runs, permutations, paired bootstrap |
| Gold = one opinion | single-source reference, circularity [6][7] | several independent gold memos, nugget consensus [17], expert audit |
| Leakage | temporal and information leakage [27][28] | strict information barriers; programmatic checks |
| nDCG vs memo disagree | redundancy not penalized [23]; labels share bias with gold [7] | alpha-nDCG on issue aspects; report both, validate against humans |
| Proxy 100% vs judge 66% | lexical proxy vs semantic judgement | entailment-based nuggets [17][18] |

## 8. Proposed evaluation designs

### Design A: Nugget-based, multi-judge, human-anchored (recommended baseline)

Steps:
1. For each profile, produce N=3 independent gold memos from different model families (e.g. Opus, a GPT-class and a Gemini-class model). Extract atomic nuggets from each using an LLM nuggetizer [17]; keep nuggets present in at least 2 of 3 as "vital", the rest as "okay".
2. For each candidate memo, assign nuggets (supported / partial / absent) with a panel of 3 judges from disjoint families [10], each run twice with permuted nugget order [12]. Aggregate by median; report Krippendorff alpha (ordinal) over judges [16].
3. Separately compute claim-level attribution: split memo into claims, check each against the 10 selected cards only (FActScore/ALCE style [18][20]); report unsupported-claim rate.
4. Have 2 humans label 30 memo/nugget pairs; compute Cohen's kappa of panel vs human [16] and gate on it before trusting results.
5. Report vital-nugget recall, claim precision, a decision-match flag, with paired-bootstrap CIs over profiles.

Cost: roughly 3 gold memos plus about 6 judge calls per memo-nugget set; for 50 profiles and 4 pipeline arms about 1,500-2,500 LLM calls plus about 2 human-hours. Measures: coverage of consensus issues, hallucination, decision agreement, with the family bias bounded and the single-opinion gold problem addressed. Weakness: nuggets still derive from LLMs (circularity reduced, not removed) [7].

### Design B: Retrieval-side re-grounding with intent-aware metrics and perturbation suite

Steps:
1. Replace single-screener labels by 2-3 screeners from different families, calibrate on a 150-item human-labelled sample per [1]; keep items with unanimous labels as high-confidence.
2. Derive each profile's decision aspects (from consensus nuggets in Design A step 1), and tag every pool item with aspects. Compute alpha-nDCG@10, ERR-IA-style aspect recall, intra-list diversity and coverage [22][23] alongside plain nDCG.
3. Run the metamorphic suite MR1-MR5 [25][26] over 20 profiles: for each, 5 perturbations; measure Jaccard/RBO of selections, and memo decision flips judged by the panel.
4. Check rank correlation (Kendall tau) between alpha-nDCG and nugget recall across arms; if low, retrieval metrics are not a valid proxy and should be demoted to diagnostics.

Cost: label calls about 2,000 x 3 screeners per pool (cheap with a small model), plus the perturbation runs (100 pipeline runs). No new human work except the calibration sample. Measures: selection quality including aspect coverage, stability and appropriate sensitivity, and whether the offline proxy tracks memo quality. Weakness: relies on synthetic profiles being realistic [24].

### Design C: Temporal backtest with realized outcomes and expert audit

Steps:
1. Choose 10-15 past dates; for each, freeze the pool to items published before the date and block any model access to later items [27][28]. Prefer items and events post-dating the writing model's training cutoff if available, to limit memorization.
2. Generate memos for profiles with a fixed set of forward-looking questions (e.g. "which events in the next 30 days will affect this decision?").
3. After the horizon, record which flagged risks or opportunities materialized (from later news, resolved by two annotators with an LLM pre-screen). Score precision/recall of flagged risks and a Brier-style score if probabilities are stated.
4. Have 3 domain experts blind-rate 40 memos on the actionability rubric (section 6), compare against judge scores, and use the result to calibrate or reweight the LLM judge.

Cost: highest, roughly 15-25 hours of expert and annotator time plus data curation. Measures: real decision value independent of any LLM opinion, plus calibration of the cheaper designs. Weakness: small sample, leakage hard to fully exclude [27], and few events materialize per profile.

### Recommended sequence
Run Design A as the standing benchmark, use Design B's suite as a regression test on every pipeline change, and run Design C once or twice to calibrate the weights of A. Always report paired differences with bootstrap CIs and agreement statistics, and never compare arms that differ in information access.

## References

[1] Thomas, Spielman, Craswell, Mitra. Large language models can accurately predict searcher preferences. SIGIR 2024. https://arxiv.org/abs/2309.10621
[2] Upadhyay, Pradeep, Thakur, Craswell, Lin. UMBRELA: UMbrela is the (Open-Source Reproduction of the) Bing RELevance Assessor. https://arxiv.org/abs/2406.06519
[3] Does UMBRELA Work on Other LLMs? SIGIR 2025. https://arxiv.org/abs/2507.09483
[4] Rahmani et al. LLMJudge: LLMs for Relevance Judgments. https://arxiv.org/abs/2408.08896
[5] Judging the Judges: A Collection of LLM-Generated Relevance Judgements. https://arxiv.org/abs/2502.13908
[6] Faggioli, Dietz, Clarke et al. Perspectives on Large Language Models for Relevance Judgment. ICTIR 2023. https://arxiv.org/abs/2304.09161
[7] Clarke, Dietz. LLM-based relevance assessment still can't replace human relevance assessment. https://arxiv.org/abs/2412.17156
[8] Panickssery, Bowman, Feng. LLM Evaluators Recognize and Favor Their Own Generations. NeurIPS 2024. https://arxiv.org/abs/2404.13076
[9] Zheng et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. https://arxiv.org/abs/2306.05685
[10] Verga et al. Replacing Judges with Juries: Evaluating LLM Generations with a Panel of Diverse Models. https://arxiv.org/abs/2404.18796
[11] Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge. https://arxiv.org/abs/2406.07791
[12] Am I More Pointwise or Pairwise? Revealing Position Bias in Rubric-Based LLM-as-a-Judge. https://arxiv.org/abs/2602.02219
[13] FairJudge: An Adaptive, Debiased, and Consistent LLM-as-a-Judge. https://arxiv.org/abs/2602.06625
[14] Liu et al. G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment. EMNLP 2023. https://arxiv.org/abs/2303.16634
[15] Kim et al. Prometheus: Inducing Fine-grained Evaluation Capability in Language Models. ICLR 2024. https://arxiv.org/abs/2310.08491
[16] Thakur et al. Judging the Judges: Evaluating Alignment and Vulnerabilities in LLMs-as-Judges. https://arxiv.org/abs/2406.12624
[17] Pradeep et al. Initial Nugget Evaluation Results for the TREC 2024 RAG Track with the AutoNuggetizer Framework. https://arxiv.org/abs/2411.09607
[18] Min et al. FActScore. EMNLP 2023. https://arxiv.org/abs/2305.14251
[19] Es et al. Ragas: Automated Evaluation of Retrieval Augmented Generation. EACL 2024 demos. https://arxiv.org/abs/2309.15217
[20] Gao, Yen, Yu, Chen. Enabling Large Language Models to Generate Text with Citations (ALCE). EMNLP 2023. https://arxiv.org/abs/2305.14627
[21] Wu et al. MIND: A Large-scale Dataset for News Recommendation. ACL 2020. https://aclanthology.org/2020.acl-main.331
[22] Kaminskas, Bridge. Diversity, serendipity, novelty, and coverage: a survey and empirical analysis of beyond-accuracy objectives in recommender systems. ACM TiiS 7(1), 2016/17. https://research.ucc.ie/en/publications/diversity-serendipity-novelty-and-coverage-a-survey-and-empirical/
[23] Clarke et al. Novelty and Diversity in Information Retrieval Evaluation. SIGIR 2008. https://plg.uwaterloo.ca/~gvcormac/novelty.pdf
[24] Zhang et al. On Generative Agents in Recommendation (Agent4Rec). SIGIR 2024. https://arxiv.org/abs/2310.10108
[25] Chen et al. Metamorphic testing: a review of challenges and opportunities. ACM Computing Surveys, 2018. https://eprints.nottingham.ac.uk/51607
[26] Khirbat et al. Metamorphic Evaluation of ChatGPT as a Recommender System. https://arxiv.org/abs/2411.12121
[27] Paleka, Goel, Geiping, Tramer. Pitfalls in Evaluating Language Model Forecasters. https://arxiv.org/abs/2506.00723
[28] Hindcast: Replaying Prediction Markets to Evaluate LLM Forecasters. https://arxiv.org/abs/2607.14051
