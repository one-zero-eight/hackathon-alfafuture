# Round 1: retrieval-only arms scored against P2 labels (nDCG@10, P@10, R@50, opinion share), dev/test split.
import json, sys, numpy as np, pandas as pd, networkx as nx
from collections import defaultdict
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

D = pd.read_parquet('../../exp/corpus.parquet'); ids = D.id.tolist(); N = len(ids)
SPLIT = pd.read_csv('p0/split.csv').split.values
CARDS = {c['sid']: c for c in map(json.loads, open('p1/cards.jsonl'))}
CARD = [CARDS[i] for i in ids]
PROF = json.load(open('p0/profiles.json'))
EXP = {p['id']: json.load(open(f"p3/out/{p['id']}.json")) for p in PROF}
GOLD = json.load(open('p2/gold.json'))  # {uid: {sid: grade}}
A0 = np.load('../../exp/cache/docs_bgem3_300.npy'); A1 = np.load('p4/cards_bgem3.npy')
M = SentenceTransformer('BAAI/bge-m3')
enc = lambda t: M.encode(t, normalize_embeddings=True, show_progress_bar=False)
ROLE = {'CEO': 'генеральный директор, собственник', 'CFO': 'финансовый директор', 'chief_accountant': 'главный бухгалтер', 'treasury_head': 'руководитель казначейства'}
REG = {'moscow': 'Москва', 'volga': 'Поволжье', 'siberia_fe': 'Сибирь и Дальний Восток'}
PRODS = {'credit': 'кредиты', 'leasing': 'лизинг', 'fx': 'валютные операции', 'deposits': 'депозиты', 'salary': 'зарплатный проект'}

def q0(p): return [f"{ROLE[p['role']]}; {p['okved_name']}; {REG[p['region']]}; {', '.join(PRODS[x] for x in p['products'])}"]
def q1(p):  # fixed templates, no LLM
    r, o, g = ROLE[p['role']], p['okved_name'], REG[p['region']]
    t = [f"{o}: изменения спроса, цен и издержек", f"регулирование и законы для отрасли {o}", f"{g}: региональные события, влияющие на бизнес"]
    t += {'CEO': ["санкции, импорт, поставщики и конкуренты", "стратегия, сделки, рынок"],
          'CFO': ["ключевая ставка ЦБ и стоимость кредитов", "курс рубля, инфляция и издержки"],
          'chief_accountant': ["налоги, НДС, отчётность, проверки ФНС", "трудовое законодательство и зарплата"],
          'treasury_head': ["курс рубля, юаня, валютный контроль", "ставки по депозитам, ликвидность"]}[p['role']]
    return t + [PRODS[x] + ': условия и ставки' for x in p['products']]
def q2(p): return EXP[p['id']]['needs']
def q3(p): return [f"{c["event"].removeprefix("Гипотетически:").strip()} {c["mechanism"]} " + " ".join(f"{e["okved"]}:{e["effect"]}" for e in c["cause_effect"]) for c in EXP[p['id']]['hyde_cards']]
QS = {'Q0': q0, 'Q1': q1, 'Q2': q2, 'Q3': q3}

def dense(Q, X):  # mean of top-3 query similarities per doc
    S = enc(Q) @ X.T; k = min(3, len(Q)); return np.sort(S, 0)[-k:].mean(0)
def docs(a): return {'A0': A0, 'A1': A1}[a] if a != 'A2' else None
def dscore(a, Q): return np.maximum(dense(Q, A0), dense(Q, A1)) if a == 'A2' else dense(Q, docs(a))

TOK = [f"{t} {l} {c['event']} {c['mechanism']}".lower().split() for t, l, c in zip(D.title, D.lead.astype(str).str[:300], CARD)]
BM = BM25Okapi(TOK)
def rrf(*scores, k=60):
    out = np.zeros(N)
    for s in scores: out[np.argsort(-s)] += 1 / (k + np.arange(1, N + 1))
    return out
def bm25(Q): return np.mean([BM.get_scores(q.lower().split()) for q in Q], 0)

# Graph pieces built from DEV cards only (no test leakage into edges).
SEC = sorted({e['okved'] for c in CARD for e in c['cause_effect']} | {s for c in CARD for s in c['okved']})
si = {s: i for i, s in enumerate(SEC)}
Wm = np.zeros((len(SEC), len(SEC)))
for c, sp in zip(CARD, SPLIT):
    if sp != 'dev': continue
    for s in c['okved']:
        for e in c['cause_effect']:
            if e['okved'] != s: Wm[si[s], si[e['okved']]] += 1
Wm = Wm + Wm.T; Wn = Wm / np.maximum(Wm.sum(1, keepdims=True), 1)
def activation(p, alpha=0.5, hops=2):
    a = np.zeros(len(SEC)); a[si[p['okved']]] = 1; x = a.copy()
    for _ in range(hops): x = alpha * Wn.T @ x; a += x
    return a
def story_sec(c): return {e['okved'] for e in c['cause_effect']} | set(c['okved'])
def g1(p):  # tag graph, 2-hop BFS: own sector 1, neighbour sectors 0.5, region 0.5, prior event-type 0.3
    nb = {SEC[j] for j in np.argsort(-Wn[si[p['okved']]])[:3] if Wn[si[p['okved']], j] > 0}
    et = {c['event_type'] for c in EXP[p['id']]['hyde_cards']}
    s = np.zeros(N)
    for i, c in enumerate(CARD):
        sec = story_sec(c)
        s[i] = (p['okved'] in sec) + 0.5 * len(sec & nb) + 0.5 * (p['region'] in c['region']) + 0.3 * (c['event_type'] in et and bool(sec))
    return s
def g2(p):
    a = activation(p); return np.array([sum(a[si[x]] for x in story_sec(c)) + 0.3 * (p['region'] in c['region']) for c in CARD])
G3 = nx.Graph()
for c, sp in zip(CARD, SPLIT):
    if sp != 'dev': continue
    for e in c['cause_effect']:
        G3.add_edge(('t', c['event_type']), ('s', e['okved']), weight=G3.get_edge_data(('t', c['event_type']), ('s', e['okved']), {'weight': 0})['weight'] + 1)
        for s in c['okved']:
            if s != e['okved']: G3.add_edge(('s', s), ('s', e['okved']), weight=1 + G3.get_edge_data(('s', s), ('s', e['okved']), {'weight': 0})['weight'])
def g3(p):
    node = ('s', p['okved']); pr = nx.pagerank(G3, personalization={node: 1}, weight='weight') if node in G3 else {}
    return np.array([(pr.get(('t', c['event_type']), 0) if story_sec(c) else 0) + sum(pr.get(('s', x), 0) for x in story_sec(c)) for c in CARD])
def x1(p):
    a = activation(p); w = np.array([max([a[si[x]] for x in story_sec(c)] or [0]) for c in CARD])
    return dscore('A1', q3(p)) * (0.5 + w / max(w.max(), 1e-9))
def x2(p):
    e = e2('A1', 'Q3', p); top = np.argsort(-e)[:300]; s = np.full(N, -1.0); g = g1(p)
    m = np.zeros(N, bool); m[top] = True
    r = rrf(np.where(m, e, -1e9), np.where(m, g + 1e-6 * e, -1e9)); s[m] = r[m]; return s
def e2(a, q, p): Q = QS[q](p); return rrf(dscore(a, Q), bm25(Q))

def ndcg(rank, g, k=10):
    dcg = sum((2 ** g.get(ids[i], 0) - 1) / np.log2(r + 2) for r, i in enumerate(rank[:k]))
    ideal = sorted(g.values(), reverse=True)[:k]; idcg = sum((2 ** v - 1) / np.log2(r + 2) for r, v in enumerate(ideal))
    return dcg / idcg if idcg else 0
NUG = {u: [set(n['sids']) for n in v if n['vital']] for u, v in json.load(open('p2/nuggets.json')).items()}
def andcg(rank, nugs, k=10, a=0.5):  # alpha-nDCG over the full corpus; ideal by greedy selection
    def gain(seq):
        seen = [0] * len(nugs); g = 0
        for r, sid in enumerate(seq):
            hit = [j for j, n in enumerate(nugs) if sid in n]; g += sum((1 - a) ** seen[j] for j in hit) / np.log2(r + 2)
            for j in hit: seen[j] += 1
        return g
    pool = set().union(*nugs) if nugs else set(); ideal = []; seen = [0] * len(nugs)
    for r in range(k):
        best = max(pool - set(ideal), key=lambda s: sum((1 - a) ** seen[j] for j, n in enumerate(nugs) if s in n), default=None)
        if best is None: break
        ideal.append(best); [seen.__setitem__(j, seen[j] + 1) for j, n in enumerate(nugs) if best in n]
    return gain([ids[i] for i in rank[:k]]) / max(gain(ideal), 1e-9)
def evaluate(score_fn):
    res = defaultdict(list)
    for p in PROF:
        s = score_fn(p); g = GOLD[p['id']]
        res['all_andcg'].append(andcg(np.argsort(-s), NUG[p['id']]))
        for sp in ('dev', 'test'):
            m = SPLIT == sp; rank = np.where(m)[0][np.argsort(-s[m])]
            gs = {k: v for k, v in g.items() if SPLIT[ids.index(k)] == sp}
            rel = {k for k, v in gs.items() if v >= 2}
            res[sp + '_ndcg'].append(ndcg(rank, gs))
            res[sp + '_p10'].append(np.mean([g.get(ids[i], 0) >= 2 for i in rank[:10]]))
            res[sp + '_r50'].append(len(rel & {ids[i] for i in rank[:50]}) / max(len(rel), 1))
            res[sp + '_op'].append(np.mean([CARD[i]['genre'] == 'opinion' for i in rank[:10]]))
    return {k: round(float(np.mean(v)), 3) for k, v in res.items()}, res['test_ndcg']

ARMS = {f'{a}-{q}-E1': (lambda p, a=a, q=q: dscore(a, QS[q](p))) for a in ('A0', 'A1', 'A2') for q in QS}
ARMS |= {f'{a}-{q}-E2': (lambda p, a=a, q=q: e2(a, q, p)) for a in ('A0', 'A1', 'A2') for q in QS}
ARMS |= {'G1': g1, 'G2': g2, 'G3': g3, 'X1': x1, 'X2': x2}
if __name__ == '__main__':
    only = sys.argv[1:]; out = {}
    for name, fn in ARMS.items():
        if only and name not in only: continue
        r, per = evaluate(fn); out[name] = r | {'per_profile_test_ndcg': [round(x, 3) for x in per]}
        print(f"{name:12s} " + ' '.join(f"{k}={v}" for k, v in r.items()), flush=True)
    json.dump(out, open('p4/r1_results.json' if not only else 'p4/r1_partial.json', 'w'), indent=1)
