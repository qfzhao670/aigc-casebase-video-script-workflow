"""Application workflows that coordinate storage, media, and AI services."""

from pathlib import Path
from typing import Callable, Iterable, List, Optional

from ..domain import CaseRecord
from ..errors import ApplicationError, DataValidationError
from .ai_service import DashScopeService
from .case_repository import CaseRepository
from .media_service import MediaService


LogCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


class CaseBuildWorkflow:
    def __init__(
        self,
        repository: CaseRepository,
        media: MediaService,
        ai: DashScopeService,
        log: Optional[LogCallback] = None,
    ):
        self.repository = repository
        self.media = media
        self.ai = ai
        self.log = log or (lambda _message: None)

    def run(self, bvids: Iterable[str], should_stop: Optional[StopCallback] = None) -> None:
        stop_requested = should_stop or (lambda: False)
        normalized_ids = list(dict.fromkeys(item.strip() for item in bvids if item.strip()))
        existing_ids = self.repository.existing_bvids()
        self.log(f"案例库已有 {len(existing_ids)} 条记录。")
        self.media.check_dependencies()

        for index, bvid in enumerate(normalized_ids, start=1):
            if stop_requested():
                self.log("任务已停止。")
                break
            if bvid in existing_ids:
                self.log(f"[{index}/{len(normalized_ids)}] 已存在，跳过：{bvid}")
                continue

            try:
                self.log(f"[{index}/{len(normalized_ids)}] 开始处理：{bvid}")
                metadata = self.media.get_metadata(bvid)
                audio_path = self.media.download_audio(metadata)
                transcript = self.media.transcribe(audio_path)
                self.log("正在生成摘要和关键词……")
                analysis = self.ai.analyze_transcript(transcript)
                self.repository.append(
                    CaseRecord(
                        uploader=metadata.uploader,
                        bvid=metadata.bvid,
                        title=metadata.title,
                        text=transcript,
                        summary=analysis.summary,
                        keywords=analysis.keywords,
                    )
                )
                existing_ids.add(metadata.bvid)
                self.log(f"入库成功：{metadata.title}")
            except ApplicationError as exc:
                self.log(f"处理失败，可稍后重试 {bvid}：{exc}")


class ScriptGenerationWorkflow:
    def __init__(self, repository: CaseRepository, ai: DashScopeService):
        self.repository = repository
        self.ai = ai

    def select_cases(self, requirement: str, top_n: int) -> List[CaseRecord]:
        cases = self.repository.load_all()
        if not cases:
            raise DataValidationError("案例库为空，请先构建案例库。")
        selected_ids = self.ai.select_cases(cases, requirement, top_n)
        cases_by_id = {case.bvid: case for case in cases}
        return [cases_by_id[bvid] for bvid in selected_ids if bvid in cases_by_id]

    def generate(
        self,
        bvids: Iterable[str],
        outline_path: Path,
        requirements: str,
    ) -> str:
        requested_ids = list(dict.fromkeys(bvid.strip() for bvid in bvids if bvid.strip()))
        selected = self.repository.find_by_bvids(requested_ids)
        selected_ids = {case.bvid for case in selected}
        missing_ids = [bvid for bvid in requested_ids if bvid not in selected_ids]
        if missing_ids:
            raise DataValidationError(f"案例库中未找到：{', '.join(missing_ids)}")
        if not selected:
            raise DataValidationError("至少需要选择一个有效参考案例。")
        outline = outline_path.read_text(encoding="utf-8").strip()
        if not outline:
            raise DataValidationError("大纲文件内容为空。")
        return self.ai.generate_script(
            templates=[case.text for case in selected],
            outline=outline,
            requirements=requirements,
        )
