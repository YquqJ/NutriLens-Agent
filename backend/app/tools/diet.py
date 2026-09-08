"""
饮食域工具（diet_agent 的工具集）。

关键设计（面试重点）：
1. 感知与查询分离：analyze_food_image 只做"看见什么"（VL 模型），
   search_food 只做"营养值是多少"（数据库）。
   不让 VL 模型直接报营养数值 —— 食物成分是事实数据，
   走数据库可溯源、可更新，模型幻觉的营养值无法校准。
2. HITL：create_diet_record 写库前 interrupt() 请求用户确认。
   AI 识别的克数是估算，让用户看一眼再入库，
   这是 LangGraph "human-in-the-loop" 的教科书用法。
3. 置信度分级贯穿：db_exact / db_fuzzy / llm_estimate 落库并透出前端。
"""

from datetime import date
from typing import Optional

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.agents.llm import get_vision_llm
from app.services import diet as diet_service
from app.tools.context import get_current_user_id, get_session


# ======================================================================
# 图片识别（感知层）
# ======================================================================
class FoodImageItem(BaseModel):
    """VL 模型识别出的单个食物条目。"""

    food_name: str = Field(description="食物中文名，尽量用常见叫法，如'牛肉面'而非'面食'")
    estimated_grams: float = Field(description="估算的分量克数，参考碗/盘尺寸")
    visual_description: str = Field(description="视觉描述，如'一大碗，含牛肉片和青菜'")


class FoodImageResult(BaseModel):
    """qwen-vl-max 结构化输出约束。强制 JSON，杜绝自由发挥。"""

    items: list[FoodImageItem] = Field(description="图中识别到的食物列表")


@tool
def analyze_food_image(image_url: str) -> dict:
    """
    识别食物图片中的食物与估算分量。输入为图片 URL。
    返回识别到的食物列表（名称/克数/视觉描述）。不做营养计算。
    """
    llm = get_vision_llm().with_structured_output(FoodImageResult)
    # 多模态消息格式：image_url 走 OpenAI 兼容协议（DashScope 支持公网 URL 直读）
    result: FoodImageResult = llm.invoke(
        [
            (
                "user",
                [
                    {"type": "text", "text": "识别这张食物图片。列出每种食物的名称、估算克数（参考餐具尺寸）和视觉描述。"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            )
        ]
    )
    return {
        "items": [
            {
                "food_name": it.food_name,
                "estimated_grams": it.estimated_grams,
                "visual_description": it.visual_description,
            }
            for it in result.items
        ]
    }


# ======================================================================
# 食物检索（数据层）
# ======================================================================
@tool
def search_food(query: str, top_k: int = 5) -> dict:
    """
    按名称检索食物营养数据（每100g含热量/蛋白质/脂肪/碳水）。
    用于查食物的营养值或确认库中是否存在某种食物。
    返回 match_type: exact(精确命中)/prefix(前缀匹配)/fuzzy(模糊匹配)。
    """
    with get_session() as db:
        results = diet_service.search_foods(db, query, top_k)
    if not results:
        return {"found": False, "results": [], "hint": "食物库未命中，可用常识估算并标注 llm_estimate"}
    return {"found": True, "results": results}


# ======================================================================
# 饮食记录（写入层，含 HITL）
# ======================================================================
class DietItemIn(BaseModel):
    """LLM 生成的食物条目（写库前的中间结构）。"""

    food_name: str
    grams: float = Field(gt=0, le=3000)
    calories: float = Field(ge=0)
    protein: float = Field(default=0, ge=0)
    fat: float = Field(default=0, ge=0)
    carbs: float = Field(default=0, ge=0)
    confidence: str = Field(default="db_exact", description="db_exact/db_fuzzy/llm_estimate")


@tool
def create_diet_record(
    items: list[DietItemIn],
    meal_type: str,
    record_date: Optional[str] = None,
) -> dict:
    """
    写入一条饮食记录（写库前会请求用户确认，确认后落库）。
    参数：
    - items: 食物条目列表（先用 search_food 查营养值，按克数换算后传入）
    - meal_type: breakfast/lunch/dinner/snack
    - record_date: YYYY-MM-DD，缺省今天
    """
    # ---- 1. 组装确认草稿（纯计算，可重复执行，无副作用） ----
    draft = [i.model_dump() for i in items]

    # ---- 2. HITL：请求用户确认/编辑 ----
    # interrupt() 第一次执行时抛出 GraphInterrupt 挂起整张图，
    # 草稿通过 SSE interrupt 事件推给前端渲染确认卡片；
    # 前端确认后 API 层用 Command(resume=...) 恢复执行 ——
    # 恢复时本工具从头重跑，interrupt() 直接返回 resume 值：
    #   - dict（可能被用户编辑过的条目）→ 继续落库
    #   - False（用户点了取消）→ 不写库
    confirmed = interrupt(
        {
            "type": "diet_confirm",
            "meal_type": meal_type,
            "record_date": record_date or date.today().isoformat(),
            "items": draft,
        }
    )

    if confirmed is False:
        return {"status": "cancelled", "message": "用户取消了本次记录"}

    # 用户可能编辑过克数/删除条目 —— 以确认结果为准
    final_items = confirmed["items"] if isinstance(confirmed, dict) else draft

    # ---- 3. 落库 ----
    user_id = get_current_user_id()
    with get_session() as db:
        result = diet_service.create_diet_record(
            db,
            user_id=user_id,
            meal_type=meal_type,
            items=final_items,
            record_date=date.fromisoformat(record_date) if record_date else None,
            source="agent",
        )
    return {"status": "created", **result}


# ======================================================================
# 饮食查询（读取层）
# ======================================================================
@tool
def get_diet_records(record_date: Optional[str] = None) -> dict:
    """
    查询用户某天的饮食记录。参数为 YYYY-MM-DD，缺省今天。
    返回记录列表与营养总计（含各餐次明细）。
    """
    user_id = get_current_user_id()
    with get_session() as db:
        records = diet_service.get_diet_records(
            db, user_id, date.fromisoformat(record_date) if record_date else date.today()
        )
        summary = diet_service.get_daily_summary(
            db, user_id, date.fromisoformat(record_date) if record_date else date.today()
        )
    return {"records": records, "daily_summary": summary}


@tool
def delete_diet_record(record_id: int) -> dict:
    """删除一条饮食记录（需要记录 id，先 get_diet_records 查到）。"""
    user_id = get_current_user_id()
    with get_session() as db:
        ok = diet_service.delete_diet_record(db, user_id, record_id)
    return {"status": "deleted" if ok else "not_found"}
