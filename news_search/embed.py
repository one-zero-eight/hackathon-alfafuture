"""Sentence encoders (loaded on first use) and the on-disk vector cache of articles."""

import os

import numpy as np

HF_IDS = {
    "bge-m3": "BAAI/bge-m3",
    "e5-large-instruct": "intfloat/multilingual-e5-large-instruct",
}
E5_TASK = "Instruct: Given a company profile or a news search query, retrieve relevant Russian news headlines\nQuery: "


def wrap_query(encoder_name, query):
    """e5-instruct wants a task prefix on queries (not on documents); bge-m3 takes plain text."""
    return E5_TASK + query if encoder_name == "e5-large-instruct" else query


def sentence_transformer(name, max_seq_length):
    """Default encoder factory: texts -> L2-normalised float32 matrix, on GPU / Apple GPU / CPU."""
    from sentence_transformers import SentenceTransformer
    import torch

    device = (
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu"
    )
    model = SentenceTransformer(HF_IDS[name], device=device)
    model.max_seq_length = max_seq_length
    if device != "cpu":
        model.half()  # fp16 is about twice as fast on a GPU; vectors are stored as float16 anyway
    return lambda texts: model.encode(
        list(texts),
        batch_size=128 if device == "cuda" else 64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)


def doc_text(item):
    return (item["title"] + ". " + (item.get("summary") or "")[:300]).strip(" .")


class VectorCache:
    """One vector per article id kept in an .npz file; only articles not seen before are encoded."""

    def __init__(self, path):
        self.path = path

    def vectors(self, items, encode):
        if os.path.exists(self.path):
            saved = np.load(self.path)
            ids, X = saved["ids"], saved["X"]
        else:
            ids, X = np.zeros(0, np.int64), None
        have = {int(i): k for k, i in enumerate(ids)}
        new = [it for it in items if it["aid"] not in have]
        if new:
            ids = np.concatenate([ids, [it["aid"] for it in new]])
            encoded = encode([doc_text(it) for it in new]).astype(np.float16)
            X = encoded if X is None else np.vstack([X, encoded])
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            np.savez(self.path, ids=ids, X=X)
            have = {int(i): k for k, i in enumerate(ids)}
        return X[[have[it["aid"]] for it in items]].astype(np.float32)
