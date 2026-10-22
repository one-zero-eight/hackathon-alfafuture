# K1: deterministic news keys "<sector>: <event> → <effect, for whom>" from A1 cards, embedded with bge-m3.
import json, numpy as np, pandas as pd
from sentence_transformers import SentenceTransformer
V = json.load(open('p0/vocab.json')); SEC = V['okved_sections']
EFF = {'costs_up': 'рост издержек', 'costs_down': 'снижение издержек', 'demand_up': 'рост спроса', 'demand_down': 'падение спроса',
       'delays': 'задержки поставок', 'access_restricted': 'ограничение доступа', 'access_opened': 'открытие доступа', 'rates_up': 'рост ставок',
       'rates_down': 'снижение ставок', 'rub_weaker': 'ослабление рубля', 'rub_stronger': 'укрепление рубля', 'compliance_burden': 'новые требования и отчётность',
       'risk_up': 'рост рисков', 'risk_down': 'снижение рисков'}
assert set(EFF) == set(V['effects'])
def key(c):
    sec = '; '.join(SEC[s] for s in c['okved']) or 'Экономика'
    eff = '; '.join(f"{EFF[e['effect']]} для: {SEC[e['okved']]}" for e in c['cause_effect']) or c['mechanism']
    return f"{sec}: {c['event']} → {eff}"
if __name__ == '__main__':
    ids = pd.read_parquet('../../exp/corpus.parquet').id.tolist(); C = {c['sid']: c for c in map(json.loads, open('p1/cards.jsonl'))}
    K = [key(C[i]) for i in ids]; print(K[ids.index('A0123')])
    X = SentenceTransformer('BAAI/bge-m3').encode(K, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    np.save('s1/keys_k1.npy', X); json.dump(K, open('s1/keys_k1.json', 'w'), ensure_ascii=False); print(X.shape)
