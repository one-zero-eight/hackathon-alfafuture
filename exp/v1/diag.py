import sys, json, numpy as np
sys.argv=[sys.argv[0]]; sys.path.insert(0,'exp')
import retrieve as R
p=__import__('os').environ.get('P','P5'); m=__import__('os').environ.get('M','small')
E=R.doc_emb(m); q,kw,_=R.profile(p,'queries'); Q=R.encode(m,q,'query'); S=E@Q.T
sc=np.sort(S,1)[:,-3:].mean(1); rank=(-sc).argsort().argsort()
gold=json.load(open('exp/runs/oracle/top.json'))[p]
ids=list(R.corpus.id)
for g in gold:
    i=ids.index(g); bq=S[i].argmax()
    print(f"rank {rank[i]:4d} sc {sc[i]:.3f} | {R.corpus.title[i][:60]} | best q: {q[bq][:50]}")
print('top10 score cutoff', np.sort(sc)[-10])
