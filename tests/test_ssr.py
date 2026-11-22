import numpy as np
import pytest

from ux_swarm import embedders, ssr


def test_pmf_sums_to_one_and_peaks_at_closest_anchor():
    anchors = np.eye(5)
    r = np.array([0.1, 0.2, 0.9, 0.3, 0.1])
    p = ssr.pmf(r / np.linalg.norm(r), anchors)
    assert p.sum() == pytest.approx(1.0)
    assert p.argmax() == 2
    assert p[0] == 0.0 or p[4] == 0.0  # the least similar anchor gets eps (0) mass


def test_pmf_uniform_when_equal():
    p = ssr.pmf(np.ones(5) / np.sqrt(5), np.eye(5))
    assert np.allclose(p, 0.2)


def test_temperature_sharpens():
    r = np.array([0.1, 0.2, 0.9, 0.5, 0.1])
    soft = ssr.pmf(r, np.eye(5), T=2.0)
    sharp = ssr.pmf(r, np.eye(5), T=0.5)
    assert sharp.max() > soft.max()


def test_sus_all_best_is_100():
    best = [np.eye(5)[4] if i % 2 == 0 else np.eye(5)[0] for i in range(10)]
    d = ssr.sus_distribution(best)
    assert d["median"] == 100 and d["p10"] == 100


def test_score_uses_all_anchor_sets_and_orders_sensibly():
    emb = embedders.get("fake")
    hi = ssr.score("It was super easy and quick, no problem at all.", "ease", emb)
    lo = ssr.score("It was impossible, I could not do it at all, very hard.", "ease", emb)
    assert hi["n_sets"] >= 4
    assert hi["mean"] > lo["mean"]


def test_missing_openai_key_message(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(embedders.EmbedderUnavailable, match="OPENAI_API_KEY"):
        embedders.get("openai:text-embedding-3-small").embed(["hi"])


def test_unknown_provider_message():
    with pytest.raises(embedders.EmbedderUnavailable, match="openai, local, voyage, fake"):
        embedders.get("cohere:x")


def test_interview_schema_covers_constructs_and_close_trigger():
    from ux_swarm.interview import interview_schema
    sch = interview_schema()
    keys = set(sch["properties"]["answers"]["properties"])
    assert set(ssr.constructs()) <= keys and "close_trigger" in keys
    naive = sch["properties"]["naive"]["properties"]
    assert naive["ease"] == {"type": "integer", "minimum": 1, "maximum": 5}
