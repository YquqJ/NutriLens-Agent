"""Build the two Chinese RAG evaluation PDFs from maintainable Markdown sources."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "knowledge_sources"
OUTPUT_DIR = ROOT / "data" / "knowledge"
FONT_REGULAR = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
FONT_SERIF = Path(r"C:\Windows\Fonts\NotoSerifSC-VF.ttf")

DOCUMENTS = (
    (
        SOURCE_DIR / "adult_diet_weight_management.md",
        OUTPUT_DIR / "成年人膳食决策与体重管理实践手册.pdf",
        colors.HexColor("#176B5B"),
    ),
    (
        SOURCE_DIR / "exercise_recovery_safety.md",
        OUTPUT_DIR / "运动处方、恢复与特殊人群安全手册.pdf",
        colors.HexColor("#A3482B"),
    ),
)


def _register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("NotoSansSC", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("NotoSerifSC", str(FONT_SERIF)))


def _inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    return escaped


def _styles(accent: colors.Color) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="NotoSerifSC",
            fontSize=25,
            leading=36,
            textColor=accent,
            alignment=TA_CENTER,
            spaceAfter=12 * mm,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=base["BodyText"],
            fontName="NotoSansSC",
            fontSize=11,
            leading=19,
            textColor=colors.HexColor("#4B5563"),
            alignment=TA_CENTER,
            spaceAfter=5 * mm,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading1"],
            fontName="NotoSerifSC",
            fontSize=17,
            leading=25,
            textColor=accent,
            spaceBefore=7 * mm,
            spaceAfter=3 * mm,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading2"],
            fontName="NotoSansSC",
            fontSize=12,
            leading=18,
            textColor=colors.HexColor("#263238"),
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="NotoSansSC",
            fontSize=9.6,
            leading=16.5,
            textColor=colors.HexColor("#202428"),
            alignment=TA_LEFT,
            spaceAfter=2.6 * mm,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="NotoSansSC",
            fontSize=9.4,
            leading=16,
            leftIndent=6 * mm,
            firstLineIndent=-3.5 * mm,
            textColor=colors.HexColor("#202428"),
            spaceAfter=1.4 * mm,
            wordWrap="CJK",
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="NotoSansSC",
            fontSize=9.3,
            leading=16,
            leftIndent=5 * mm,
            rightIndent=5 * mm,
            borderColor=accent,
            borderWidth=0.8,
            borderPadding=8,
            backColor=colors.HexColor("#F4F7F6"),
            textColor=colors.HexColor("#263238"),
            spaceBefore=2 * mm,
            spaceAfter=4 * mm,
            wordWrap="CJK",
        ),
        "reference": ParagraphStyle(
            "Reference",
            parent=base["BodyText"],
            fontName="NotoSansSC",
            fontSize=7.8,
            leading=12.5,
            textColor=colors.HexColor("#4B5563"),
            leftIndent=4 * mm,
            firstLineIndent=-4 * mm,
            spaceAfter=1.5 * mm,
            wordWrap="CJK",
        ),
    }


class HandbookTemplate(BaseDocTemplate):
    def __init__(self, filename: Path, title: str, accent: colors.Color):
        self.short_title = title
        self.accent = accent
        super().__init__(
            str(filename),
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=22 * mm,
            bottomMargin=18 * mm,
            title=title,
            author="NutriLens-Agent",
            subject="RAG evaluation knowledge document",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="body",
        )
        self.addPageTemplates(
            PageTemplate(id="main", frames=[frame], onPage=self._draw_page)
        )

    def _draw_page(self, canvas, doc) -> None:
        canvas.saveState()
        width, height = A4
        if doc.page > 1:
            canvas.setStrokeColor(self.accent)
            canvas.setLineWidth(0.6)
            canvas.line(20 * mm, height - 14 * mm, width - 20 * mm, height - 14 * mm)
            canvas.setFont("NotoSansSC", 7.5)
            canvas.setFillColor(colors.HexColor("#6B7280"))
            canvas.drawString(20 * mm, height - 10.5 * mm, self.short_title[:28])
            canvas.drawRightString(width - 20 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()


def _parse_markdown(path: Path, accent: colors.Color):
    styles = _styles(accent)
    lines = path.read_text(encoding="utf-8").splitlines()
    title = lines[0].removeprefix("# ").strip()
    story = [Spacer(1, 25 * mm), Paragraph(_inline_markup(title), styles["cover_title"])]
    in_cover = True
    in_references = False
    section_count = 0

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            story.extend([Spacer(1, 12 * mm), PageBreak()])
            in_cover = False
            continue
        if not stripped:
            continue
        if in_cover:
            story.append(Paragraph(_inline_markup(stripped), styles["cover_meta"]))
            continue
        if stripped.startswith("## "):
            heading = stripped[3:]
            if section_count:
                story.append(PageBreak())
            section_count += 1
            in_references = heading == "参考资料"
            story.append(Paragraph(_inline_markup(heading), styles["h2"]))
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(_inline_markup(stripped[4:]), styles["h3"]))
            continue
        if stripped.startswith("> "):
            story.append(Paragraph(_inline_markup(stripped[2:]), styles["callout"]))
            continue
        if stripped.startswith("- "):
            story.append(
                Paragraph(f"• {_inline_markup(stripped[2:])}", styles["bullet"])
            )
            continue
        if re.match(r"^\d+\. ", stripped):
            story.append(Paragraph(_inline_markup(stripped), styles["bullet"]))
            continue

        style = styles["reference"] if in_references else styles["body"]
        story.append(Paragraph(_inline_markup(stripped), style))

    return title, story


def build_pdf(source: Path, output: Path, accent: colors.Color) -> None:
    title, story = _parse_markdown(source, accent)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = HandbookTemplate(output, title, accent)
    document.build(story)


def main() -> None:
    _register_fonts()
    for source, output, accent in DOCUMENTS:
        build_pdf(source, output, accent)
        print(output)


if __name__ == "__main__":
    main()
