"""
qa_agent Agentic RAG 测试（M4.5）。E2E：真实 LLM + 真实检索管线。

验收（SPEC）：问"减脂期每天吃多少蛋白质"，回答带来源且检索轨迹可见。
"""

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa_agent import make_qa_agent
from app.core.config import settings
from app.db.seed_knowledge import seed_knowledge


@pytest.fixture(scope="module", autouse=True)
def knowledge_ready():
    """保证知识库已 seed（幂等）。"""
    seed_knowledge()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_qa_agent_answers_with_sources_and_trace():
    """SPEC 验收：数值正确 + 来源标注 + 检索轨迹（retrieve + self_check）。"""
    qa = make_qa_agent()
    result = qa(
        {
            "messages": [HumanMessage("减脂期每天吃多少蛋白质")],
            "task": "回答知识问题：减脂期每天需要摄入多少蛋白质",
            "hop_count": 1,
        }
    )

    answer = result["messages"][-1].content
    # 1. 数值正确（知识库里是 1.6-2.2 克/公斤）
    assert any(x in answer for x in ("1.6", "2.2", "2.0")), answer
    # 2. 来源标注可见（编号引用或来源列表）
    assert ("[1]" in answer) or ("来源" in answer), answer
    # 3. 检索轨迹可见：retrieve_knowledge 与 self_check 各至少一条
    names = [tc["name"] for tc in result["tool_calls"]]
    assert "retrieve_knowledge" in names
    assert "self_check" in names
    retrieve_trace = next(tc for tc in result["tool_calls"] if tc["name"] == "retrieve_knowledge")
    assert retrieve_trace["result"], "检索轨迹应带召回摘要"


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_qa_agent_out_of_scope_guardrail():
    """纪律护栏：问查用户数据的问题，应明确不归它管（不臆造用户数据）。"""
    qa = make_qa_agent()
    result = qa(
        {
            "messages": [HumanMessage("我今天总共吃了多少卡路里？")],
            "task": "回答：查询用户今天摄入的总卡路里",
            "hop_count": 1,
        }
    )
    answer = result["messages"][-1].content
    # 不应编造具体数值；应引导走记录功能或说明查不到
    assert any(
        kw in answer
        for kw in ("无法", "不能", "查不到", "查不了", "不清楚", "记录", "数据库")
    ), answer
