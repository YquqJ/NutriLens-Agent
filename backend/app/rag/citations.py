"""RAG 证据定位与回答编号校验。

文档标题只能说明“来自哪份资料”，不能说明“哪一段支持这句话”。引用标签
由检索结果的文档、章节、页码和片段序号确定性生成，供工具轨迹、LLM 上下文
和最终用户回答共用，避免三处展示各自拼字符串而漂移。

生成模型只负责在结论旁选择引用编号，但它偶尔会把切片的页码、片段号
或自己臆测的序号写成 ``[n]``。因此最终回复出站前必须按本轮结构化证据
校验编号；不在证据集里的标记不能留给前端伪装成来源。
"""

import re


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


def citation_catalog_from_payloads(citations: list[dict]) -> str:
    """根据已实际引用的结构化证据生成唯一来源目录。"""
    if not citations:
        return ""
    lines = [
        f"[{citation['index']}] {citation['label']}" for citation in citations
    ]
    return "参考来源：\n" + "\n".join(lines)


def citation_catalog(results: list[dict]) -> str:
    """根据检索结果生成目录（兼容旧调用；QA 出站应使用已引用证据）。"""
    return citation_catalog_from_payloads(citation_payloads(results))


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


def sanitize_citation_markers(answer: str, citations: list[dict]) -> str:
    """移除回答中不存在于本轮证据集的 ``[n]`` 标记。

    有效标记保留给前端渲染为可点击引用；无效标记不应被静默映射到某个
    切片，否则会制造错误的证据关联。这里仅处理纯数字方括号，避免影响
    普通中文括号或 Markdown 链接。
    """
    valid_indexes = {citation["index"] for citation in citations}

    def replace(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) in valid_indexes else ""

    return re.sub(r"\[(\d+)\]", replace, answer)


def normalize_answer_citations(answer: str, citations: list[dict]) -> tuple[str, list[dict]]:
    """仅保留正文实际使用的证据，并按首次出现顺序重编连续编号。

    检索阶段的 top-k 是“候选证据”，不是“最终引用”。若直接把所有候选
    渲染到来源目录，会出现正文只有 [1][3][4]、目录却还有 [2][5][6] 的
    错位。此函数以正文中真实的引用标记为准：同一证据重复出现仍共享编号，
    未使用的候选不进入 SSE、数据库和前端抽屉。
    """
    by_index = {citation["index"]: citation for citation in citations}
    remapped_indexes: dict[int, int] = {}
    used_citations: list[dict] = []

    def replace(match: re.Match[str]) -> str:
        original_index = int(match.group(1))
        source = by_index.get(original_index)
        if source is None:
            return ""
        if original_index not in remapped_indexes:
            new_index = len(used_citations) + 1
            remapped_indexes[original_index] = new_index
            used_citations.append({**source, "index": new_index})
        return f"[{remapped_indexes[original_index]}]"

    return re.sub(r"\[(\d+)\]", replace, answer), used_citations


def strip_model_reference_catalog(answer: str) -> str:
    """移除模型自行输出在回答末尾的“参考来源”目录。

    目录必须由 ``citation_catalog`` 基于本轮检索结果唯一生成。若保留模型
    生成的目录，模型即使正确复述了来源，也会与程序追加的目录重复；若它
    复述错误，则会产生两套相互矛盾的引用。仅移除位于末尾的 Markdown
    标题或纯文本“参考来源：”段，不影响正文中的普通“来源”表述。
    """
    return re.sub(
        r"(?:\n\s*)+(?:#{1,6}\s*)?参考来源\s*[:：][\s\S]*\Z",
        "",
        answer,
    ).rstrip()
