"""
Embedding 客户端测试（M4.1）。E2E：真实 DashScope 调用。
"""

import pytest

from app.core.config import settings
from app.rag.embedding import _client, embed_query, embed_texts


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_embed_single_and_dimensions():
    vec = embed_query("减脂期每天需要多少蛋白质")
    assert len(vec) == 1024  # 与 KnowledgeChunk.embedding 列对齐
    assert any(abs(v) > 1e-6 for v in vec)  # 非全零


def test_embedding_client_has_finite_timeout():
    """RAG 在生成回答前先请求 embedding，也必须有超时边界。"""
    _client.cache_clear()
    try:
        client = _client()
        assert client.timeout == settings.llm_timeout_seconds
    finally:
        _client.cache_clear()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_embed_batch_over_limit():
    """12 条 > 单批上限 10：自动分两批，且返回顺序与输入一致。

    顺序用余弦相似度检验而非逐位相等：远端 embedding 两次调用存在
    微小浮点差异（非确定性），但同文本高相似、异文本低相似不受影响。
    """
    texts = [
        "减脂期建议保持热量缺口并保证蛋白质摄入",
        "有氧运动主要依靠有氧代谢系统供能",
        "维生素 C 是水溶性维生素，多余部分随尿液排出",
        "深蹲是训练下肢肌群的复合动作",
        "睡眠不足会升高皮质醇水平，不利于减脂",
        "碳水化合物每克提供约 4 千卡能量",
        "力量训练后的 48 小时是肌肉合成窗口期",
        "膳食纤维有助于肠道健康与血糖稳定",
        "铁缺乏会导致缺铁性贫血",
        "运动前动态热身可降低受伤风险",
        "橄榄油富含单不饱和脂肪酸",
        "基础代谢率随年龄增长逐渐下降",
    ]
    vectors = embed_texts(texts)
    assert len(vectors) == 12
    assert all(len(v) == 1024 for v in vectors)

    # 若分批乱序：vectors[0]（来自第 1 批）会错配第 2 批（texts[10]/[11]）的文本向量。
    # texts[1] 同属第 1 批，作为"批次内顺序正确"的对照
    again = embed_texts([texts[0], texts[1]])
    sim_same = _cosine(vectors[0], again[0])
    sim_cross = _cosine(vectors[11], again[1])  # texts[11] 若串位到 texts[1] 的槽就坏
    assert sim_same > 0.85, f"同文本相似度应高：{sim_same}"
    assert sim_cross < 0.85, f"不同文本相似度应低（疑似乱序）：{sim_cross}"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb)
