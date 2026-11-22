"""Pluggable text embedders for SSR. Spec: 'openai:<model>' | 'local:<st-model>' | 'voyage:<model>' | 'fake'."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get("UX_SWARM_CACHE", Path.home() / ".cache" / "ux-swarm" / "emb"))


class EmbedderUnavailable(RuntimeError):
    pass


def _norm(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float64)
    return m / np.clip(np.linalg.norm(m, axis=-1, keepdims=True), 1e-12, None)


class Embedder:
    spec = "base"

    def _embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def embed(self, texts: list[str]) -> np.ndarray:
        """L2-normalised embeddings, cached on disk per (spec, text)."""
        out: list[np.ndarray | None] = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            f = CACHE / hashlib.sha1(f"{self.spec}\0{t}".encode()).hexdigest()
            if self.spec != "fake" and f.exists():
                out[i] = np.array(json.loads(f.read_text()))
            else:
                todo.append(i)
        if todo:
            vecs = _norm(self._embed([texts[i] for i in todo]))
            for i, v in zip(todo, vecs):
                out[i] = v
                if self.spec != "fake":
                    CACHE.mkdir(parents=True, exist_ok=True)
                    (CACHE / hashlib.sha1(f"{self.spec}\0{texts[i]}".encode()).hexdigest()).write_text(json.dumps(v.tolist()))
        return np.vstack(out)


class FakeEmbedder(Embedder):
    """Deterministic hashed bag-of-words. For tests and dry runs only; not semantically meaningful."""
    spec = "fake"

    def _embed(self, texts):
        m = np.zeros((len(texts), 512))
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z']+", t.lower()):
                m[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 512] += 1
        return m + 1e-6


class OpenAIEmbedder(Embedder):
    def __init__(self, model: str):
        self.model, self.spec = model, f"openai:{model}"

    def _embed(self, texts):
        if not os.environ.get("OPENAI_API_KEY"):
            raise EmbedderUnavailable("openai embedder needs the OPENAI_API_KEY environment variable")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise EmbedderUnavailable("openai embedder needs the extra: uv sync --extra openai") from e
        r = OpenAI().embeddings.create(model=self.model, input=texts)
        return np.array([d.embedding for d in r.data])


class LocalEmbedder(Embedder):
    def __init__(self, model: str):
        self.model, self.spec = model, f"local:{model}"
        self._m = None

    def _embed(self, texts):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbedderUnavailable("local embedder needs the extra: uv sync --extra local") from e
        self._m = self._m or SentenceTransformer(self.model)
        return self._m.encode(texts)


class VoyageEmbedder(Embedder):
    def __init__(self, model: str):
        self.model, self.spec = model, f"voyage:{model}"

    def _embed(self, texts):
        if not os.environ.get("VOYAGE_API_KEY"):
            raise EmbedderUnavailable("voyage embedder needs the VOYAGE_API_KEY environment variable")
        try:
            import voyageai
        except ImportError as e:
            raise EmbedderUnavailable("voyage embedder needs the extra: uv sync --extra voyage") from e
        return np.array(voyageai.Client().embed(texts, model=self.model).embeddings)


def get(spec: str) -> Embedder:
    kind, _, model = spec.partition(":")
    if kind == "fake":
        return FakeEmbedder()
    if kind == "openai":
        return OpenAIEmbedder(model or "text-embedding-3-small")
    if kind == "local":
        return LocalEmbedder(model or "all-MiniLM-L6-v2")
    if kind == "voyage":
        return VoyageEmbedder(model or "voyage-3")
    raise EmbedderUnavailable(f"unknown embedder {spec!r}; providers: openai, local, voyage, fake")
