"""Semantic Similarity Rating (Maier et al. 2025, arXiv 2510.08338).

Free-text answer -> Likert pmf via cosine similarity to anchor statements for points 1..5:
  s_r = cos(answer, anchor_r);  d_r = s_r - min(s) + eps*[r == argmin];  p_r = d_r^(1/T) / sum
averaged over several anchor sets.
"""
from __future__ import annotations

from functools import cache

import numpy as np
import yaml

from .config import data_dir

SUS_ITEMS = [
    "I think that I would like to use this app frequently.",
    "I found the app unnecessarily complex.",
    "I thought the app was easy to use.",
    "I think that I would need the support of a technical person to be able to use this app.",
    "I found the various functions in this app were well integrated.",
    "I thought there was too much inconsistency in this app.",
    "I would imagine that most people would learn to use this app very quickly.",
    "I found the app very cumbersome to use.",
    "I felt very confident using the app.",
    "I needed to learn a lot of things before I could get going with this app.",
]


def pmf(response: np.ndarray, anchors: np.ndarray, T: float = 1.0, eps: float = 0.0) -> np.ndarray:
    s = anchors @ response
    d = s - s.min()
    d[np.argmin(s)] += eps
    if d.sum() <= 1e-12:
        return np.full(len(s), 1 / len(s))
    d = d ** (1.0 / T)
    return d / d.sum()


@cache
def anchor_sets(construct: str) -> tuple[str, list[list[str]]]:
    """Returns (question, sets). SUS items share templated agreement anchors."""
    if construct.startswith("sus_"):
        raw = yaml.safe_load((data_dir("anchors") / "sus_agreement.yaml").read_text())
        item = SUS_ITEMS[int(construct[4:]) - 1]
        stmt = item[0].lower() + item[1:-1]
        return (f'How do you feel about this statement: "{item}"',
                [[a.format(s=stmt) for a in st] for st in raw["sets"]])
    raw = yaml.safe_load((data_dir("anchors") / f"{construct}.yaml").read_text())
    return raw["question"], raw["sets"]


def constructs() -> list[str]:
    return ["ease", "trust", "use_intent", "pay_intent"] + [f"sus_{i}" for i in range(1, 11)]


def score(answer: str, construct: str, embedder, T: float = 1.0, eps: float = 0.0) -> dict:
    _, sets = anchor_sets(construct)
    r = embedder.embed([answer])[0]
    ps = [pmf(r, embedder.embed(st), T, eps) for st in sets]
    p = np.mean(ps, axis=0)
    nz = p[p > 0]
    return {"pmf": p.round(4).tolist(), "mean": float(p @ np.arange(1, 6)),
            "entropy": float(-(nz * np.log2(nz)).sum()), "n_sets": len(sets)}


def sus_distribution(item_pmfs: list, n: int = 5000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    total = np.zeros(n)
    for i, p in enumerate(item_pmfs):
        r = rng.choice(np.arange(1, 6), size=n, p=np.asarray(p) / np.sum(p))
        total += (r - 1) if i % 2 == 0 else (5 - r)
    total *= 2.5
    return {"median": float(np.median(total)), "p10": float(np.percentile(total, 10)),
            "p90": float(np.percentile(total, 90)), "mean": float(total.mean())}
