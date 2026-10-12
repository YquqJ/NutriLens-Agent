"""
ORM 模型（SQLAlchemy 2.0 风格：Mapped + mapped_column）。

表结构总览：
    users              用户账号
    user_profiles      身体数据与目标（1:1 users）—— BMR/TDEE 等计算结果缓存于此
    conversations      会话（id 即 LangGraph thread_id，二者天然对齐）
    messages           会话消息（含 agent 名与工具调用轨迹，供前端渲染）
    diet_records       饮食记录（一次进食事件，按餐次）
    diet_record_items  饮食记录明细（多食物条目，含营养数据置信度）
    exercise_records   运动记录（MET 计算结果落库）
    foods              食物营养成分表（每 100g，内置中国食物成分表数据）
    knowledge_chunks   RAG 知识库切片（pgvector 向量列）

设计决策：
- 业务表与 LangGraph 的 checkpoint/store 表（由 PostgresSaver/PostgresStore
  自动创建）同库不同表，职责分离但部署只有一个实例；
- 所有"计算结果"（calories、bmr、met...）落库而非仅运行时计算，
  保证历史记录不随公式/模型升级而漂移。
"""

from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def utcnow() -> datetime:
    """时区感知的当前 UTC 时间。所有 timestamptz 列必须写 aware datetime：
    裸 datetime.now() 是 naive 本地时间，插入 timestamptz 时被 Postgres 按
    会话时区(UTC)重解读，本地时刻被整体当成 UTC 偏移 +8h（症状：当天新建的
    会话在侧栏显示成第二天，如 9/10 显示 9/11）。"""
    return datetime.now(timezone.utc)


class User(Base):
    """用户账号。密码只存 bcrypt 哈希。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    profile: Mapped["UserProfile | None"] = relationship(back_populates="user")
    plans: Mapped[list["Plan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base):
    """
    身体数据与目标档案。plan_agent 的 calculate_bmr_tdee 工具读取此表。

    字段说明：
    - activity_level：久坐/轻度/中度/高度 → 对应活动系数 1.2/1.375/1.55/1.725
    - goal：lose（减脂 -500 kcal）/ maintain（维持）/ gain（增肌 +300 kcal）
    - goal_note：自由文本，存放"对花生过敏""不吃香菜"等长期偏好
    - bmr/tdee/calorie_target：计算缓存，update 时由 service 层重算回填
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    gender: Mapped[str | None] = mapped_column(String(16))  # male / female
    age: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[float | None] = mapped_column(Float)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    activity_level: Mapped[str | None] = mapped_column(String(16))  # sedentary/light/moderate/active
    goal: Mapped[str | None] = mapped_column(String(16))  # lose/maintain/gain
    goal_note: Mapped[str] = mapped_column(Text, default="")
    # 计算缓存（Mifflin-St Jeor 公式结果，见 services/profile.py）
    bmr: Mapped[float | None] = mapped_column(Float)
    tdee: Mapped[float | None] = mapped_column(Float)
    calorie_target: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Conversation(Base):
    """
    会话。id 为 UUID 字符串，同时作为 LangGraph 的 thread_id ——
    这是刻意设计：conversation 即 thread，checkpointer 按 thread_id
    恢复对话状态，两套概念一一对齐。
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), default="新会话")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # 首次饮食确认挂起时暂存请求级性能指标，resume 完成后合并到 assistant 消息。
    pending_duration_ms: Mapped[int | None] = mapped_column(Integer)
    pending_input_tokens: Mapped[int | None] = mapped_column(Integer)
    pending_output_tokens: Mapped[int | None] = mapped_column(Integer)
    pending_total_tokens: Mapped[int | None] = mapped_column(Integer)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        order_by="Message.id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_conversations_user", "user_id", "updated_at"),)


class Message(Base):
    """
    一条对话消息。role: user / assistant / tool_trace。
    - agent_name：产出该消息的最后一个 agent（旧字段兼容）
    - agent_names：本轮参与的 agent 列表（JSON 字符串，前端渲染多个徽章）
    - tool_trace：本轮工具调用记录（JSON 字符串，前端折叠面板渲染）
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(Text)  # 该消息携带的食物图片（OSS URL）
    agent_name: Mapped[str | None] = mapped_column(String(32))
    agent_names: Mapped[str | None] = mapped_column(Text)
    tool_trace: Mapped[str | None] = mapped_column(Text)  # JSON 数组：[{name, args, result}]
    citations: Mapped[str | None] = mapped_column(Text)  # JSON 数组：QA 证据定位与切片正文
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Plan(Base):
    """用户当前启用的健康计划，由 plan_agent 的最终交付自动归档。"""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="plans")

    __table_args__ = (Index("ix_plans_user_active", "user_id", "is_active", "updated_at"),)


class DietRecord(Base):
    """
    一次进食记录（如"午餐"）。一条记录可含多个食物条目（1:N → items）。

    source 字段记录录入方式：image（拍照识别）/ text（文字描述）/ manual（表单手填），
    用于区分置信度语义。
    """

    __tablename__ = "diet_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)  # 归属日期（默认今天）
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # breakfast/lunch/dinner/snack
    source: Mapped[str] = mapped_column(String(16), default="manual")
    # 冗余总计字段：聚合查询免 join，写入时由 service 层同步维护
    total_calories: Mapped[float] = mapped_column(Float, default=0)
    total_protein: Mapped[float] = mapped_column(Float, default=0)
    total_fat: Mapped[float] = mapped_column(Float, default=0)
    total_carbs: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    items: Mapped[list["DietRecordItem"]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_diet_records_user_date", "user_id", "record_date"),)


class DietRecordItem(Base):
    """
    饮食记录的食物条目。营养数值 = foods 表每 100g 值 × grams / 100。

    confidence 记录营养数据来源（三档，前端可视化区分）：
    - db_exact  ：食物库精确命中
    - db_fuzzy  ：食物库模糊命中（如"手抓饼"匹配到"葱油饼"）
    - llm_estimate：库未命中，由 LLM 估算 —— 数值仅供参考
    """

    __tablename__ = "diet_record_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    diet_record_id: Mapped[int] = mapped_column(
        ForeignKey("diet_records.id", ondelete="CASCADE"), nullable=False
    )
    food_name: Mapped[str] = mapped_column(String(64), nullable=False)
    grams: Mapped[float] = mapped_column(Float, nullable=False)
    calories: Mapped[float] = mapped_column(Float, nullable=False)
    protein: Mapped[float] = mapped_column(Float, default=0)
    fat: Mapped[float] = mapped_column(Float, default=0)
    carbs: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[str] = mapped_column(String(16), default="db_exact")

    record: Mapped[DietRecord] = relationship(back_populates="items")


class ExerciseRecord(Base):
    """运动记录。热量消耗 = MET × 体重(kg) × 时长(h)，写入时固化。"""

    __tablename__ = "exercise_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    exercise_type: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    met: Mapped[float] = mapped_column(Float, nullable=False)  # 代谢当量
    calories_burned: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual/text
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (Index("ix_exercise_records_user_date", "user_id", "record_date"),)


class Food(Base):
    """
    食物营养成分表（每 100g 可食部）。
    数据来源：开源"中国食物成分表"整理数据集，seed 脚本导入 ~800-1000 条。

    alias 存常用别名（如"西红柿,番茄"），LIKE 检索时一并匹配，
    解决"番茄/西红柿""马铃薯/土豆"这类同物异名问题。
    """

    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="其他")  # 主食/肉类/蔬果/饮品...
    alias: Mapped[str] = mapped_column(Text, default="")  # 逗号分隔的别名列表
    calories: Mapped[float] = mapped_column(Float, nullable=False)  # kcal / 100g
    protein: Mapped[float] = mapped_column(Float, default=0)  # g / 100g
    fat: Mapped[float] = mapped_column(Float, default=0)
    carbs: Mapped[float] = mapped_column(Float, default=0)

    __table_args__ = (
        UniqueConstraint("name", name="uq_foods_name"),
        Index("ix_foods_name", "name"),
    )


class KnowledgeDocument(Base):
    """知识文档的导入清单。

    原始文件与切片分表：文档表记录来源、文件哈希和解析版本，切片表只保存
    检索所需的最小内容。这样同一文件重复导入可幂等跳过；源文件变更时也能
    精确删除旧切片再重建，而不是把整个知识库清空。
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_title: Mapped[str] = mapped_column(String(128), nullable=False)
    source_path: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)  # pdf / markdown
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base):
    """
    RAG 知识库切片。embedding 为 pgvector 向量列（text-embedding-v3，1024 维）。

    同表存 BM25 需要的关键词文本：混合检索的"向量路"走 embedding 列，
    "关键词路"用 rank_bm25 在内存索引（见 rag/retriever.py），
    避免依赖 PostgreSQL 中文分词扩展（zhparser 需自编译，Windows 不友好）。
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 文档是来源真相；切片不再重复存 source_title，避免同一字段两处失同步。
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)  # 切片正文
    topic: Mapped[str] = mapped_column(String(32), default="general")  # 主题分类（过滤用）
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(256))
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    embedding = mapped_column(Vector(1024))  # pgvector 向量，HNSW 索引在 DDL 后建

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "document_id", "content_hash", name="uq_knowledge_chunks_document_hash"
        ),
        Index("ix_knowledge_chunks_document", "document_id"),
    )
