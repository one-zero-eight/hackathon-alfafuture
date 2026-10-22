For each news story below, output one JSON object per line (JSONL), no other text. Use ONLY values from the vocabulary; never invent tags.

Vocabulary:
{VOCAB}

Schema (keys in this order):
{"sid": <story id>, "event": "<one Russian sentence: what happened, to whom>", "actors": ["..."], "region": [<regions>], "okved": [<sections directly affected>], "event_type": "<event_types>", "mechanism": "<one Russian sentence: how it reaches businesses>", "horizon": "<horizons>", "genre": "<genres>", "cause_effect": [{"okved": "<section>", "effect": "<effects>"}]}

Rules: cause_effect lists 0-4 sectors that feel a concrete effect (including indirect ones, e.g. fuel prices -> H costs_up). Opinion/columns get genre "opinion". Irrelevant to business (sport results, crime gossip): okved [] and cause_effect [].

Stories:
{STORIES}
