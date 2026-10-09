"""All DashScope interactions and prompt construction."""

import json
import re
from typing import Any, Iterable, List, Sequence

from ..domain import CaseAnalysis, CaseRecord
from ..errors import AIServiceError, DependencyError


class DashScopeService:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _generation_class(self) -> Any:
        try:
            from dashscope import Generation
        except ImportError as exc:
            raise DependencyError(
                "未安装 dashscope。请运行对应平台的初始化脚本。"
            ) from exc
        return Generation

    def complete(self, prompt: str, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        generation = self._generation_class()
        response = generation.call(
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            result_format="message",
        )
        status_code = getattr(response, "status_code", None)
        if status_code != 200:
            code = getattr(response, "code", "unknown")
            message = getattr(response, "message", "unknown error")
            raise AIServiceError(f"DashScope 请求失败：{code} - {message}")

        try:
            return response.output.choices[0].message.content.strip()
        except (AttributeError, IndexError, TypeError) as exc:
            raise AIServiceError("DashScope 返回了无法识别的响应格式") from exc

    def analyze_transcript(self, transcript: str) -> CaseAnalysis:
        prompt = f"""请分析以下视频口播转写文本，并只返回标准 JSON 对象。

要求：
1. summary：约 150 字，概括核心内容、账号人设、语言风格和文字特点。
2. keywords：不超过 15 个关键词，覆盖主题、国家或实体、语言风格。

返回格式：
{{"summary": "...", "keywords": ["..."]}}

转写文本：
{transcript[:15000]}
"""
        content = self.complete(
            prompt,
            system_prompt="你是视频内容分析和 JSON 数据提取助手。",
        )
        value = _parse_json(content)
        if not isinstance(value, dict):
            raise AIServiceError("案例分析结果不是 JSON 对象")

        summary = str(value.get("summary", "")).strip()
        keywords_value = value.get("keywords", [])
        if not summary or not isinstance(keywords_value, list):
            raise AIServiceError("案例分析结果缺少 summary 或合法的 keywords")
        keywords = [str(item).strip() for item in keywords_value if str(item).strip()]
        return CaseAnalysis(summary=summary, keywords=keywords[:15])

    def select_cases(
        self,
        cases: Sequence[CaseRecord],
        requirement: str,
        top_n: int,
    ) -> List[str]:
        candidates = _prefilter_cases(cases, requirement, limit=max(80, top_n * 20))
        summaries = []
        for case in candidates:
            summaries.append(
                "\n".join(
                    [
                        f"bvid: {case.bvid}",
                        f"作者: {case.uploader}",
                        f"标题: {case.title}",
                        f"摘要: {case.summary}",
                        f"关键词: {', '.join(case.keywords)}",
                    ]
                )
            )
        summaries_text = "\n\n".join(summaries)

        prompt = f"""下面是经过初筛的视频文案案例：

{summaries_text}

用户需求：{requirement}

请选择最符合需求风格的 {top_n} 个案例。
只返回包含 bvid 的 JSON 数组，不要解释。例如：["BV1...", "BV2..."]
"""
        value = _parse_json(self.complete(prompt, system_prompt="你是专业的视频内容策划。"))
        if not isinstance(value, list):
            raise AIServiceError("案例筛选结果不是 JSON 数组")

        valid_ids = {case.bvid for case in cases}
        selected = []
        for item in value:
            bvid = str(item).strip()
            if bvid in valid_ids and bvid not in selected:
                selected.append(bvid)
        return selected[:top_n]

    def generate_script(
        self,
        templates: Iterable[str],
        outline: str,
        requirements: str,
    ) -> str:
        templates_text = "\n\n".join(
            f"<template>\n{text}\n</template>" for text in templates if text.strip()
        )
        if not templates_text:
            raise AIServiceError("所选案例中没有可用的文案正文")

        prompt = f"""下面是优秀的视频文案脚本模板：
{templates_text}

下面是本次视频的详细大纲和相应数据：
<outline>
{outline}
</outline>

请参考模板的语感、节奏和叙事结构，结合大纲撰写一篇完整视频文案。

具体要求：
{requirements}
"""
        return self.complete(prompt, system_prompt="你是专业的视频文案编剧。")


def _parse_json(content: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(cleaned):
            if character not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise AIServiceError("模型返回内容中没有合法 JSON")


def _prefilter_cases(
    cases: Sequence[CaseRecord], requirement: str, limit: int
) -> List[CaseRecord]:
    """Reduce very large libraries before the LLM call using transparent text overlap."""
    terms = _search_terms(requirement)
    if not terms or len(cases) <= limit:
        return list(cases[:limit])

    scored = []
    for index, case in enumerate(cases):
        title = case.title.lower()
        keywords = " ".join(case.keywords).lower()
        summary = case.summary.lower()
        score = sum(
            (6 if term in keywords else 0)
            + (4 if term in title else 0)
            + (2 if term in summary else 0)
            for term in terms
        )
        scored.append((score, -index, case))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [case for _, _, case in scored[:limit]]


def _search_terms(text: str) -> List[str]:
    lowered = text.lower()
    terms = re.findall(r"[a-z0-9]{2,}", lowered)
    for segment in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(segment) == 1:
            terms.append(segment)
        else:
            terms.extend(segment[index : index + 2] for index in range(len(segment) - 1))
    return list(dict.fromkeys(terms))
