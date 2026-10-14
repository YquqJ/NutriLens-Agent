"""离线端到端 RAG 回答评测：执行 QA，再用 LLM-as-Judge 评分。"""

from typing import Any, Callable

from langchain_core.messages import HumanMessage

from app.agents.qa_agent import make_qa_agent
from app.core.config import settings
from app.rag.citations import strip_model_reference_catalog
from app.rag.judge import build_judge_report, judge_answer
from app.rag.retriever import RetrievalMode


def run_qa_judge_eval(
    queries: list[dict[str, Any]],
    *,
    qa_agent_factory: Callable[..., Callable] | None = None,
    judgment_fn: Callable[..., Any] | None = None,
    judge_model: str | None = None,
    dataset_version: str = "unspecified",
    retrieval_mode: RetrievalMode = "hybrid_rerank",
) -> dict[str, Any]:
    """在固定问题集上执行 QA 并评估忠实度、答案相关性。失败样例不会中断整批。"""
    make_agent = qa_agent_factory or make_qa_agent
    judge = judgment_fn or judge_answer
    cases: list[dict[str, Any]] = []

    for item in queries:
        question = item["query"]
        observed: dict[str, Any] = {}

        def observe(_question: str, evidence: list[dict[str, Any]], answer: str) -> None:
            observed.update(
                {"question": _question, "evidence": evidence, "answer": answer}
            )

        case: dict[str, Any] = {
            "query": question,
            "answer": "",
            "evidence": [],
            "judgment": None,
        }
        try:
            qa_agent = make_agent(
                evaluation_observer=observe, retrieval_mode=retrieval_mode
            )
            result = qa_agent({"messages": [HumanMessage(content=question)], "task": ""})
            if not observed:
                messages = result.get("messages") or []
                if messages:
                    observed["answer"] = str(messages[-1].content)
                    observed["evidence"] = []
            case["answer"] = strip_model_reference_catalog(
                observed.get("answer", "")
            )
            case["evidence"] = [
                {
                    "label": " · ".join(
                        part
                        for part in (
                            evidence.get("source_title") or evidence.get("label") or "",
                            evidence.get("section") or "",
                            f"第 {evidence['page_number']} 页"
                            if evidence.get("page_number") is not None
                            else "",
                        )
                        if part
                    ),
                    "section": evidence.get("section"),
                    "page_number": evidence.get("page_number"),
                    "content": evidence.get("content") or "",
                }
                for evidence in observed.get("evidence", [])
            ]
            judgment = judge(question, case["answer"], observed.get("evidence", []))
            case["judgment"] = (
                judgment.model_dump()
                if hasattr(judgment, "model_dump")
                else dict(judgment)
            )
        except Exception as exc:  # 把 QA / Judge 单条失败保留在报告里。
            case["error"] = f"{type(exc).__name__}: {exc}"
        cases.append(case)

    return build_judge_report(
        cases,
        judge_model=judge_model or settings.text_model,
        dataset_version=dataset_version,
        retrieval_mode=retrieval_mode,
    )
