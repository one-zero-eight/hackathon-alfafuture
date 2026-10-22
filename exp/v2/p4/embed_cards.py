# Embed A1 event cards (event + mechanism + effects) with bge-m3, aligned to corpus order.
import json, numpy as np, pandas as pd
from sentence_transformers import SentenceTransformer
ids = pd.read_parquet('../../exp/corpus.parquet').id.tolist()
C = {c['sid']: c for c in map(json.loads, open('p1/cards.jsonl'))}
def txt(c): return f"{c['event']} {c['mechanism']} " + ' '.join(f"{e['okved']}:{e['effect']}" for e in c['cause_effect'])
X = SentenceTransformer('BAAI/bge-m3').encode([txt(C[i]) for i in ids], batch_size=32, normalize_embeddings=True, show_progress_bar=False)
assert X.shape == (len(ids), 1024)
np.save('p4/cards_bgem3.npy', X); print('saved', X.shape)
