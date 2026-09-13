"""
qa_agent Agentic RAG 测试（M4.5）。E2E：真实 LLM + 真实检索管线。

验收（SPEC）：问"减脂期每天吃多少蛋白质"，回答带来源且检索轨迹可见。
"""

import pytest
from langchain_core.messages import HumanMessage

from app.agents.qa_agent import make_qa_agent
from app.core.config import settings
from app.db.seed_knowledge import seed_knowledge


def test_qa_agent_abstains_when_knowledge_base_has_no_answer(monkeypatch):
    """严格 RAG：无相关切片时不得调用生成模型补充通用知识。"""
    class FakeChecker:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            from app.agents.qa_agent import QaSelfCheck

            return QaSelfCheck(
                sufficient=False,
                rewritten_query="",
                reason="知识库没有相关切片",
            )

    class FakeGenerator:
        def __init__(self):
            self.called = False

        def invoke(self, _messages):
            self.called = True
            raise AssertionError("无证据时不应调用回答生成模型")

    generator = FakeGenerator()
    checker = FakeChecker()

    def fake_get_text_llm(*, streaming=True):
        return generator if streaming else checker

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr("app.agents.qa_agent.retrieve", lambda *_args, **_kwargs: [])

    result = make_qa_agent()(
        {"messages": [HumanMessage("量子计算机的纠错率是多少")], "task": ""}
    )

    assert result["messages"][-1].content == (
        "知识库中未找到与该问题直接相关的信息，暂时无法可靠回答。"
    )
    assert generator.called is False


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
    # 2. 来源标注既可见又可定位：不是重复文档名，而是章节、页码、片段对照表。
    assert "参考来源：" in answer, answer
    assert "[1]" in answer and "第 " in answer and "片段 " in answer, answer
    # 3. 检索轨迹可见：retrieve_knowledge 与 self_check 各至少一条
    names = [tc["name"] for tc in result["tool_calls"]]
    assert "retrieve_knowledge" in names
    assert "self_check" in names
    retrieve_trace = next(tc for tc in result["tool_calls"] if tc["name"] == "retrieve_knowledge")
    assert retrieve_trace["result"], "检索轨迹应带召回摘要"
    assert result["citations"], "QA 节点应返回供前端抽屉展示的结构化证据"
    assert result["citations"][0]["content"] and result["citations"][0]["label"]


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
