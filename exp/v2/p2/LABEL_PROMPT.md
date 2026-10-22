You are building a strict gold relevance labelling for a business-news experiment.

Read fully (use Read with offset/limit; read EVERY line, do not skim):
- Profiles: {PROFILES} — a JSON list of 16 users described ONLY by login parameters: role, OKVED section/name, region, company size, bank products. Each is a decision-maker at a Russian company with that profile; "products" are the bank products they use (credit, leasing, fx, deposits, salary project).
- News chunk: {CHUNK} — 251 Russian stories: [ID] date | source (xN outlets) | title, then a lead.

For EACH profile (in the order {ORDER}), list every story that should plausibly inform or change a decision within that role's authority at such a company. The story need not mention the industry; what matters is a realistic transmission path (fuel prices -> freight costs; key rate -> credit cost; customs/sanctions -> imports; tax/reporting rules -> chief accountant; regional events -> that region only).
Ignore celebrity, sport, crime trivia, generic war-front reports without a logistics/energy/regional link.

Scale: 3 = should trigger/materially change a decision now; 2 = useful input / monitor closely; 1 = background context, weak link. Omit 0.

Write ONLY this JSON to {OUT}: {"U01": {"A0123": 3, ...}, ..., "U16": {...}} (all 16 keys, possibly empty objects). Reply "done".
