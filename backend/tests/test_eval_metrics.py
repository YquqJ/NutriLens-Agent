"""指标函数离线单测：用已知 pred/rel 断言 Recall@K / MRR / nDCG@K 的精确值。"""

import math

import pytest

from app.rag.eval import mrr, ndcg_at_k, recall_at_k


def test_recall_at_k():
    relevant = {1, 2, 3}
    assert recall_at_k([5, 2, 9, 1, 3], relevant, 4) == pytest.approx(2 / 3)  # 前 4 命中 2 个
    assert recall_at_k([5, 2, 9, 1, 3], relevant, 5) == pytest.approx(1.0)
    assert recall_at_k([5, 9], relevant, 2) == pytest.approx(0.0)
    assert recall_at_k([], relevant, 3) == pytest.approx(0.0)


def test_recall_at_k_empty_relevant():
    assert recall_at_k([1, 2, 3], set(), 3) == pytest.approx(0.0)


def test_mrr():
    assert mrr([5, 2, 9], {9, 2}) == pytest.approx(0.5)  # 第 1 个相关在第 2 位
    assert mrr([1, 2, 3], {3}) == pytest.approx(1 / 3)
    assert mrr([5, 9], {1}) == pytest.approx(0.0)
    assert mrr([], {1}) == pytest.approx(0.0)


def test_ndcg_at_k():
    relevant = {1, 2}
    # 相关全排最前 = 理想排序，ndcg = 1
    assert ndcg_at_k([2, 1], relevant, 2) == pytest.approx(1.0)
    assert ndcg_at_k([1, 2, 3], set(), 3) == pytest.approx(0.0)
    assert ndcg_at_k([5, 6, 7], {1}, 3) == pytest.approx(0.0)  # 无命中
    # 单相关命中在第 2 位：dcg = 1/log2(3)，idcg = 1/log2(2) = 1
    assert ndcg_at_k([5, 1, 7], {1}, 3) == pytest.approx(1.0 / math.log2(3))