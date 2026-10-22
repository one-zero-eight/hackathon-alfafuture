# Validate card JSONL files against the fixed vocabulary; report bad lines and missing ids.
import json, sys, pathlib, re
D = pathlib.Path(__file__).parent
V = json.loads((D / 'vocab.json').read_text())
ok, bad, seen = 0, [], set()
for f in sys.argv[1:]:
    want = set(re.findall(r'^\[(A\d+)\]', (D / 'batches' / (pathlib.Path(f).stem + '.md')).read_text(), re.M))
    got = set()
    for ln in pathlib.Path(f).read_text().splitlines():
        if not ln.strip(): continue
        try:
            c = json.loads(ln)
            assert c['event_type'] in V['event_types'] and c['genre'] in V['genres'] and c['horizon'] in V['horizons']
            assert set(c['okved']) <= V['okved_sections'].keys() and set(c['region']) <= set(V['regions'])
            assert all(e['okved'] in V['okved_sections'] and e['effect'] in V['effects'] for e in c['cause_effect'])
            got.add(c['sid']); ok += 1
        except Exception as e: bad.append((f, ln[:80], repr(e)[:60]))
    if want - got: bad.append((f, 'missing', sorted(want - got)[:5]))
print('ok', ok, 'bad', len(bad)); [print(b) for b in bad[:10]]
