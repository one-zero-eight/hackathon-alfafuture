# Build blinded judge inputs: per profile and run, memos of all configs shuffled (seeded) + vital nuggets + sources.
# Usage: python p5/judge_build.py <tag> <cfg1,cfg2,...> [runs]   -> p5/judge_in/<tag>_<U>_r<k>.md + key file
import sys, json, glob, random, re, pandas as pd
TAG, CFGS, RUNS = sys.argv[1], sys.argv[2].split(','), int(sys.argv[3]) if len(sys.argv) > 3 else 3
D = pd.read_parquet('../../exp/corpus.parquet').set_index('id')
NUG = json.load(open('p2/nuggets.json')); PROF = {p['id']: p for p in json.load(open('p0/profiles.json'))}
key = {}
for u in PROF:
    memos = {c: open(f'p5/memos/{c}_{u}.md').read() for c in CFGS}
    src = sorted(set().union(*(set(json.load(open(f'p5/packets/{c}/seen.json'))[u]) for c in CFGS)) | {s for m in memos.values() for s in re.findall(r'A\d{4}', m) if s in D.index})
    vital = [n['n'] for n in NUG[u] if n['vital']]
    for r in range(RUNS):
        order = CFGS[:]; random.Random(f"{u}-{r}").shuffle(order)
        body = [f"PROFILE: {json.dumps(PROF[u], ensure_ascii=False)}", "VITAL NUGGETS:\n" + '\n'.join(f"{i+1}. {n}" for i, n in enumerate(vital)),
                "SOURCES:\n" + '\n'.join(f"[{s}] {D.title[s]} — {str(D.lead[s])[:250]}" for s in src)]
        body += [f"===== M{i+1} =====\n{memos[c]}" for i, c in enumerate(order)]
        open(f'p5/judge_in/{TAG}_{u}_r{r}.md', 'w').write('\n\n'.join(body)); key[f'{u}_r{r}'] = {f'M{i+1}': c for i, c in enumerate(order)}
json.dump(key, open(f'p5/judge_in/{TAG}_key.json', 'w')); print('built', len(key), 'judge inputs')
