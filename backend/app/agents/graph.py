"""
Supervisor 图组装 —— 多 Agent 系统的总装车间（M3.6）。

图结构（星型拓扑，supervisor 是唯一调度中枢）：

    START → turn_reset → analyze_image → summarize → supervisor ⇄ diet_agent / exercise_agent / qa_agent / plan_agent

- analyze_image 在路由前把带图消息里的食物确定性识别出来（感知与决策分离，
  见 diet_agent.make_analyze_image_node），结果写 recognized_foods 供下游共用；
- summarize 在 supervisor 路由前把超长历史折叠成摘要、裁剪 messages（防上下文
  无限累积，见 memory.py）；短对话时是 no-op 不增延迟；
- worker 干完活固定回到 supervisor 汇报（add_edge(worker, "supervisor")），
  由 supervisor 看结果决定继续路由还是 FINISH —— 全图的流转控制权
  集中在一处，worker 之间不存在直连边（不允许互相踢皮球）；
- checkpointer：生产路径挂 PostgresSaver（thread_id = conversation_id），
  整个 AgentState 含 messages 按 thread 持久化，跨请求自动续上会话历史；
- worker 子图不单独挂 checkpointer：作为子图节点加入时由外层图统一
  管理 checkpoint（diet_agent 里 interrupt() 的挂起/恢复依赖这一点，
  子图自带 checkpointer 反而会出现双写与 checkpoint_id 错位）。
"""

import base64
from typing import Any, Optional

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, ChannelVersions, Checkpoint, CheckpointMetadata
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import START, StateGraph
from langgraph.types import Send
from psycopg.rows import dict_row

from app.agents.diet_agent import make_analyze_image_node, make_diet_agent
from app.agents.exercise_agent import make_exercise_agent
from app.agents.memory import make_summarize_node
from app.agents.plan_agent import make_plan_agent
from app.agents.qa_agent import make_qa_agent
from app.agents.state import AgentState
from app.agents.supervisor import make_supervisor_node
from app.core.config import settings

# 四个专职 worker（图中的固定节点名，supervisor 的 Command.goto 按名跳转）
WORKERS = ["diet_agent", "exercise_agent", "qa_agent", "plan_agent"]


def _turn_reset(state: AgentState) -> dict:
    """
    入口节点：每轮用户消息进来时重置"轮内"状态。

    checkpoint 会持久化整个 state，而这些字段的语义是"本轮"——
    hop_count 不重置的话，第一轮路由两次后，后续每一轮都会被
    防死循环守卫直接强制结束（worker 干脆得不到执行机会）；
    agent_trace / tool_calls 不重置则跨轮无限累积。
    resume（Command 恢复中断）不会重新经过 START，不受影响。
    """
    return {"hop_count": 0, "agent_trace": [], "tool_calls": [], "citations": []}


def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    supervisor_node: Optional[callable] = None,
    summarize_node: Optional[callable] = None,
):
    """
    组装并编译 supervisor 图。

    参数 checkpointer：生产传 PostgresSaver（get_checkpointer()），
    测试传 MemorySaver；不传则无持久化（图仍可单轮运行）。
    参数 supervisor_node：测试注入桩 supervisor（伪造路由决策）用，
    生产默认 qwen-plus 路由。
    参数 summarize_node：测试注入桩摘要器用，生产默认 qwen-plus 非流式。
    """
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node or make_supervisor_node())
    builder.add_node("diet_agent", make_diet_agent())
    builder.add_node("exercise_agent", make_exercise_agent())
    builder.add_node("qa_agent", make_qa_agent())
    builder.add_node("plan_agent", make_plan_agent())

    # 星型接线：supervisor 是唯一入口；每个 worker 完成后回到 supervisor
    builder.add_node("turn_reset", _turn_reset)
    # 图片感知：带图时先确定性识别食物（感知与决策分离），结果写 recognized_foods
    builder.add_node("analyze_image", make_analyze_image_node())
    # 摘要压缩：在 supervisor 路由之前把超长历史折叠成摘要、裁剪 messages
    builder.add_node("summarize", summarize_node or make_summarize_node())
    builder.add_edge(START, "turn_reset")
    builder.add_edge("turn_reset", "analyze_image")
    builder.add_edge("analyze_image", "summarize")
    builder.add_edge("summarize", "supervisor")
    for worker in WORKERS:
        builder.add_edge(worker, "supervisor")

    return builder.compile(checkpointer=checkpointer)


def _psycopg_conn_string() -> str:
    """把 SQLAlchemy 方言 URL 转成 psycopg 原生连接串（去掉 +psycopg 后缀）。"""
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_checkpointer() -> PostgresSaver:
    """
    进程级 PostgresSaver 单例（NutriLensPostgresSaver，见下方补丁说明）。

    不用 from_conn_string：它是 contextmanager，with 块退出即关连接，
    做不了常驻单例 —— 这里自持一条 psycopg 连接。

    连接参数（autocommit / prepare_threshold=0 / dict_row）是
    PostgresSaver 的硬性要求：checkpoint 写入依赖自动提交，
    prepare_threshold=0 规避 psycopg 预编译语句与临时表类型不符的坑。

    setup() 建 checkpoint 三张表（幂等），等价于业务表的 init_db；
    首次调用发生在进程第一个请求构图时，幂等可安全并发重入。
    """
    conn = psycopg.connect(
        _psycopg_conn_string(),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    checkpointer = NutriLensPostgresSaver(conn)
    checkpointer.setup()
    return checkpointer


# ---- pending_sends 兼容补丁（踩坑记录见 DESIGN_NOTES）----
# langgraph 0.4.10 的 react 子图用 Send API 调度工具节点，Send 会进入
# checkpoint["pending_sends"]；而 checkpoint-postgres（2.x/3.x 皆是）的 put()
# 把整个 checkpoint 用原生 json.dumps 落 JSONB 列 —— Send 不可序列化直接崩。
# Send 的另一条落库通道（put_writes → checkpoint_writes 表）只服务读路径的
# v<4 迁移逻辑，恢复执行依赖的是 checkpoint 里的 pending_sends 本身。
# 因此补丁：写时编码成 JSON 安全结构（serde msgpack + base64），
# 读时解码还原 Send，保证 PostgresSaver 与 MemorySaver 行为一致。

_send_serde = JsonPlusSerializer()  # serde 能正确往返 Send（含其 arg 里的消息对象）

_PENDING_SENDS_TAG = "__nutrilens_send__"


def _encode_send(send: Send) -> dict:
    """Send → JSON 安全 dict（入 JSONB 列）。"""
    typ, blob = _send_serde.dumps_typed(send)
    return {
        _PENDING_SENDS_TAG: True,
        "type": typ,
        "blob": base64.b64encode(blob).decode("ascii"),
    }


def _decode_send(obj: Any) -> Any:
    """JSON 安全 dict → Send（出 JSONB 列）；非本补丁编码的值原样返回。"""
    if isinstance(obj, dict) and obj.get(_PENDING_SENDS_TAG):
        return _send_serde.loads_typed((obj["type"], base64.b64decode(obj["blob"])))
    return obj


class NutriLensPostgresSaver(PostgresSaver):
    """PostgresSaver + pending_sends 的 JSONB 往返补丁。"""

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        sends = checkpoint.get("pending_sends")
        if sends:
            checkpoint = dict(checkpoint)  # 浅拷贝，不动调用方持有的原 dict
            checkpoint["pending_sends"] = [_encode_send(s) for s in sends]
        return super().put(config, checkpoint, metadata, new_versions)

    def _load_checkpoint_tuple(self, value):
        # value["checkpoint"] 是 psycopg json.loads 出来的 dict（含待还原的编码结构）
        raw_sends = value["checkpoint"].get("pending_sends")
        if raw_sends:
            value["checkpoint"]["pending_sends"] = [
                _decode_send(s) for s in raw_sends
            ]
        return super()._load_checkpoint_tuple(value)


_GRAPH = None  # 编译好的图单例（FastAPI 多线程共享，图本身线程安全）


def get_graph():
    """编译好的 supervisor 图单例（带 PostgresSaver）。API 层直接 invoke 它。"""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph(checkpointer=get_checkpointer())
    return _GRAPH
