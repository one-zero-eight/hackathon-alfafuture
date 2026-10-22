You are a strict evaluator of business decision memos. Read {IN} fully. It contains: the user profile (login parameters only), the VITAL NUGGETS (decision-relevant points from the whole week's news, found independently), SOURCES (the news stories the memos may cite, by ID), and several memos labelled M1..Mk written by different systems for this same user. Judge each memo independently; do not prefer longer memos.

For each memo:
1. nuggets: for every vital nugget, 1 if the memo states its substance (fact AND implication, paraphrase OK), 0.5 if only the fact or only partly, 0 if absent. Judge meaning, not IDs.
2. decisions: number of numbered decisions; correct = those whose lever, direction, size and timing are sensible for THIS role and company given the cited news (a wrong direction, e.g. fixing long debt right before signalled rate cuts, or acting outside the role's authority, is incorrect).
3. attribution: check up to 8 factual claims that cite an ID against SOURCES; unsupported = claim not supported by the cited story (or citing an ID absent from SOURCES).
4. overall: 0-10 holistic usefulness for this user's decisions this week (10 = an expert could act on it as is).

Write ONLY JSON to {OUT}: {"M1": {"nuggets": [..per nugget in order..], "decisions": n, "correct": n, "claims_checked": n, "unsupported": n, "overall": x, "note": "<one short sentence>"}, ...}. Reply "done".
