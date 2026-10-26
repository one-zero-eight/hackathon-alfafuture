"""Nearest Alfa thesis for a headline. BAAI/bge-m3 runs locally; it is not a generative model."""

import threading

from sentence_transformers import SentenceTransformer
import torch


class Bge:
    def __init__(self, docs: dict[str, str]):
        device = (
            "cuda"
            if torch.cuda.is_available()
            else "mps"
            if torch.backends.mps.is_available()
            else "cpu"
        )
        self.model = SentenceTransformer("BAAI/bge-m3", device=device)
        self.lock = (
            threading.Lock()
        )  # the news are analysed in threads, one encode at a time
        self.keys = list(docs)
        self.vec = self.model.encode(
            list(docs.values()),
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        )

    def search(self, query: str, k: int = 1, prefix: str = "") -> list[str]:
        idx = [i for i, key in enumerate(self.keys) if key.startswith(prefix)]
        if not idx:
            return []
        with self.lock:
            q = self.model.encode(
                [query], normalize_embeddings=True, show_progress_bar=False
            )[0]
        order = (self.vec[idx] @ q).argsort()[::-1][:k]
        return [self.keys[idx[j]] for j in order]
