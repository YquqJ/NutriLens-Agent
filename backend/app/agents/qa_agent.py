"""
qa_agent —— 知识问答专职 worker（M4.5：Agentic RAG 形态）。

与其它 worker 的形态差异：检索流程是确定性的（检索→自检→改写重检），
不需要 react 循环的"模型自由决定下一步"，一个普通节点函数里显式
编排更可控、可测 —— 这也是 Agentic RAG 的常见形态：把"迭代检索"
写进流程而非交给模型即兴发挥。

流程（≤2 轮）：
    检索（混合召回 + rerank 精排）
      → 自检（结构化输出：结果是否足以回答问题）
      → 不足 → 改写 query 重检 → 合并两轮结果
      → 带编号来源生成回答

检索轨迹经 state["tool_calls"] 透出（SSE tool_calls 事件 + messages
表 tool_trace 落库，前端折叠面板渲染）——与 react worker 的轨迹
同构，chat.py 统一收集。
"""

from typing import Any, Callable, Optional, Sequence

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.llm import get_text_llm
from app.agents.state import AgentState
from app.db.session import SessionLocal
from app.rag.citations import (
    citation_catalog_from_payloads,
    citation_label,
    citation_payloads,
    normalize_answer_citations,
    strip_model_reference_catalog,
)
from app.rag.retriever import retrieve

QA_SYSTEM_PROMPT = """你是营养与运动知识顾问，基于检索到的知识库切片回答问题。

工作纪律：
1. 回答依据优先来自下方【知识库切片】，引用处标注编号如 [1][2]；编号只能使用本轮
   "可用引用编号"中列出的值，不得将页码、片段号或其他数字写成 [n]；
2. 回答中的事实必须能被知识库切片直接支持；如果切片未覆盖问题，必须明确说明知识库未找到可靠信息，禁止用通用知识补充；
3. 只讲营养/饮食/运动领域的通用知识，不查询、不臆测用户本人的记录数据
   （用户问"我今天吃了多少"不归你管，那需要查库）；
4. 涉及医疗诊断、用药的问题，提醒用户咨询医生，不给出诊疗结论；
5. 回答控制在三五句话内，先给结论再给依据；不要自行输出“参考来源”列表，
   系统会在回答后追加可核验的来源目录。"""

_NO_EVIDENCE_REPLY = "知识库中未找到与该问题直接相关的信息，暂时无法可靠回答。"

_SELF_CHECK_PROMPT = """你是检索质量审查员。判断下方知识库切片是否足以回答用户问题：
- 充分：切片覆盖用户明确询问的核心意图和主要结论，即使没有覆盖所有可能的延伸细节，也可以判为充分；
- 不足：切片只是擦边相关、明显缺少回答核心问题所需的信息，或完全没有相关内容。
- 不要把用户没有明确询问的细节（例如完整宏量营养素比例、个体化热量、训练组数）作为拒答条件；回答时可说明这些细节未被覆盖，需要额外信息才能个性化。
- 对“如何饮食和运动”这类概括性问题，只要切片能支持主要原则、方向或可执行的基础建议，就判为充分。

不足时把问题改写成更利于检索的表述（补全领域关键词、消除口语化指代）。
判断只依据切片内容，不要自己脑补答案。"""


class QaSelfCheck(BaseModel):
    """自检的结构化输出约束。"""

    sufficient: bool = Field(description="检索结果是否足以回答问题")
    rewritten_query: str = Field(
        default="",
        description="不足时改写后的检索 query（补全领域关键词、消除口语化）；充分时留空",
    )
    reason: str = Field(default="", description="一句话判断依据")


def _question_from(state: AgentState) -> str:
    """以本轮最新用户原话为准，避免路由扩写提高 QA 的回答门槛。"""
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage) and m.content:
            return m.content if isinstance(m.content, str) else str(m.content)
    if state.get("task"):
        return state["task"]
    return ""


def _trace_entry(query: str, round_no: int, results: list[dict], reason: str) -> dict:
    """一条检索轨迹（SSE / 前端折叠面板渲染的格式，与 react 工具轨迹同构）。"""
    tops = "；".join(
        f"[{i}] {citation_label(r)}" for i, r in enumerate(results[:3], start=1)
    )
    return {
        "name": "retrieve_knowledge",
        "args": {"query": query, "round": round_no},
        "result": f"召回 {len(results)} 条：{tops}" if results else "召回 0 条",
        "reason": reason,
    }


def _context_block(results: list[dict]) -> str:
    """检索切片格式化为带编号的上下文块（引用编号与来源列表共用）。"""
    if not results:
        return "（本次未检索到相关知识库切片）"
    lines = [
        f"[{i}] 证据定位：{citation_label(r)}\n正文：{r['content']}"
        for i, r in enumerate(results, start=1)
    ]
    return "\n".join(lines)


def make_qa_agent(
    callbacks: Sequence[BaseCallbackHandler] | None = None,
    *,
    evaluation_observer: Callable[[str, list[dict[str, Any]], str], None] | None = None,
):
    """构造 qa_agent 节点函数（Agentic RAG：混合检索 + 重排 + 迭代自检）。"""
    gen_llm = get_text_llm()  # 生成路：流式（SSE 打字机）
    check_llm = get_text_llm(streaming=False).with_structured_output(
        QaSelfCheck
    )  # 自检路：一次性结构化输出，关流式（与 supervisor 路由同理由）
    callback_config = {"callbacks": list(callbacks)} if callbacks else None

    def invoke_llm(llm, messages):
        """评测注入回调；生产路径不传 config，兼容现有调用和测试替身。"""
        if callback_config is None:
            return llm.invoke(messages)
        return llm.invoke(messages, config=callback_config)

    def qa_agent(state: AgentState) -> dict:
        question = _question_from(state)
        trace: list[dict] = []

        def run_self_check(results_to_check: list[dict], round_no: int) -> QaSelfCheck:
            check = invoke_llm(
                check_llm,
                [
                    ("system", _SELF_CHECK_PROMPT),
                    (
                        "user",
                        f"用户问题：{question}\n\n知识库切片：\n{_context_block(results_to_check)}",
                    ),
                ],
            )
            trace.append(
                {
                    "name": "self_check",
                    "args": {"query": question, "round": round_no},
                    "result": f"sufficient={check.sufficient}（{check.reason}）",
                }
            )
            return check

        db = SessionLocal()  # 知识库是全局的，不涉用户数据，无需 user_id
        try:
            # ---- 第 1 轮检索 ----
            results = retrieve(db, question, top_k=6)
            trace.append(_trace_entry(question, 1, results, reason="初检"))

            # ---- 自检：不足则改写重检（≤2 轮）----
            check: Optional[QaSelfCheck] = run_self_check(results, 1)
            if not check.sufficient:
                retry_query = check.rewritten_query or question
                results2 = retrieve(db, retry_query, top_k=6)
                trace.append(
                    _trace_entry(
                        retry_query,
                        2,
                        results2,
                        reason=f"第一轮不足：{check.reason}",
                    )
                )
                # 合并两轮（按切片 id 去重），第 2 轮结果靠前（含改写后的针对性）
                seen = {r["id"] for r in results2}
                results = results2 + [r for r in results if r["id"] not in seen]
                results = results[:6]
                # 重写检索后重新审查最终证据，不能沿用第一轮“不足”的结论。
                check = run_self_check(results, 2)

            if not check.sufficient:
                if evaluation_observer is not None:
                    evaluation_observer(question, results, _NO_EVIDENCE_REPLY)
                return {
                    "messages": [AIMessage(content=_NO_EVIDENCE_REPLY)],
                    "tool_calls": trace,
                    "citations": [],
                }

            # ---- 带来源生成 ----
            citations = citation_payloads(results)
            available_indexes = "、".join(
                f"[{citation['index']}]" for citation in citations
            ) or "（本轮没有可用引用编号）"
            retry_context = state.get("worker_retry_context") or ""
            system = SystemMessage(
                content=(
                    f"{QA_SYSTEM_PROMPT}\n\n【当前任务】{question}"
                    + (f"\n\n【重试说明】{retry_context}" if retry_context else "")
                    + f"\n\n【知识库切片】\n{_context_block(results)}"
                    + f"\n\n【可用引用编号】{available_indexes}"
                    + "\n这些编号是本轮唯一有效的引用编号；不能使用其他 [n]。"
                    + "\n\n【可用来源列表】"
                    + "、".join(
                        f"[{i}]{citation_label(r)}"
                        for i, r in enumerate(results, start=1)
                    )
                )
            )
            response = invoke_llm(gen_llm, [system] + state["messages"])
        finally:
            db.close()

        # 模型输出是不可信文本：它可能把页码、片段号或臆测序号写成 [n]，
        # 也可能无视提示自行附一份“参考来源”。出站前统一清理，并且只保留
        # 正文实际引用的证据；目录、SSE 载荷、历史消息和前端抽屉共享同一份
        # 重编后的 citations，避免把“召回候选”误展示为“回答依据”。
        if isinstance(response.content, str):
            content, citations = normalize_answer_citations(
                strip_model_reference_catalog(response.content), citations
            )
            references = citation_catalog_from_payloads(citations)
            if references:
                content = f"{content}\n\n{references}"
            response = response.model_copy(update={"content": content})

        if evaluation_observer is not None:
            answer = (
                response.content
                if isinstance(response.content, str)
                else str(response.content)
            )
            evaluation_observer(question, results, answer)

        return {
            "messages": [response],
            "tool_calls": trace,
            "citations": citations,
        }

    return qa_agent
