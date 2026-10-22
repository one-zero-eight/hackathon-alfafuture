# P0: temporal split + card-prompt batches (40 stories each).
import json, pathlib, pandas as pd
D = pathlib.Path(__file__).parent
d = pd.read_parquet(D.parents[2] / 'exp/corpus.parquet')
d['day'] = d.date.str[:10]
# shortcut: corpus is 64% from 21 Oct, so cut by time not day; re-split by days once more weeks are collected
d['split'] = (d.date.astype(str) >= '2026-10-21T14:00').map({True: 'test', False: 'dev'})
d[['id', 'day', 'split']].to_csv(D / 'split.csv', index=False)
print(d.split.value_counts().to_dict())
vocab = (D / 'vocab.json').read_text()
tmpl = (D / 'CARD_PROMPT.md').read_text().replace('{VOCAB}', vocab)
out = D / 'batches'; out.mkdir(exist_ok=True)
rows = [f"[{r.id}] {r.title}. {str(r.lead)[:300]}" for r in d.itertuples()]
for i in range(0, len(rows), 40):
    (out / f'b{i // 40:03d}.md').write_text(tmpl.replace('{STORIES}', '\n'.join(rows[i:i + 40])))
assert len(list(out.glob('b*.md'))) == (len(rows) + 39) // 40
