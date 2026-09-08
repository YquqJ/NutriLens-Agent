"""
qa_agent —— 知识问答专职 worker（M3 占位形态）。

SPEC 约定：M3.4-M3.6 阶段以"直连 LLM + 无工具"占位接入图，
保证 supervisor 的四路路由完整可用；M4 再替换为 Agentic RAG
（混合检索 + 重排 + 迭代自检）实现，届时回答将带知识库来源。

与其它 worker 的形态差异：无工具就无需 react 循环（create_react_agent），
一个普通节点函数足够 —— 组装与一次调用，返回 AIMessage。
"""

from langchain_core.messages import SystemMessage

from app.agents.llm import get_text_llm
from app.agents.state import AgentState

QA_SYSTEM_PROMPT = """你是营养与运动知识顾问，负责回答健康领域的知识性与建议性问题。只回答交给你的问题，不闲聊。

工作纪律：
1. 只讲营养/饮食/运动/健康领域的通用知识与建议，不查询、不臆测用户本人的记录数据
   （用户问"我今天吃了多少"不归你管，那需要查库）；
2. 涉及医疗诊断、用药的问题，提醒用户咨询医生，不给出诊疗结论；
3. 回答控制在三五句话内，先给结论再给依据。"""


def make_qa_agent():
    """构造 qa_agent 节点函数（占位形态：直连 qwen-plus，无工具）。"""

    llm = get_text_llm()

    def qa_agent(state: AgentState) -> dict:
        task = state.get("task") or ""
        system = SystemMessage(content=f"{QA_SYSTEM_PROMPT}\n\n【当前任务】{task}")
        response = llm.invoke([system] + state["messages"])
        return {"messages": [response]}

    return qa_agent
