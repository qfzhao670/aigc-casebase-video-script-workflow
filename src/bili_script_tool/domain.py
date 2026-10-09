"""Domain models shared by storage, workflows, and the user interface."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

from .errors import DataValidationError


@dataclass(frozen=True)
class VideoMetadata:
    uploader: str
    bvid: str
    title: str


@dataclass(frozen=True)
class CaseAnalysis:
    summary: str
    keywords: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseRecord:
    uploader: str
    bvid: str
    title: str
    text: str
    summary: str
    keywords: List[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CaseRecord":
        bvid = str(value.get("bvid", "")).strip()
        if not bvid:
            raise DataValidationError("案例记录缺少 bvid")

        raw_keywords = value.get("keywords", [])
        if isinstance(raw_keywords, str):
            keywords = [item.strip() for item in raw_keywords.split(",") if item.strip()]
        elif isinstance(raw_keywords, list):
            keywords = [str(item).strip() for item in raw_keywords if str(item).strip()]
        else:
            raise DataValidationError(f"案例 {bvid} 的 keywords 必须是数组或字符串")

        return cls(
            uploader=str(value.get("uploader", "Unknown")).strip() or "Unknown",
            bvid=bvid,
            title=str(value.get("title", "Untitled")).strip() or "Untitled",
            text=str(value.get("text", "")),
            summary=str(value.get("summary", "")),
            keywords=keywords,
        )

    def to_mapping(self) -> Dict[str, Any]:
        return {
            "uploader": self.uploader,
            "bvid": self.bvid,
            "title": self.title,
            "text": self.text,
            "summary": self.summary,
            "keywords": self.keywords,
        }
