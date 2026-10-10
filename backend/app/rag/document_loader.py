"""PDF 知识文档的提取与切片。

当前接入项目内置的营养、运动与健康管理知识 PDF。这里故意把“文件解析/切片”
和“向量化/数据库写入”分开：前者可离线、确定性测试；后者才依赖 embedding
服务与数据库。未来增加 Markdown、Word 或后台上传时，复用同一份切片契约。
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Literal

from pypdf import PdfReader


PDF_SOURCE_KEY = "nutrition_exercise_basics_pdf"
PDF_SOURCE_TITLE = "通用营养与运动科学常识知识库"
PDF_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "通用营养与运动科学常识知识库.pdf"
)
ADULT_DIET_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "成年人膳食决策与体重管理实践手册.pdf"
)
EXERCISE_SAFETY_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "运动处方、恢复与特殊人群安全手册.pdf"
)
NATIONAL_FITNESS_GUIDE_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "《全民健身指南》解读.pdf"
)
HEALTHY_CHINA_ACTION_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "健康中国行动.pdf"
)
DIETARY_GUIDELINES_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "平衡膳食八准则——核心推荐.pdf"
)
WEIGHT_MANAGEMENT_GUIDELINE_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "体重管理指导原则.pdf"
)
BALANCED_MEALS_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "会吃比好吃更重要：一日三餐的科学搭配法则.pdf"
)
PARSER_VERSION = "pdf-text-v1"

_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百]+章(?:\s+.*)?$")
_TOP_LEVEL_RE = re.compile(r"^\d{1,2}\.\s+.*$")
_SUBSECTION_RE = re.compile(r"^\d{1,2}\.\d{1,2}\s+.*$")
_APPENDIX_RE = re.compile(r"^附录(?:\s*[A-Z])?.*$")
_MAX_CHARS = 600
_OVERLAP_CHARS = 80
SplitMode = Literal["section_aware", "fixed"]


@dataclass(frozen=True)
class KnowledgeSource:
    source_key: str
    source_title: str
    path: Path


KNOWLEDGE_SOURCES = (
    KnowledgeSource(PDF_SOURCE_KEY, PDF_SOURCE_TITLE, PDF_SOURCE_PATH),
    KnowledgeSource(
        "adult_diet_weight_management_pdf",
        "成年人膳食决策与体重管理实践手册",
        ADULT_DIET_SOURCE_PATH,
    ),
    KnowledgeSource(
        "exercise_recovery_safety_pdf",
        "运动处方、恢复与特殊人群安全手册",
        EXERCISE_SAFETY_SOURCE_PATH,
    ),
    KnowledgeSource(
        "national_fitness_guide_pdf",
        "《全民健身指南》解读",
        NATIONAL_FITNESS_GUIDE_SOURCE_PATH,
    ),
    KnowledgeSource(
        "healthy_china_action_pdf",
        "健康中国行动",
        HEALTHY_CHINA_ACTION_SOURCE_PATH,
    ),
    KnowledgeSource(
        "dietary_guidelines_eight_pdf",
        "平衡膳食八准则——核心推荐",
        DIETARY_GUIDELINES_SOURCE_PATH,
    ),
    KnowledgeSource(
        "weight_management_guideline_pdf",
        "体重管理指导原则",
        WEIGHT_MANAGEMENT_GUIDELINE_SOURCE_PATH,
    ),
    KnowledgeSource(
        "balanced_meals_pdf",
        "会吃比好吃更重要：一日三餐的科学搭配法则",
        BALANCED_MEALS_SOURCE_PATH,
    ),
)


@dataclass(frozen=True)
class ExtractedChunk:
    """一条可直接向量化的、带可追溯定位信息的知识切片。"""

    content: str
    page_number: int
    section: str
    chunk_index: int

    @property
    def content_hash(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """以流式读取计算源文件哈希，避免大文件一次性载入内存。"""
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _is_heading(line: str) -> bool:
    return bool(
        _CHAPTER_RE.match(line)
        or _TOP_LEVEL_RE.match(line)
        or _SUBSECTION_RE.match(line)
        or _APPENDIX_RE.match(line)
    )


def _split_text(text: str) -> list[str]:
    """优先按原始行累积；单行过长时使用小重叠窗口避免语义被硬截断。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for line in lines:
        if len(line) > _MAX_CHARS:
            flush()
            start = 0
            while start < len(line):
                end = start + _MAX_CHARS
                chunks.append(line[start:end])
                if end >= len(line):
                    break
                start = end - _OVERLAP_CHARS
            continue

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= _MAX_CHARS:
            current = candidate
        else:
            flush()
            current = line
    flush()
    return chunks


def extract_pdf_chunks(
    path: Path = PDF_SOURCE_PATH,
    *,
    split_mode: SplitMode = "section_aware",
) -> tuple[int, list[ExtractedChunk]]:
    """提取 PDF 文本层并按页码、章节切片。

    不做 OCR 兜底：当前资料是有文本层的 PDF；扫描件应在未来上传管线中进入
    独立 OCR 分支，不能把“提取为空”静默地当成可入库文档。
    """
    if split_mode not in {"section_aware", "fixed"}:
        raise ValueError(f"未知切分模式：{split_mode}")
    if not path.is_file():
        raise FileNotFoundError(f"知识文档不存在：{path}")

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError("知识文档已加密，无法导入")

    chunks: list[ExtractedChunk] = []
    current_chapter = "未标注章节"
    current_section = current_chapter

    for page_number, page in enumerate(reader.pages, start=1):
        text = _normalize_text(page.extract_text() or "")
        if not text:
            raise ValueError(f"第 {page_number} 页未提取到文本；该文件需要 OCR 后再导入")

        if split_mode == "fixed":
            for content in _split_text(text):
                chunks.append(
                    ExtractedChunk(
                        content=content,
                        page_number=page_number,
                        section=f"page:{page_number}",
                        chunk_index=len(chunks),
                    )
                )
            continue

        section_blocks: list[tuple[str, str]] = []
        lines: list[str] = []

        def flush_block() -> None:
            if lines:
                section_blocks.append((current_section, "\n".join(lines)))
                lines.clear()

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if _is_heading(line):
                flush_block()
                if _CHAPTER_RE.match(line) or _TOP_LEVEL_RE.match(line):
                    current_chapter = line
                    current_section = line
                elif _SUBSECTION_RE.match(line):
                    current_section = f"{current_chapter} / {line}"
                else:
                    current_section = line
            lines.append(line)
        flush_block()

        for section, block in section_blocks:
            for content in _split_text(block):
                # section 前缀保证切片独立被召回时也携带语境。
                if not content.startswith(section):
                    content = f"{section}\n{content}"
                chunks.append(
                    ExtractedChunk(
                        content=content,
                        page_number=page_number,
                        section=section,
                        chunk_index=len(chunks),
                    )
                )

    if not chunks:
        raise ValueError("文档没有生成任何知识切片")
    return len(reader.pages), chunks
