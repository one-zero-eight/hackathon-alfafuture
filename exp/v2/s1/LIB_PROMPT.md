Build a QUERY LIBRARY for a business-news retrieval system. Queries must look like news keys in this exact template (Russian):
"<сектор>: <событие> → <эффект, для кого>"
Example news key: "Транспортировка и хранение: Спрос на автоперевозки грузов вырос на 20% → рост спроса для: Транспортировка и хранение".
Use the placeholders {SECTOR} (user's OKVED section name), {REGION} (user's region name) where the block depends on them.

Write ONLY a JSON object to {OUT}:
{"role": {"CEO": [...], "CFO": [...], "chief_accountant": [...], "treasury_head": [...]},
 "okved": {"<letter>": [...] for every letter in {SECTIONS}},
 "region": {"moscow": [...], "volga": [...], "siberia_fe": [...]},
 "product": {"credit": [...], "leasing": [...], "fx": [...], "deposits": [...], "salary": [...]},
 "role_okved": {"<role>|<letter>": [...] for every role and every letter in B C G H J K}}
Sizes: role 6 queries each, okved 6 each, region 3 each, product 2 each, role_okved 3 each. Each query is a hypothetical but typical event for that block (no real facts), phrased as a news key that such a user must not miss. Reply "done".
