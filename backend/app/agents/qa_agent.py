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

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
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
2. 切片未覆盖的部分可以用可靠的通用知识补充，但不要标注编号；
3. 只讲营养/饮食/运动领域的通用知识，不查询、不臆测用户本人的记录数据
   （用户问"我今天吃了多少"不归你管，那需要查库）；
4. 涉及医疗诊断、用药的问题，提醒用户咨询医生，不给出诊疗结论；
5. 回答控制在三五句话内，先给结论再给依据；不要自行输出“参考来源”列表，
   系统会在回答后追加可核验的来源目录。"""

_SELF_CHECK_PROMPT = """你是检索质量审查员。判断下方知识库切片是否足以回答用户问题：
- 充分：切片包含与问题直接相关的具体信息（数值、方法、结论）；
- 不足：切片只是擦边相关、明显缺关键信息，或完全没有相关内容。

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
    """检索 query：优先 supervisor 改写过的 task，兜底取最后的用户消息。"""
    if state.get("task"):
        return state["task"]
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage) and m.content:
            return m.content if isinstance(m.content, str) else str(m.content)
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
        return "（本次未检索到相关切片，请用可靠的通用知识回答并说明）"
    lines = [
        f"[{i}] 证据定位：{citation_label(r)}\n正文：{r['content']}"
        for i, r in enumerate(results, start=1)
    ]
    return "\n".join(lines)


def make_qa_agent():
    """构造 qa_agent 节点函数（Agentic RAG：混合检索 + 重排 + 迭代自检）。"""
    gen_llm = get_text_llm()  # 生成路：流式（SSE 打字机）
    check_llm = get_text_llm(streaming=False).with_structured_output(
        QaSelfCheck
    )  # 自检路：一次性结构化输出，关流式（与 supervisor 路由同理由）

    def qa_agent(state: AgentState) -> dict:
        question = _question_from(state)
        trace: list[dict] = []

        db = SessionLocal()  # 知识库是全局的，不涉用户数据，无需 user_id
        try:
            # ---- 第 1 轮检索 ----
            results = retrieve(db, question, top_k=4)
            trace.append(_trace_entry(question, 1, results, reason="初检"))

            # ---- 自检：不足则改写重检（≤2 轮）----
            check: Optional[QaSelfCheck] = check_llm.invoke(
                [
                    ("system", _SELF_CHECK_PROMPT),
                    (
                        "user",
                        f"用户问题：{question}\n\n知识库切片：\n{_context_block(results)}",
                    ),
                ]
            )
            trace.append(
                {
                    "name": "self_check",
                    "args": {"query": question, "round": 1},
                    "result": f"sufficient={check.sufficient}（{check.reason}）",
                }
            )
            if not check.sufficient and check.rewritten_query:
                results2 = retrieve(db, check.rewritten_query, top_k=4)
                trace.append(
                    _trace_entry(
                        check.rewritten_query,
                        2,
                        results2,
                        reason=f"第一轮不足：{check.reason}",
                    )
                )
                # 合并两轮（按切片 id 去重），第 2 轮结果靠前（含改写后的针对性）
                seen = {r["id"] for r in results2}
                results = results2 + [r for r in results if r["id"] not in seen]
                results = results[:6]

            # ---- 带来源生成 ----
            citations = citation_payloads(results)
            available_indexes = "、".join(
                f"[{citation['index']}]" for citation in citations
            ) or "（本轮没有可用引用编号）"
            system = SystemMessage(
                content=f"{QA_SYSTEM_PROMPT}\n\n【当前任务】{question}"
                f"\n\n【知识库切片】\n{_context_block(results)}"
                f"\n\n【可用引用编号】{available_indexes}"
                f"\n这些编号是本轮唯一有效的引用编号；不能使用其他 [n]。"
                f"\n\n【可用来源列表】"
                + "、".join(
                    f"[{i}]{citation_label(r)}"
                    for i, r in enumerate(results, start=1)
                )
            )
            response = gen_llm.invoke([system] + state["messages"])
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

        return {
            "messages": [response],
            "tool_calls": trace,
            "citations": citations,
        }

    return qa_agent
