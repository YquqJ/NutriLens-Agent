"""
qa_agent Agentic RAG 测试（M4.5）。E2E：真实 LLM + 真实检索管线。

验收（SPEC）：问"减脂期每天吃多少蛋白质"，回答带来源且检索轨迹可见。
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.qa_agent import make_qa_agent
from app.core.config import settings
from app.db.seed_knowledge import seed_knowledge


def test_qa_agent_forwards_callbacks_to_every_llm_call(monkeypatch):
    """Token 评测回调必须同时覆盖自检与最终回答，不能只统计生成阶段。"""
    class FakeChecker:
        def __init__(self):
            self.configs = []

        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages, config=None):
            from app.agents.qa_agent import QaSelfCheck

            self.configs.append(config)
            return QaSelfCheck(sufficient=True, reason="切片直接覆盖问题")

    class FakeGenerator:
        def __init__(self):
            self.configs = []

        def invoke(self, _messages, config=None):
            self.configs.append(config)
            return AIMessage(content="建议按知识库范围执行。[1]")

    checker = FakeChecker()
    generator = FakeGenerator()
    callback = object()
    result_item = {
        "id": 1,
        "source_title": "营养指南",
        "section": "蛋白质",
        "page_number": 2,
        "chunk_index": 0,
        "content": "减脂期间可根据体重安排蛋白质摄入。",
    }

    def fake_get_text_llm(*, streaming=True):
        return generator if streaming else checker

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        "app.agents.qa_agent.retrieve", lambda *_args, **_kwargs: [result_item]
    )

    make_qa_agent(callbacks=[callback])(
        {"messages": [HumanMessage("减脂期蛋白质怎么安排？")], "task": ""}
    )

    assert checker.configs == [{"callbacks": [callback]}]
    assert generator.configs == [{"callbacks": [callback]}]


def test_qa_agent_evaluation_observer_receives_final_answer_and_generation_evidence(
    monkeypatch,
):
    class FakeChecker:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            from app.agents.qa_agent import QaSelfCheck

            return QaSelfCheck(sufficient=True, reason="证据覆盖问题")

    class FakeGenerator:
        def invoke(self, _messages):
            return AIMessage(content="按证据安排饮食。[1]")

    result_item = {
        "id": 7,
        "source_title": "营养指南",
        "section": "饮食结构",
        "page_number": 3,
        "chunk_index": 0,
        "content": "一餐可按蔬菜、优质蛋白、主食和适量脂肪配置。",
    }
    observed = []

    def fake_get_text_llm(*, streaming=True):
        return FakeGenerator() if streaming else FakeChecker()

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        "app.agents.qa_agent.retrieve", lambda *_args, **_kwargs: [result_item]
    )

    node = make_qa_agent(
        evaluation_observer=lambda question, evidence, answer: observed.append(
            (question, evidence, answer)
        )
    )
    result = node({"messages": [HumanMessage("怎么安排饮食？")], "task": ""})

    assert len(observed) == 1
    question, evidence, answer = observed[0]
    assert question == "怎么安排饮食？"
    assert evidence == [result_item]
    assert "按证据安排饮食。[1]" in answer
    assert result["messages"][-1].content == answer


def test_qa_agent_uses_latest_user_question_instead_of_expanded_task(monkeypatch):
    """宽泛咨询的检索和自检不能被路由任务扩写成更高的回答门槛。"""
    class FakeChecker:
        def __init__(self):
            self.messages = []

        def with_structured_output(self, _schema):
            return self

        def invoke(self, messages):
            from app.agents.qa_agent import QaSelfCheck

            self.messages.append(messages)
            return QaSelfCheck(sufficient=True, reason="核心原则已被切片覆盖")

    class FakeGenerator:
        def invoke(self, _messages):
            return AIMessage(content="可以根据核心原则安排饮食和运动。[1]")

    checker = FakeChecker()
    queries = []
    result_item = {
        "id": 1,
        "source_title": "体重管理指南",
        "section": "减脂原则",
        "page_number": 2,
        "chunk_index": 0,
        "content": "减脂应保持适度热量缺口，并结合有氧和抗阻训练。",
    }

    def fake_get_text_llm(*, streaming=True):
        return FakeGenerator() if streaming else checker

    class FakeDb:
        def close(self):
            pass

    def fake_retrieve(_db, query, **_kwargs):
        queries.append(query)
        return [result_item]

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr("app.agents.qa_agent.retrieve", fake_retrieve)

    result = make_qa_agent()(
        {
            "messages": [HumanMessage("减肥期间该如何饮食和运动？")],
            "task": (
                "解答减肥期间的饮食和运动原则，包括热量缺口建议、宏量营养素分配、"
                "运动类型与频率推荐"
            ),
        }
    )

    assert queries == ["减肥期间该如何饮食和运动？"]
    assert "用户问题：减肥期间该如何饮食和运动？" in checker.messages[0][1][1]
    assert "知识库中未找到" not in result["messages"][-1].content


def test_qa_agent_retries_when_self_check_omits_a_rewritten_query(monkeypatch):
    """自检判不足却未改写时，仍应以原问题进行一次扩大候选集的复检。"""
    class FakeChecker:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            from app.agents.qa_agent import QaSelfCheck

            self.calls += 1
            return QaSelfCheck(
                sufficient=self.calls > 1,
                rewritten_query="",
                reason="首轮证据不完整" if self.calls == 1 else "核心建议已覆盖",
            )

    class FakeGenerator:
        def invoke(self, _messages):
            return AIMessage(content="可以从饮食和运动两方面安排。[1]")

    checker = FakeChecker()
    captured_queries = []
    result_item = {
        "id": 1,
        "source_title": "体重管理",
        "section": "减脂",
        "page_number": 1,
        "chunk_index": 0,
        "content": "减脂期间应控制总能量，并结合有氧运动和力量训练。",
    }

    def fake_get_text_llm(*, streaming=True):
        return FakeGenerator() if streaming else checker

    class FakeDb:
        def close(self):
            pass

    def fake_retrieve(_db, query, top_k):
        captured_queries.append((query, top_k))
        return [result_item]

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr("app.agents.qa_agent.retrieve", fake_retrieve)

    result = make_qa_agent()(
        {
            "messages": [HumanMessage("减肥期间该如何饮食和运动")],
            "task": "回答：减肥期间该如何饮食和运动",
        }
    )

    assert captured_queries == [
        ("减肥期间该如何饮食和运动", 6),
        ("减肥期间该如何饮食和运动", 6),
    ]
    assert result["messages"][-1].content.startswith("可以从饮食和运动")


def test_qa_agent_abstains_when_evidence_is_only_partial(monkeypatch):
    """严格 RAG 下，擦边证据不能支撑受限回答，必须直接拒答。"""
    class FakeChecker:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            from app.agents.qa_agent import QaSelfCheck

            return QaSelfCheck(
                sufficient=False,
                rewritten_query="",
                reason="切片支持有氧运动建议，但未覆盖个性化训练计划",
            )

    class FakeGenerator:
        def __init__(self):
            self.called = False

        def invoke(self, _messages):
            self.called = True
            raise AssertionError("证据仅部分覆盖时不应调用回答生成模型")

    generator = FakeGenerator()
    result_item = {
        "id": 1,
        "source_title": "运动指南",
        "section": "有氧运动",
        "page_number": 3,
        "chunk_index": 0,
        "content": "稳态有氧适合减脂，持续30分钟以上。",
    }

    def fake_get_text_llm(*, streaming=True):
        return generator if streaming else FakeChecker()

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(
        "app.agents.qa_agent.retrieve", lambda *_args, **_kwargs: [result_item]
    )

    result = make_qa_agent()(
        {"messages": [HumanMessage("减脂但不做力量训练，适合什么运动？")], "task": ""}
    )

    assert result["messages"][-1].content == (
        "知识库中未找到与该问题直接相关的信息，暂时无法可靠回答。"
    )
    assert result["citations"] == []
    assert generator.called is False


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


def test_qa_agent_evaluation_observer_receives_grounded_abstention(monkeypatch):
    class FakeChecker:
        def with_structured_output(self, _schema):
            return self

        def invoke(self, _messages):
            from app.agents.qa_agent import QaSelfCheck

            return QaSelfCheck(sufficient=False, reason="没有可用证据")

    class FakeGenerator:
        def invoke(self, _messages):
            raise AssertionError("证据不足时不应生成建议")

    observed = []

    def fake_get_text_llm(*, streaming=True):
        return FakeGenerator() if streaming else FakeChecker()

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr("app.agents.qa_agent.get_text_llm", fake_get_text_llm)
    monkeypatch.setattr("app.agents.qa_agent.SessionLocal", lambda: FakeDb())
    monkeypatch.setattr("app.agents.qa_agent.retrieve", lambda *_args, **_kwargs: [])

    result = make_qa_agent(
        evaluation_observer=lambda question, evidence, answer: observed.append(
            (question, evidence, answer)
        )
    )({"messages": [HumanMessage("量子计算怎么工作？")], "task": ""})

    assert observed == [
        (
            "量子计算怎么工作？",
            [],
            "知识库中未找到与该问题直接相关的信息，暂时无法可靠回答。",
        )
    ]
    assert result["messages"][-1].content == observed[0][2]


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
