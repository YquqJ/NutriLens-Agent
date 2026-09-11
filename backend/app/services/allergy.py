"""饮食记录的确定性过敏风险检测。

过敏安全判断不能交给 LLM：模型可能因为历史上下文拒绝已发生的饮食记录，
也可能遗漏风险。这里把用户档案中的常见过敏原与待记录食物做可解释的规则匹配，
只负责生成风险提示，不替用户决定是否记录。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.db.models import UserProfile


# 只把带有安全语义的档案内容视为过敏声明，避免“喜欢花生”之类普通偏好误报。
_ALLERGY_MARKERS = (
    "过敏",
    "过敏原",
    "不耐受",
    "allergy",
    "allergic",
    "intolerant",
)

# 规则按“档案关键词 → 食物关键词”组织。关键词使用常见中文/英文别名，
# 规则结果会把原始档案关键词和命中的食物名称一起返回，便于前端解释。
_ALLERGEN_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "海鲜",
        ("海鲜", "水产", "甲壳类", "贝类", "shellfish", "seafood"),
        (
            "虾",
            "蟹",
            "螃蟹",
            "龙虾",
            "虾仁",
            "贝",
            "蛤",
            "扇贝",
            "牡蛎",
            "生蚝",
            "鱿鱼",
            "章鱼",
            "鱼",
            "shrimp",
            "prawn",
            "crab",
            "lobster",
            "shellfish",
            "fish",
        ),
    ),
    ("虾", ("虾", "shrimp", "prawn"), ("虾", "shrimp", "prawn")),
    ("蟹", ("蟹", "螃蟹", "crab"), ("蟹", "螃蟹", "crab")),
    ("鱼", ("鱼", "fish"), ("鱼", "三文鱼", "鲈鱼", "鳕鱼", "金枪鱼", "fish")),
    ("贝类", ("贝类", "贝", "蛤", "扇贝", "牡蛎", "生蚝", "shellfish"), ("贝", "蛤", "扇贝", "牡蛎", "生蚝", "shellfish")),
    ("花生", ("花生", "peanut", "peanuts"), ("花生", "peanut")),
    ("坚果", ("坚果", "nut", "nuts", "tree nut"), ("坚果", "杏仁", "核桃", "腰果", "榛子", "nut")),
    ("牛奶/乳制品", ("牛奶", "乳制品", "乳糖", "milk", "dairy", "lactose"), ("牛奶", "奶", "乳", "奶酪", "酸奶", "milk", "cheese", "yogurt")),
    ("鸡蛋", ("鸡蛋", "蛋类", "蛋", "egg", "eggs"), ("鸡蛋", "蛋", "egg")),
    ("大豆", ("大豆", "黄豆", "豆制品", "soy", "soya"), ("大豆", "黄豆", "豆腐", "豆浆", "soy")),
    ("芝麻", ("芝麻", "sesame"), ("芝麻", "sesame")),
    ("小麦/麸质", ("小麦", "麸质", "面筋", "gluten", "wheat"), ("小麦", "面包", "面条", "馒头", "面粉", "面筋", "gluten", "wheat")),
)


def _contains(text: str, keyword: str) -> bool:
    """大小写不敏感地匹配中文或英文关键词。"""
    return keyword.lower() in text.lower()


def _has_allergy_semantics(note: str) -> bool:
    return any(_contains(note, marker) for marker in _ALLERGY_MARKERS)


def assess_food_allergy_risks(goal_note: str | None, food_names: Iterable[str]) -> list[dict]:
    """根据档案备注和食物名返回结构化风险列表。

    这是纯函数，便于单测。没有明确过敏/不耐受语义，或没有匹配食物时返回空列表。
    """
    note = (goal_note or "").strip()
    if not note or not _has_allergy_semantics(note):
        return []

    names = [str(name).strip() for name in food_names if str(name).strip()]
    risks: list[dict] = []
    for allergen, note_terms, food_terms in _ALLERGEN_RULES:
        matched_note_terms = [term for term in note_terms if _contains(note, term)]
        if not matched_note_terms:
            continue
        matched_foods = [
            name
            for name in names
            if any(_contains(name, term) for term in food_terms)
        ]
        if not matched_foods:
            continue
        # “鱼香肉丝”不是鱼类，避免海鲜规则对该固定菜名误报。
        if allergen == "海鲜":
            matched_foods = [name for name in matched_foods if "鱼香" not in name]
        if not matched_foods:
            continue
        unique_foods = list(dict.fromkeys(matched_foods))
        risks.append(
            {
                "allergen": allergen,
                "profile_terms": matched_note_terms,
                "foods": unique_foods,
                "message": (
                    f"档案标注对{allergen}过敏，本次待记录食物包含："
                    f"{'、'.join(unique_foods)}。"
                ),
            }
        )
    return risks


def assess_user_food_allergy_risks(
    db: Session, user_id: int, food_names: Iterable[str]
) -> list[dict]:
    """读取用户档案后执行风险检测。"""
    profile = db.get(UserProfile, user_id)
    return assess_food_allergy_risks(profile.goal_note if profile else "", food_names)
