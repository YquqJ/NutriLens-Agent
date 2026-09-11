"""RAG 证据定位的统一格式化。

文档标题只能说明“来自哪份资料”，不能说明“哪一段支持这句话”。引用标签
由检索结果的文档、章节、页码和片段序号确定性生成，供工具轨迹、LLM 上下文
和最终用户回答共用，避免三处展示各自拼字符串而漂移。
"""


def citation_label(result: dict) -> str:
    """将一条检索结果格式化为人可核验的证据定位。"""
    title = result.get("source_title") or "未命名文档"
    section = result.get("section") or "未标注章节"
    page = result.get("page_number")
    chunk_index = result.get("chunk_index")

    locator = [section]
    if page is not None:
        locator.append(f"第 {page} 页")
    if chunk_index is not None:
        locator.append(f"片段 {chunk_index + 1}")
    return f"《{title}》· " + " · ".join(locator)


def citation_catalog(results: list[dict]) -> str:
    """生成与回答中 [1][2] 一一对应的确定性引用对照表。"""
    citations = citation_payloads(results)
    if not citations:
        return ""
    lines = [
        f"[{citation['index']}] {citation['label']}" for citation in citations
    ]
    return "参考来源：\n" + "\n".join(lines)


def citation_payloads(results: list[dict]) -> list[dict]:
    """生成可透传给前端抽屉的结构化证据，不让 UI 反向解析回答文本。"""
    return [
        {
            "index": index,
            "label": citation_label(result),
            "source_title": result.get("source_title") or "未命名文档",
            "section": result.get("section") or "未标注章节",
            "page_number": result.get("page_number"),
            "chunk_index": result.get("chunk_index"),
            "content": result.get("content") or "",
        }
        for index, result in enumerate(results, start=1)
    ]
