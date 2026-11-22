import pytest

from ux_swarm import stats

FLEISS_1971 = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
               [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]


def test_fleiss_kappa_known_value():
    assert stats.fleiss_kappa(FLEISS_1971) == pytest.approx(0.210, abs=0.001)


def test_jaccard_empty_sets_is_1():
    assert stats.jaccard(set(), set()) == 1.0
    assert stats.jaccard({1, 2}, {2, 3}) == pytest.approx(1 / 3)


def test_run_agreement():
    cells = {"p__t": {"r1": ({"a", "b"}, "success"), "r2": ({"a"}, "success"), "r3": ({"a", "b"}, "gave_up")}}
    ag = stats.run_agreement(cells)
    assert ag["mean_jaccard"] == pytest.approx((0.5 + 1 + 0.5) / 3)
    assert ag["outcome_agreement"] == pytest.approx(1 / 3)
