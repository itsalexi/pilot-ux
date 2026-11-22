"""Agreement statistics."""
from __future__ import annotations

from itertools import combinations

import numpy as np


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def fleiss_kappa(table: list[list[int]]) -> float:
    """Rows = subjects, cols = categories, cells = raters choosing that category. Equal raters per row."""
    m = np.asarray(table, dtype=float)
    n = m.sum(axis=1)[0]
    if n < 2 or not np.allclose(m.sum(axis=1), n):
        return float("nan")
    p_j = m.sum(axis=0) / m.sum()
    P_i = ((m * m).sum(axis=1) - n) / (n * (n - 1))
    P_e = (p_j ** 2).sum()
    return float("nan") if P_e == 1 else float((P_i.mean() - P_e) / (1 - P_e))


def run_agreement(cells: dict[str, dict[str, tuple[set, str]]]) -> dict:
    """cells: cell id -> run id -> (issue ids hit, effective status)."""
    jac, same = [], []
    cats = sorted({st for runs in cells.values() for _, st in runs.values()})
    counts = {}
    for cid, runs in cells.items():
        vals = list(runs.values())
        for (a, sa), (b, sb) in combinations(vals, 2):
            jac.append(jaccard(a, b))
            same.append(sa == sb)
        counts[cid] = [sum(1 for _, st in vals if st == c) for c in cats]
    sizes = {sum(v) for v in counts.values()}
    n = max(sizes) if sizes else 0
    kappa = fleiss_kappa([v for v in counts.values() if sum(v) == n]) if n >= 2 and len(cats) > 1 else float("nan")
    return {"mean_jaccard": float(np.mean(jac)) if jac else float("nan"),
            "outcome_agreement": float(np.mean(same)) if same else float("nan"),
            "fleiss_kappa_outcome": kappa, "cells": len(cells), "pairs": len(jac)}
