"""
图片记录链路回归测试 —— 不依赖真实 LLM / 图片。

背景 bug：用户发「这是我的晚饭」+ 食物照片，supervisor（纯文本路由、看不到图）
把指代消解误判成「把上一轮刚记录的香肠改成晚餐」，diet_agent 照单执行，确认卡里
出现幻觉的「香肠」而非图片里的真实食物。

根因：图片识别依赖 react agent 自主调 analyze_food_image 工具，受历史上下文
干扰时会被漏调、改去幻觉食物。修复：把感知（vision）从决策（agent 路由）剥离——
新增 analyze_image 前置节点，带图时确定性先识别、结果写 recognized_foods，再
注入 supervisor（改写 task 以真实食物为准）与 diet_agent（按识别结果落库）。
"""

from langchain_core.messages import HumanMessage

from app.agents.diet_agent import _diet_prompt, make_analyze_image_node
from app.agents.supervisor import make_supervisor_node


def test_analyze_image_node_injects_recognized_foods():
    node = make_analyze_image_node(recognizer=lambda url: [
        {"food_name": "白切鸡", "estimated_grams": 150.0, "visual_description": "鸡"}
    ])
    out = node({"image_url": "https://x/y.jpg"})
    assert out["recognized_foods"][0]["food_name"] == "白切鸡"


def test_analyze_image_node_noop_without_image():
    node = make_analyze_image_node(recognizer=lambda url: [])
    out = node({"image_url": None})
    assert out["recognized_foods"] is None


def test_supervisor_injects_recognized_foods():
    captured = {}

    class _StubRouter:
        def invoke(self, msgs):
            captured["msgs"] = msgs

            class _D:
                next_agent = "diet_agent"
                task = "记录晚餐"

            return _D()

    node = make_supervisor_node(router=_StubRouter())
    node(
        {
            "messages": [HumanMessage(content="这是我的晚饭")],
            "image_url": "https://x/y.jpg",
            "recognized_foods": [{"food_name": "白切鸡", "estimated_grams": 150.0}],
            "hop_count": 0,
            "agent_trace": [],
        }
    )
    assert any(
        isinstance(m, tuple)
        and m[0] == "system"
        and "白切鸡" in m[1]
        and "以这些食物为准" in m[1]
        for m in captured["msgs"]
    )


def test_diet_prompt_uses_recognized_foods():
    state = {
        "messages": [HumanMessage(content="这是我的晚饭")],
        "image_url": "https://x/y.jpg",
        "recognized_foods": [{"food_name": "白切鸡", "estimated_grams": 150.0}],
        "task": "记录晚餐",
    }
    system = _diet_prompt(state)[0].content
    assert "图片识别结果" in system
    assert "白切鸡" in system
    assert "不要重复调用 analyze_food_image" in system