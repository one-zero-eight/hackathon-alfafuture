import sys; sys.path.insert(0,'exp'); import retrieve as R, numpy as np
ids=list(R.corpus.id); t=R.corpus.title
fx=[i for i,x in enumerate(t) if 'курс доллара' in x or 'Рубль укреп' in x][:6]
others=[i for i,x in enumerate(t) if 'ключевой ставки' in x or 'инфляционные' in x][:3]
for m in ['bgem3']:
    E=R.doc_emb(m); idx=fx+others
    print(m); print('\n'.join(f"{t[i][:45]:45} "+" ".join(f"{E[i]@E[j]:.2f}" for j in idx) for i in idx))
    # typical neighbour sims
    S=E@E.T; np.fill_diagonal(S,0); print('pct of all pairs', np.percentile(S,[50,90,99,99.9]).round(3))
