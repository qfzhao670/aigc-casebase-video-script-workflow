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
ProgressCallback = Callable[[str, float, Optional[float]], None]
BvidsCallback = Callable[[List[str]], None]


class CaseBuildWorkflow:
    def __init__(
        self,
        repository: CaseRepository,
        media: MediaService,
        ai: DashScopeService,
        log: Optional[LogCallback] = None,
        progress: Optional[ProgressCallback] = None,
    ):
        self.repository = repository
        self.media = media
        self.ai = ai
        self.log = log or (lambda _message: None)
        self.progress = progress or (lambda _stage, _overall, _stage_percent: None)

    def run_from_user(
        self,
        uid: str,
        limit: int,
        should_stop: Optional[StopCallback] = None,
        on_bvids: Optional[BvidsCallback] = None,
        cookies_from_browser: Optional[str] = None,
    ) -> List[str]:
        """Resolve one user's recent videos, then pass them to the build flow."""
        return self.run_from_users(
            [uid],
            limit,
            should_stop=should_stop,
            on_bvids=on_bvids,
            cookies_from_browser=cookies_from_browser,
        )

    def run_from_users(
        self,
        uids: Iterable[str],
        limit: int,
        should_stop: Optional[StopCallback] = None,
        on_bvids: Optional[BvidsCallback] = None,
        cookies_from_browser: Optional[str] = None,
    ) -> List[str]:
        """Resolve multiple users' videos, merge them, then run the build flow."""
        stop_requested = should_stop or (lambda: False)
        normalized_uids = list(
            dict.fromkeys(str(uid).strip() for uid in uids if str(uid).strip())
        )
        if not normalized_uids:
            raise DataValidationError("请至少输入一个 B 站用户 UID。")

        bvids = []
        seen_bvids = set()
        total = len(normalized_uids)
        for index, uid in enumerate(normalized_uids, start=1):
            if stop_requested():
                self.log("任务已停止。")
                self.progress("任务已停止", 0.0, None)
                return bvids
            self.log(
                f"[{index}/{total}] 正在获取 UID {uid} "
                f"最近的 {limit} 条公开投稿……"
            )
            self.progress(
                f"[{index}/{total}] 正在获取 UID {uid} 的视频列表……",
                0.0,
                (index - 1) / total * 100.0,
            )
            try:
                if cookies_from_browser:
                    user_bvids = self.media.get_user_bvids(
                        uid,
                        limit,
                        cookies_from_browser=cookies_from_browser,
                    )
                else:
                    user_bvids = self.media.get_user_bvids(uid, limit)
            except ApplicationError as exc:
                self.log(f"[{index}/{total}] UID {uid} 获取失败，继续下一个：{exc}")
                continue

            added = []
            for bvid in user_bvids:
                key = bvid.upper()
                if key not in seen_bvids:
                    seen_bvids.add(key)
                    bvids.append(bvid)
                    added.append(bvid)
            self.log(
                f"[{index}/{total}] UID {uid} 获取到 {len(user_bvids)} 个 BV 号，"
                f"合并后新增 {len(added)} 个。"
            )

        if not bvids:
            raise DataValidationError(
                f"未能从输入的 {total} 个 UID 获取到公开视频。"
                "请检查 UID、用户投稿状态或稍后重试。"
            )
        self.log(f"共获取 {len(bvids)} 个去重后的 BV 号。")
        if on_bvids:
            on_bvids(list(bvids))
        if stop_requested():
            self.log("任务已停止。")
            self.progress("任务已停止", 0.0, None)
            return bvids
        self.run(bvids, should_stop=stop_requested)
        return bvids

    def run(self, bvids: Iterable[str], should_stop: Optional[StopCallback] = None) -> None:
        stop_requested = should_stop or (lambda: False)
        normalized_ids = list(dict.fromkeys(item.strip() for item in bvids if item.strip()))
        total = len(normalized_ids)
        if total == 0:
            self.log("没有可处理的 BV 号。")
            self.progress("没有可处理的 BV 号", 100.0, 100.0)
            return
        self.progress("正在检查环境……", 0.0, None)
        existing_ids = self.repository.existing_bvids()
        self.log(f"案例库已有 {len(existing_ids)} 条记录。")
        self.media.check_dependencies()

        for index, bvid in enumerate(normalized_ids, start=1):
            item_start = (index - 1) / total * 100.0
            item_end = index / total * 100.0

            def report_stage(
                stage: str,
                stage_percent: Optional[float],
                stage_start: float,
                stage_end: float,
            ) -> None:
                fraction = 0.0 if stage_percent is None else stage_percent / 100.0
                item_fraction = (stage_start + (stage_end - stage_start) * fraction) / 100.0
                overall = item_start + (item_end - item_start) * item_fraction
                self.progress(
                    f"[{index}/{total}] {stage}",
                    overall,
                    stage_percent,
                )

            if stop_requested():
                self.log("任务已停止。")
                self.progress("任务已停止", item_start, None)
                break
            if bvid in existing_ids:
                self.log(f"[{index}/{len(normalized_ids)}] 已存在，跳过：{bvid}")
                self.progress(f"[{index}/{total}] 已存在，已跳过", item_end, 100.0)
                continue

            try:
                self.log(f"[{index}/{len(normalized_ids)}] 开始处理：{bvid}")
                report_stage("正在读取视频信息……", None, 0.0, 5.0)
                metadata = self.media.get_metadata(bvid)
                report_stage("视频信息读取完成", 100.0, 0.0, 5.0)
                audio_path = self.media.download_audio(
                    metadata,
                    progress=lambda percent: report_stage(
                        "正在下载音频",
                        percent,
                        5.0,
                        30.0,
                    ),
                )
                transcript = self.media.transcribe(
                    audio_path,
                    progress=lambda percent: report_stage(
                        "正在进行语音转录",
                        percent,
                        30.0,
                        85.0,
                    ),
                )
                self.log("正在生成摘要和关键词……")
                report_stage("正在生成摘要和关键词……", None, 85.0, 98.0)
                analysis = self.ai.analyze_transcript(transcript)
                report_stage("正在写入案例库……", None, 98.0, 100.0)
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
                self.progress(f"[{index}/{total}] 入库成功", item_end, 100.0)
            except ApplicationError as exc:
                self.log(f"处理失败，可稍后重试 {bvid}：{exc}")
                self.progress(f"[{index}/{total}] 处理失败", item_end, 100.0)

        else:
            self.progress("案例库构建完成", 100.0, 100.0)


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
