"""LLM-as-Judge 输出约束与离线报告聚合。"""

import pytest
from pydantic import ValidationError

from app.rag.judge import (
    RagAnswerJudgment,
    build_judge_report,
    judge_answer,
)
from app.rag.qa_eval import run_qa_judge_eval


def test_judge_answer_uses_original_question_answer_and_retrieved_evidence():
    judgment = RagAnswerJudgment(
        faithfulness_score=0.8,
        answer_relevance_score=0.9,
        unsupported_claims=["额外的具体数值"],
        unanswered_intents=[],
        rationale="主体回答有证据支持。",
    )

    class FakeJudge:
        def __init__(self):
            self.messages = None

        def with_structured_output(self, schema):
            assert schema is RagAnswerJudgment
            return self

        def invoke(self, messages):
            self.messages = messages
            return judgment

    fake_judge = FakeJudge()
    result = judge_answer(
        "减肥期间该如何饮食和运动？",
        "应关注饮食结构，也要进行运动。",
        [{"label": "体重管理指南·饮食", "content": "一餐可按蔬菜、蛋白质、主食和脂肪配置。"}],
        judge_llm=fake_judge,
    )

    assert result is judgment
    assert fake_judge.messages[0][0] == "system"
    assert fake_judge.messages[1][0] == "human"
    prompt = fake_judge.messages[1][1]
    assert "减肥期间该如何饮食和运动？" in prompt
    assert "应关注饮食结构，也要进行运动。" in prompt
    assert "一餐可按蔬菜、蛋白质、主食和脂肪配置。" in prompt


def test_judge_scores_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        RagAnswerJudgment(
            faithfulness_score=1.1,
            answer_relevance_score=0.9,
            unsupported_claims=[],
            unanswered_intents=[],
            rationale="无效分数。",
        )


def test_build_judge_report_averages_scores_and_keeps_failed_cases_visible():
    report = build_judge_report(
        [
            {
                "query": "问题一",
                "answer": "回答一",
                "evidence": [],
                "judgment": {
                    "faithfulness_score": 0.8,
                    "answer_relevance_score": 1.0,
                    "unsupported_claims": [],
                    "unanswered_intents": [],
                    "rationale": "回答完整。",
                },
            },
            {
                "query": "问题二",
                "answer": "回答二",
                "evidence": [],
                "error": "judge timeout",
            },
        ],
        judge_model="qwen-plus",
        dataset_version="rag-eval-v2",
    )

    assert report["n_cases"] == 2
    assert report["n_judged"] == 1
    assert report["n_failed"] == 1
    assert report["metrics"] == {
        "faithfulness": pytest.approx(0.8),
        "answer_relevance": pytest.approx(1.0),
    }


def test_run_qa_judge_eval_uses_original_question_and_actual_qa_evidence():
    evidence = {
        "source_title": "运动指南",
        "section": "有氧运动",
        "page_number": 3,
        "content": "成年人每周进行 150-300 分钟中等强度有氧活动。",
    }
    observed = {}

    def qa_agent_factory(*, evaluation_observer):
        def qa_agent(state):
            question = state["messages"][0].content
            observed["question"] = question
            evaluation_observer(
                question,
                [evidence],
                "每周可安排中等强度有氧活动。[1]\n\n参考来源：\n[1] 运动指南",
            )
            return {"messages": []}

        return qa_agent

    def judgment_fn(question, answer, contexts):
        observed["judgment_input"] = (question, answer, contexts)
        return RagAnswerJudgment(
            faithfulness_score=1,
            answer_relevance_score=1,
            rationale="回答有证据且切题。",
        )

    report = run_qa_judge_eval(
        [{"query": "成年人每周要做多少有氧运动？"}],
        qa_agent_factory=qa_agent_factory,
        judgment_fn=judgment_fn,
        judge_model="test-judge",
        dataset_version="rag-eval-test-v1",
    )

    assert observed["question"] == "成年人每周要做多少有氧运动？"
    assert observed["judgment_input"] == (
        "成年人每周要做多少有氧运动？",
        "每周可安排中等强度有氧活动。[1]",
        [evidence],
    )
    assert report["results"][0]["answer"] == "每周可安排中等强度有氧活动。[1]"
    assert report["dataset_version"] == "rag-eval-test-v1"
    assert report["n_judged"] == 1
