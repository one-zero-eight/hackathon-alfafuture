You are building a GOLD-STANDARD relevance labelling for a business-news experiment. Be thorough and strict.

Inputs (read them fully with the Read tool; the chunk file may need several reads with offset/limit — read EVERY line, do not skim):
- Personas: {ROOT}/exp/personas.json  (6 personas: a role at a specific company, with their decision authority)
- News chunk: {ROOT}/exp/chunks/chunk_{K}.txt  (~251 Russian-language news stories, format: [ID] date | source (xN = number of outlets covering it) | title, then a lead paragraph)

Task: for EACH persona, find every story in this chunk that should plausibly change or inform a decision within that persona's authority at that company. The story does NOT need to mention the company, its country or its industry — what matters is the transmission path to their decisions (e.g. a German cyberattack wave matters to a German bank CISO; Brent price matters to a Kazakh freight forwarder via fuel; a French riot matters to a French retailer's security head; a Duma bill on marketplaces matters to a Russian e-commerce GC; ruble/yuan moves and key-rate signals matter to a CFO importing from China).
Ignore stories with no realistic decision path (celebrity, sports, crime trivia, generic war-front reports unless they hit logistics/energy/security for that persona).

Relevance scale:
3 = should trigger or materially change a decision now
2 = useful input to a decision / monitor closely
1 = background context, weak link

Output: write ONLY this file with the Write tool: {ROOT}/exp/gold/map_{K}.json
Format (valid JSON, no comments):
{"P1": [{"id": "A0123", "rel": 3, "why": "<=25 words: the transmission path to this persona's decision"}], "P2": [...], ..., "P6": [...]}
Include rel 1 items too, but be honest — most stories are irrelevant to any given persona. Do not write any other files. Reply with one line: counts per persona.
