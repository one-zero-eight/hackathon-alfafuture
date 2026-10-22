# Build reader prompts per (config, profile). Usage: PYTHONPATH=p4 python p5/build.py <config> [B1|B2|B3]
# Format (B3 = pilot p14): 10 theme-capped lead cards + related stories with leads + 40 one-line headlines.
import sys, json, os, numpy as np
import r1, r2, union
from r1 import PROF, CARD, D, ids, A0, A1
CFG, MODE = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'B3')
SCORE = {'base': r2.base, 'xQuAD': r2.xquad, 'E3-rerank': r2.e3, 'Q2only': r2.ARMS['Q2only'],
         'G1': r1.g1, 'X1': r1.x1, 'X2': r1.x2, 'P14': r1.ARMS['A0-Q1-E1'], 'U55X1': lambda p: union.split5(r2.base(p), r1.x1(p))}
ROLES = json.load(open('p5/roles.json')); TPL = open('../../exp/DECIDE_PROMPT_V3.md').read()
REG = {'moscow': 'Moscow', 'volga': 'Volga region', 'siberia_fe': 'Siberia / Far East'}
SIZE = {'small': 'small', 'medium': 'mid-size', 'large': 'large'}
E = A0  # theme/related similarity on raw bge-m3 vectors, as in the pilot

def why(p, i):  # graph path for graph-based arms (traceability)
    sec = sorted(r1.story_sec(CARD[i])); return f"    (graph path: your sector {p['okved']} -> {', '.join(sec) or '-'} via {CARD[i]['event_type']})"
def packet(p, s):
    order = np.argsort(-s); cards, themes = [], []
    for i in order:
        if all(E[i] @ E[j] < 0.74 for j in cards): cards.append(i)
        if len(cards) == 10: break
    taken = set(cards); out = []
    for ci in cards:
        t = f"[{ids[ci]}] {D.date.iloc[ci][:10]} | {D.source.iloc[ci]} (x{D.n.iloc[ci]}) | {D.title.iloc[ci]}\n    {' '.join(str(D.lead.iloc[ci]).split())[:600]}"
        if CFG in ('G1', 'X1', 'X2', 'U55X1'): t += '\n' + why(p, ci)
        if MODE != 'B1':
            rel = [j for j in order[:300] if j not in taken and E[ci] @ E[j] >= 0.62][:4]; taken |= set(rel)
            if rel: t += "\n    Related this week:" + ''.join(f"\n     - [{ids[j]}] {D.title.iloc[j]} — {str(D.lead.iloc[j])[:220]}" for j in rel)
        out.append(t)
    if MODE in ('B3', 'B4'):
        rest = [i for i in order if i not in taken][:40]
        out.append("OTHER RELEVANT HEADLINES THIS WEEK (one line each, lower priority):\n" + '\n'.join(f"  [{ids[j]}] {D.title.iloc[j]} — {str(D.lead.iloc[j])[:120]}" for j in rest))
    return '\n\n'.join(out), [ids[i] for i in order[:50]], sorted(taken | set(order[:0]))
d = f'p5/packets/{CFG}_{MODE}'; os.makedirs(d, exist_ok=True); seen = {}
for p in PROF:
    r = ROLES[p['role']]; news, top, _ = packet(p, SCORE[CFG](p))
    company = f"{SIZE[p['size']]} Russian company, OKVED {p['okved']} ({p['okved_name']}), {REG[p['region']]}; uses bank products: {', '.join(p['products'])}"
    txt = TPL.replace('{ROLE}', r['title']).replace('{COMPANY}', company).replace('{AUTHORITY}', r['authority']).replace('{PLAYBOOK}', r['playbook']).replace('{NEWS}', news)
    assert '{' not in txt.split('Your news-monitoring')[0], 'unfilled placeholder'
    open(f"{d}/{p['id']}.md", 'w').write(txt); seen[p['id']] = sorted(set(__import__('re').findall(r'\[(A\d{4})\]', news)))
json.dump(seen, open(f'{d}/seen.json', 'w')); print('built', d, 'avg ids seen', np.mean([len(v) for v in seen.values()]))
