"""Application workflows that coordinate storage, media, and AI services."""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import math
from pathlib import Path
import threading
from typing import Callable, Iterable, List, Optional

from ..domain import CaseAnalysis, CaseRecord, VideoMetadata
from ..errors import ApplicationError, DataValidationError
from .ai_service import DashScopeService
from .case_repository import CaseRepository
from .media_service import MediaService


LogCallback = Callable[[str], None]
StopCallback = Callable[[], bool]
ProgressCallback = Callable[[str, float, Optional[float]], None]
BvidsCallback = Callable[[List[str]], None]


def _normalize_title_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
    """Normalize and deduplicate literal title keywords."""
    normalized = []
    seen = set()
    for keyword in keywords:
        value = str(keyword).strip().casefold()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return tuple(normalized)


def _validate_duration_range(
    min_duration_seconds: Optional[float],
    max_duration_seconds: Optional[float],
) -> None:
    for label, value in (
        ("最短时长", min_duration_seconds),
        ("最长时长", max_duration_seconds),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise DataValidationError(f"{label}必须是大于等于 0 的有限数字。")
    if (
        min_duration_seconds is not None
        and max_duration_seconds is not None
        and min_duration_seconds > max_duration_seconds
    ):
        raise DataValidationError("最短时长不能大于最长时长。")


def _video_filter_reason(
    metadata: VideoMetadata,
    min_duration_seconds: Optional[float],
    max_duration_seconds: Optional[float],
    title_keywords: tuple[str, ...],
) -> Optional[str]:
    """Return the reason a video should be skipped, or ``None`` to keep it."""
    if title_keywords and not any(
        keyword in metadata.title.casefold() for keyword in title_keywords
    ):
        return "标题未包含指定关键词"

    if min_duration_seconds is None and max_duration_seconds is None:
        return None
    if metadata.duration is None:
        return "无法获取视频时长"
    if min_duration_seconds is not None and metadata.duration < min_duration_seconds:
        return f"时长 {metadata.duration / 60:.1f} 分钟，低于下限"
    if max_duration_seconds is not None and metadata.duration > max_duration_seconds:
        return f"时长 {metadata.duration / 60:.1f} 分钟，超过上限"
    return None


@dataclass(frozen=True)
class _PreparedVideo:
    index: int
    bvid: str
    metadata: VideoMetadata
    audio_path: Path


@dataclass(frozen=True)
class _TranscribedVideo:
    index: int
    bvid: str
    metadata: VideoMetadata
    transcript: str


class _PipelineProgress:
    """Aggregate concurrent per-video stages into one monotonic percentage."""

    def __init__(self, total: int, callback: ProgressCallback):
        self.total = total
        self.callback = callback
        self._item_percent = [0.0] * total
        self._lock = threading.Lock()

    def report(
        self,
        index: int,
        stage: str,
        item_percent: float,
        stage_percent: Optional[float],
    ) -> None:
        with self._lock:
            slot = index - 1
            self._item_percent[slot] = max(
                self._item_percent[slot],
                max(0.0, min(100.0, item_percent)),
            )
            overall = sum(self._item_percent) / self.total
            self.callback(
                f"[{index}/{self.total}] {stage}",
                overall,
                stage_percent,
            )

    def overall(self) -> float:
        with self._lock:
            return sum(self._item_percent) / self.total


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
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        title_keywords: Iterable[str] = (),
    ) -> List[str]:
        """Resolve one user's recent videos, then pass them to the build flow."""
        return self.run_from_users(
            [uid],
            limit,
            should_stop=should_stop,
            on_bvids=on_bvids,
            cookies_from_browser=cookies_from_browser,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            title_keywords=title_keywords,
        )

    def run_from_users(
        self,
        uids: Iterable[str],
        limit: int,
        should_stop: Optional[StopCallback] = None,
        on_bvids: Optional[BvidsCallback] = None,
        cookies_from_browser: Optional[str] = None,
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        title_keywords: Iterable[str] = (),
    ) -> List[str]:
        """Resolve multiple users' videos, merge them, then run the build flow."""
        _validate_duration_range(min_duration_seconds, max_duration_seconds)
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
        self.run(
            bvids,
            should_stop=stop_requested,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            title_keywords=title_keywords,
        )
        return bvids

    def run(
        self,
        bvids: Iterable[str],
        should_stop: Optional[StopCallback] = None,
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        title_keywords: Iterable[str] = (),
    ) -> None:
        stop_requested = should_stop or (lambda: False)
        _validate_duration_range(min_duration_seconds, max_duration_seconds)
        normalized_keywords = _normalize_title_keywords(title_keywords)
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
        if stop_requested():
            self.log("任务已停止。")
            self.progress("任务已停止", 0.0, None)
            return
        tracker = _PipelineProgress(total, self.progress)
        jobs = []
        for index, bvid in enumerate(normalized_ids, start=1):
            if bvid in existing_ids:
                self.log(f"[{index}/{total}] 已存在，跳过：{bvid}")
                tracker.report(index, "已存在，已跳过", 100.0, 100.0)
            else:
                jobs.append((index, bvid))

        if not jobs:
            self.progress("案例库构建完成", 100.0, 100.0)
            return

        def prepare(index: int, bvid: str) -> Optional[_PreparedVideo]:
            self.log(f"[{index}/{total}] 正在预取视频：{bvid}")
            tracker.report(index, "正在读取视频信息……", 0.0, None)
            metadata = self.media.get_metadata(bvid)
            tracker.report(index, "视频信息读取完成", 5.0, 100.0)
            filter_reason = _video_filter_reason(
                metadata,
                min_duration_seconds,
                max_duration_seconds,
                normalized_keywords,
            )
            if filter_reason is not None:
                self.log(
                    f"[{index}/{total}] 筛选跳过 {metadata.bvid}："
                    f"{filter_reason}（{metadata.title}）"
                )
                tracker.report(index, "不符合筛选条件，已跳过", 100.0, 100.0)
                return None
            audio_path = self.media.download_audio(
                metadata,
                progress=lambda percent: tracker.report(
                    index,
                    "正在下载音频",
                    5.0 + 25.0 * percent / 100.0,
                    percent,
                ),
            )
            return _PreparedVideo(index, bvid, metadata, audio_path)

        def analyze(item: _TranscribedVideo) -> tuple[_TranscribedVideo, CaseAnalysis]:
            self.log(f"[{item.index}/{total}] 正在生成摘要和关键词……")
            tracker.report(
                item.index,
                "正在生成摘要和关键词……",
                85.0,
                None,
            )
            analysis = self.ai.analyze_transcript(item.transcript)
            tracker.report(item.index, "摘要和关键词已生成", 98.0, 100.0)
            return item, analysis

        def fail(index: int, bvid: str, exc: ApplicationError) -> None:
            self.log(f"处理失败，可稍后重试 {bvid}：{exc}")
            tracker.report(index, "处理失败", 100.0, 100.0)

        def finish_analysis(
            pending_item: _TranscribedVideo,
            future: Future[tuple[_TranscribedVideo, CaseAnalysis]],
        ) -> None:
            try:
                item, analysis = future.result()
                tracker.report(item.index, "正在写入案例库……", 98.0, None)
                self.repository.append(
                    CaseRecord(
                        uploader=item.metadata.uploader,
                        bvid=item.metadata.bvid,
                        title=item.metadata.title,
                        text=item.transcript,
                        summary=analysis.summary,
                        keywords=analysis.keywords,
                    )
                )
                existing_ids.add(item.metadata.bvid)
                self.log(f"入库成功：{item.metadata.title}")
                tracker.report(item.index, "入库成功", 100.0, 100.0)
            except ApplicationError as exc:
                fail(pending_item.index, pending_item.bvid, exc)

        pending_analysis: Optional[
            tuple[
                _TranscribedVideo,
                Future[tuple[_TranscribedVideo, CaseAnalysis]],
            ]
        ] = None
        stopped = False
        download_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="bili-download",
        )
        analysis_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="bili-analysis",
        )
        current_download: Optional[
            Future[Optional[_PreparedVideo]]
        ] = download_executor.submit(prepare, *jobs[0])

        try:
            for position, (index, bvid) in enumerate(jobs):
                if stop_requested():
                    stopped = True
                    break

                assert current_download is not None
                try:
                    prepared = current_download.result()
                except ApplicationError as exc:
                    prepared = None
                    fail(index, bvid, exc)

                next_download = None
                if position + 1 < len(jobs) and not stop_requested():
                    next_download = download_executor.submit(prepare, *jobs[position + 1])

                transcribed = None
                if prepared is not None:
                    try:
                        transcript = self.media.transcribe(
                            prepared.audio_path,
                            progress=lambda percent, item_index=index: tracker.report(
                                item_index,
                                "正在进行语音转录",
                                30.0 + 55.0 * percent / 100.0,
                                percent,
                            ),
                        )
                        transcribed = _TranscribedVideo(
                            index,
                            bvid,
                            prepared.metadata,
                            transcript,
                        )
                    except ApplicationError as exc:
                        fail(index, bvid, exc)

                if pending_analysis is not None:
                    finish_analysis(*pending_analysis)
                    pending_analysis = None

                if stop_requested():
                    stopped = True
                    current_download = next_download
                    break

                if transcribed is not None:
                    pending_analysis = (
                        transcribed,
                        analysis_executor.submit(analyze, transcribed),
                    )

                current_download = next_download

            if pending_analysis is not None:
                finish_analysis(*pending_analysis)
        finally:
            download_executor.shutdown(wait=True, cancel_futures=True)
            analysis_executor.shutdown(wait=True, cancel_futures=True)

        if stopped:
            self.log("任务已停止。")
            self.progress("任务已停止", tracker.overall(), None)
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
