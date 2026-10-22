You are a strict, objective evaluator in a research experiment comparing a CHEAP pipeline against a FULLY INFORMED reference.

For each persona P1..P6:
- Persona: {ROOT}/exp/personas.json
- REFERENCE (fully informed: an expert who cross-analysed ALL ~2,000 news stories of the week): {ROOT}/exp/gold/{P}_gold.md
- CANDIDATE (a small model that saw ONLY 10 news items picked by a light retrieval algorithm): {ROOT}/exp/runs/{VARIANT}/{P}_decisions.md
- The 10 items the candidate saw: {ROOT}/exp/runs/{VARIANT}/{P}_news.txt

Score each persona strictly:
1. issue_coverage: for each "Key issue" in the reference, 0 (absent), 0.5 (partially / only weakly), 1 (clearly addressed with equivalent substance). Report the list and the mean.
2. decision_match: for each reference "Decision", 0/0.5/1 whether the candidate makes an equivalent decision (same lever, similar direction and specificity). Report list and mean.
3. valid_extra: number of candidate decisions NOT in the reference that are still sound and useful for this persona.
4. errors: number of candidate decisions that are wrong, harmful, based on misread news, hallucinated facts, or that fall into the reference's "Traps". Name each briefly.
5. depth (1-5): specificity, quantification, cross-linking of signals, correct transmission paths.
6. overall (0-10): "if this persona acted on the candidate memo instead of the reference, how much of the decision value would they capture?" 10 = equivalent, 5 = half the value, 0 = useless or harmful.
7. retrieval_gap: one sentence — was the shortfall mainly due to the 10 items selected (missing key stories) or due to the model's reasoning on the items it had?

Write valid JSON to {ROOT}/exp/judge/{VARIANT}.json:
{"P1": {"issue_coverage": [..], "issue_mean": x, "decision_match": [..], "decision_mean": x, "valid_extra": n, "errors": ["..."], "depth": n, "overall": n, "retrieval_gap": "..."}, ..., "summary": {"mean_overall": x, "mean_issue": x, "mean_decision": x, "main_failure_modes": ["..."]}}
Be harsh and consistent: do not give credit for vague or generic advice that does not use the week's actual news. Use only the Read and Write tools. Write only that file; reply with the summary line.
