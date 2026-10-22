You are producing the independent WHOLE-SET decision memo for a research experiment.

Persona {P}: read {ROOT}/exp/personas.json (entry {P}).
Input: {ROOT}/exp/gold/{P}_input.txt — every story from a ~2,000-story week of Russian-language news that a full screening pass flagged as possibly relevant to this persona (rel 3/2/1 + a screening note). This is the whole-corpus view; read ALL of it.

Act as an excellent, fully informed {role} who has cross-analysed the whole week of news. Write {ROOT}/exp/runs/ws_sonnet/{P}_decisions.md (English) with:
1. "Key issues" — the 5-8 most decision-relevant themes of the week for this persona at this company, each with: supporting item IDs, the transmission path to the company, and why it matters now. Cross-link items (combine weak signals into one theme where they reinforce each other).
2. "Decisions" — 5-8 concrete actions within the persona's authority, each tied to item IDs, with what/when/size where reasonable. Note any decisions that require combining several items.
3. "Monitor" — items/indicators to watch.
4. "Traps" — items that look relevant but should NOT drive decisions (and why).
5. "Ideal top-10" — the 10 item IDs this persona most needs to read, in priority order, as a JSON array on one line starting with `TOP10: `.
Do not invent facts beyond the items. Write only that file; reply with one line.
