"""
用户档案 service：BMR / TDEE / 每日热量目标计算。

公式出处（面试口径）：
- BMR：Mifflin-St Jeor 公式（1990），目前公认比 Harris-Benedict 更准：
    男：BMR = 10×体重(kg) + 6.25×身高(cm) − 5×年龄 + 5
    女：BMR = 10×体重(kg) + 6.25×身高(cm) − 5×年龄 − 161
- TDEE = BMR × 活动系数（久坐1.2 / 轻度1.375 / 中度1.55 / 高度1.725）
- 热量目标按目标调整：减脂 −500 kcal（约每周减 0.5kg 脂肪的理论缺口），
  增肌 +300 kcal，维持不变。

工程决策：这些计算是确定性数学，用纯函数实现并有单测，
LLM 只负责"解释"计算结果，绝不做算术 —— 避免 LLM 算错 42 的经典问题。
"""

ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,  # 久坐，几乎不运动
    "light": 1.375,    # 每周 1-3 次轻量运动
    "moderate": 1.55,  # 每周 3-5 次中等强度运动
    "active": 1.725,   # 每周 6-7 次高强度运动
}

# 目标热量调整幅度（kcal/天）
GOAL_ADJUSTMENT: dict[str, float] = {
    "lose": -500,
    "maintain": 0,
    "gain": 300,
}


def calc_bmr(gender: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor 公式计算基础代谢率（kcal/天）。gender: male/female。"""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(base + 5 if gender == "male" else base - 161, 1)


def calc_tdee(bmr: float, activity_level: str) -> float:
    """TDEE = BMR × 活动系数。未知活动水平按久坐处理（保守估计）。"""
    factor = ACTIVITY_FACTORS.get(activity_level, ACTIVITY_FACTORS["sedentary"])
    return round(bmr * factor, 1)


def calc_calorie_target(tdee: float, goal: str) -> float:
    """每日热量目标：按减脂/维持/增肌调整。目标未知按维持。"""
    adj = GOAL_ADJUSTMENT.get(goal, 0)
    return round(tdee + adj, 1)


def recalc_profile_metrics(
    gender: str | None,
    weight_kg: float | None,
    height_cm: float | None,
    age: int | None,
    activity_level: str | None,
    goal: str | None,
) -> tuple[float | None, float | None, float | None]:
    """
    档案更新时重算 (bmr, tdee, calorie_target)。
    身体数据不完整（任一缺失）时返回 (None, None, None)——
    存疑不计算好过给一个误导性的数字。
    """
    if not all([gender, weight_kg, height_cm, age]):
        return None, None, None
    bmr = calc_bmr(gender, weight_kg, height_cm, age)  # type: ignore[arg-type]
    tdee = calc_tdee(bmr, activity_level or "sedentary")
    target = calc_calorie_target(tdee, goal or "maintain")
    return bmr, tdee, target
