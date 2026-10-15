"""Case-library builder tab."""

from datetime import datetime
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from ..config import WHISPER_MODEL, Settings
from ..services.factory import ServiceFactory


class CaseBuilderTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, settings: Settings, factory: ServiceFactory):
        super().__init__(parent, padding=12)
        self.settings = settings
        self.factory = factory
        self.stop_event = threading.Event()
        self._ui_events: queue.Queue[tuple] = queue.Queue()
        self._worker_active = False
        self._event_poll_scheduled = False
        self._task_bvids: list[str] = []
        self._task_signature: Optional[tuple] = None
        self._resume_available = False
        self._create_widgets()

    def _create_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        settings_frame = ttk.LabelFrame(self, text="任务设置", padding=10)
        settings_frame.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        settings_frame.columnconfigure(1, weight=1)

        self.library_path = tk.StringVar(value=str(self.settings.default_library))
        ttk.Label(settings_frame, text="案例库").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 12)
        )
        ttk.Entry(settings_frame, textvariable=self.library_path).grid(
            row=0, column=1, sticky=tk.EW
        )
        ttk.Button(settings_frame, text="选择…", command=self._browse_library).grid(
            row=0, column=2, sticky=tk.E, padx=(8, 0)
        )

        ttk.Separator(settings_frame).grid(
            row=1, column=0, columnspan=3, sticky=tk.EW, pady=10
        )

        self.source_mode = tk.StringVar(value="uid")
        ttk.Label(settings_frame, text="视频来源").grid(
            row=2, column=0, sticky=tk.W, padx=(0, 12)
        )
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.grid(row=2, column=1, columnspan=2, sticky=tk.W)
        self.uid_mode_button = ttk.Radiobutton(
            mode_frame,
            text="按 UID 自动获取",
            variable=self.source_mode,
            value="uid",
            command=self._update_source_controls,
        )
        self.uid_mode_button.pack(side=tk.LEFT)
        self.manual_mode_button = ttk.Radiobutton(
            mode_frame,
            text="手动输入 BV 号",
            variable=self.source_mode,
            value="manual",
            command=self._update_source_controls,
        )
        self.manual_mode_button.pack(side=tk.LEFT, padx=(18, 0))

        options_frame = ttk.Frame(settings_frame)
        options_frame.grid(
            row=3,
            column=0,
            columnspan=3,
            sticky=tk.EW,
            pady=(8, 0),
        )
        options_frame.columnconfigure(0, weight=1, uniform="options")
        options_frame.columnconfigure(1, weight=1, uniform="options")

        source_frame = ttk.LabelFrame(options_frame, text="UID 自动获取", padding=8)
        source_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        source_frame.columnconfigure(0, weight=1)

        source_header = ttk.Frame(source_frame)
        source_header.grid(row=0, column=0, sticky=tk.EW, pady=(0, 5))
        source_header.columnconfigure(0, weight=1)
        ttk.Label(source_header, text="UID 列表（每行一个）").grid(
            row=0,
            column=0,
            sticky=tk.W,
        )
        count_frame = ttk.Frame(source_header)
        count_frame.grid(row=0, column=1, sticky=tk.E)
        ttk.Label(count_frame, text="每个最近").pack(side=tk.LEFT)
        self.video_count = tk.StringVar(value="10")
        self.count_input = ttk.Spinbox(
            count_frame,
            from_=1,
            to=1000,
            textvariable=self.video_count,
            width=6,
        )
        self.count_input.pack(side=tk.LEFT, padx=(5, 3))
        ttk.Label(count_frame, text="条").pack(side=tk.LEFT)

        self.uid_input = scrolledtext.ScrolledText(
            source_frame,
            height=3,
            wrap=tk.NONE,
        )
        self.uid_input.grid(row=1, column=0, sticky=tk.EW)
        self.use_chrome_cookies = tk.BooleanVar(value=True)
        self.cookie_retry_button = ttk.Checkbutton(
            source_frame,
            text="遇到 412/352 风控时使用 Chrome 登录状态重试",
            variable=self.use_chrome_cookies,
        )
        self.cookie_retry_button.grid(
            row=2, column=0, sticky=tk.W, pady=(5, 0)
        )

        filter_frame = ttk.LabelFrame(options_frame, text="视频筛选", padding=8)
        filter_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text="时长").grid(
            row=0,
            column=0,
            sticky=tk.W,
            padx=(0, 8),
        )
        duration_frame = ttk.Frame(filter_frame)
        duration_frame.grid(row=0, column=1, sticky=tk.W)
        self.min_duration_minutes = tk.StringVar()
        self.min_duration_input = ttk.Entry(
            duration_frame,
            textvariable=self.min_duration_minutes,
            width=8,
        )
        self.min_duration_input.pack(side=tk.LEFT)
        ttk.Label(duration_frame, text="–").pack(side=tk.LEFT, padx=6)
        self.max_duration_minutes = tk.StringVar()
        self.max_duration_input = ttk.Entry(
            duration_frame,
            textvariable=self.max_duration_minutes,
            width=8,
        )
        self.max_duration_input.pack(side=tk.LEFT)
        ttk.Label(duration_frame, text="分钟（最短 / 最长）").pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

        ttk.Label(filter_frame, text="标题").grid(
            row=1,
            column=0,
            sticky=tk.W,
            padx=(0, 8),
            pady=(7, 0),
        )
        self.title_keywords_text = tk.StringVar()
        self.title_keywords_input = ttk.Entry(
            filter_frame,
            textvariable=self.title_keywords_text,
        )
        self.title_keywords_input.grid(
            row=1,
            column=1,
            sticky=tk.EW,
            pady=(7, 0),
        )
        ttk.Label(
            filter_frame,
            text="时长留空即不限；多个关键词用逗号分隔，命中任意一个即保留",
            wraplength=350,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(7, 0))

        workspace_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        workspace_pane.grid(row=1, column=0, sticky=tk.NSEW)

        activity_frame = ttk.Frame(workspace_pane)
        activity_frame.columnconfigure(0, weight=2, minsize=280)
        activity_frame.columnconfigure(1, weight=3, minsize=420)
        activity_frame.rowconfigure(0, weight=1)

        input_frame = ttk.LabelFrame(
            activity_frame,
            text="BV 号列表 · 每行一个（UID 模式下自动填入）",
            padding=10,
        )
        input_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 5))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)
        self.bvid_input = scrolledtext.ScrolledText(input_frame, height=8, wrap=tk.NONE)
        self.bvid_input.grid(row=0, column=0, sticky=tk.NSEW)

        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))
        self.stop_button = ttk.Button(
            button_frame,
            text="停止",
            command=self._request_stop,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.RIGHT)
        self.start_button = ttk.Button(
            button_frame, text="开始构建", command=self._start
        )
        self.start_button.pack(side=tk.RIGHT, padx=(0, 6))

        progress_frame = ttk.LabelFrame(activity_frame, text="任务进度", padding=10)
        progress_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(5, 0))
        progress_frame.columnconfigure(1, weight=1)
        progress_frame.columnconfigure(2, weight=1)
        self.progress_status = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.progress_status).grid(
            row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6)
        )
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_value,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky=tk.EW)

        ttk.Separator(progress_frame).grid(
            row=2, column=0, columnspan=3, sticky=tk.EW, pady=9
        )
        self.pipeline_status: dict[str, tk.StringVar] = {}
        self.pipeline_value: dict[str, tk.DoubleVar] = {}
        for row, (lane, title) in enumerate(
            (
                ("download", "下载"),
                ("transcribe", "语音转录"),
                ("analysis", "分析入库"),
            ),
            start=3,
        ):
            ttk.Label(progress_frame, text=title, width=9).grid(
                row=row, column=0, sticky=tk.W, pady=2
            )
            value = tk.DoubleVar(value=0.0)
            ttk.Progressbar(
                progress_frame,
                variable=value,
                maximum=100.0,
                mode="determinate",
            ).grid(row=row, column=1, sticky=tk.EW, padx=(0, 10), pady=2)
            status = tk.StringVar(value="等待中")
            ttk.Label(
                progress_frame,
                textvariable=status,
                width=18,
                anchor=tk.W,
            ).grid(row=row, column=2, sticky=tk.EW, pady=2)
            self.pipeline_value[lane] = value
            self.pipeline_status[lane] = status

        log_frame = ttk.LabelFrame(
            workspace_pane,
            text="事件日志 · 可拖动上方分隔线调整高度",
            padding=10,
        )
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_output = scrolledtext.ScrolledText(
            log_frame,
            height=14,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log_output.grid(row=0, column=0, sticky=tk.NSEW)
        self.log_output.tag_configure("timestamp", foreground="#777777")
        self.log_output.tag_configure("download", foreground="#0969da")
        self.log_output.tag_configure("transcribe", foreground="#8250df")
        self.log_output.tag_configure("analysis", foreground="#007a7a")
        self.log_output.tag_configure("task", foreground="#57606a")
        self.log_output.tag_configure("success", foreground="#18794e")
        self.log_output.tag_configure("warning", foreground="#9a6700")
        self.log_output.tag_configure("error", foreground="#cf222e")

        workspace_pane.add(activity_frame, weight=1)
        workspace_pane.add(log_frame, weight=4)
        self._update_source_controls()

    def _browse_library(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择或创建案例库",
            initialdir=str(self.settings.data_dir),
            initialfile="dataset.jsonl",
            defaultextension=".jsonl",
            filetypes=[("JSON Lines", "*.jsonl"), ("所有文件", "*.*")],
        )
        if path:
            self.library_path.set(path)

    def _start(self) -> None:
        path_text = self.library_path.get().strip()
        mode = self.source_mode.get()
        bvids = [line.strip() for line in self.bvid_input.get("1.0", tk.END).splitlines()]
        bvids = [bvid for bvid in bvids if bvid]
        if not path_text:
            messagebox.showwarning("缺少案例库", "请选择案例库文件。")
            return
        uids = [line.strip() for line in self.uid_input.get("1.0", tk.END).splitlines()]
        uids = list(dict.fromkeys(uid for uid in uids if uid))
        count = 0
        if mode == "uid":
            if not uids:
                messagebox.showwarning("缺少 UID", "请至少输入一个 B 站用户 UID。")
                return
            invalid_uids = [uid for uid in uids if not uid.isdigit() or int(uid) <= 0]
            if invalid_uids:
                messagebox.showwarning(
                    "无效 UID",
                    "UID 必须是大于 0 的整数，请检查："
                    + "、".join(invalid_uids[:5]),
                )
                return
            try:
                count = int(self.video_count.get().strip())
            except ValueError:
                count = 0
            if not 1 <= count <= 1000:
                messagebox.showwarning("无效数量", "获取数量必须是 1–1000 之间的整数。")
                return
        elif not bvids:
            messagebox.showwarning("缺少 BV 号", "请至少输入一个 BV 号。")
            return

        try:
            min_duration_seconds = self._parse_duration_minutes(
                self.min_duration_minutes.get(),
                "最短时长",
            )
            max_duration_seconds = self._parse_duration_minutes(
                self.max_duration_minutes.get(),
                "最长时长",
            )
        except ValueError as exc:
            messagebox.showwarning("无效筛选条件", str(exc))
            return
        if (
            min_duration_seconds is not None
            and max_duration_seconds is not None
            and min_duration_seconds > max_duration_seconds
        ):
            messagebox.showwarning(
                "无效筛选条件",
                "最短时长不能大于最长时长。",
            )
            return
        title_keywords = self._parse_title_keywords(self.title_keywords_text.get())

        cookies_from_browser = "chrome" if self.use_chrome_cookies.get() else None
        task_signature = self._make_task_signature(
            Path(path_text),
            mode,
            uids,
            count,
            bvids,
            cookies_from_browser,
            min_duration_seconds,
            max_duration_seconds,
            title_keywords,
        )
        resume = (
            self._resume_available
            and bool(self._task_bvids)
            and task_signature == self._task_signature
        )

        self.stop_event.clear()
        self._discard_pending_events()
        if not resume:
            self._clear_log()
            self._task_bvids = list(bvids)
            self._task_signature = task_signature
        self._resume_available = False
        self.start_button.configure(text="开始构建")
        self.progress_value.set(0.0)
        self.progress_status.set("正在启动……")
        self._reset_pipeline_progress()
        self._worker_active = True
        self._set_running(True)
        if resume:
            self._append_log(
                f"继续上次构建，直接处理已获取的 "
                f"{len(self._task_bvids)} 个 BV 号。"
            )
        else:
            self._append_log("开始执行案例库构建任务。")
        self._append_log(f"本次使用 Whisper 模型：{WHISPER_MODEL}")
        self._schedule_event_poll()
        worker = threading.Thread(
            target=self._run_worker,
            args=(
                Path(path_text),
                mode,
                uids,
                count,
                list(self._task_bvids) if resume else bvids,
                cookies_from_browser,
                min_duration_seconds,
                max_duration_seconds,
                title_keywords,
                resume,
            ),
            daemon=True,
        )
        worker.start()

    @staticmethod
    def _make_task_signature(
        library_path: Path,
        mode: str,
        uids: list[str],
        count: int,
        bvids: list[str],
        cookies_from_browser: Optional[str],
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        title_keywords: tuple[str, ...] = (),
    ) -> tuple:
        """Identify whether the current form still describes the stopped task."""
        source = (tuple(uids), count) if mode == "uid" else tuple(bvids)
        return (
            str(library_path.expanduser().resolve()),
            mode,
            source,
            cookies_from_browser if mode == "uid" else None,
            min_duration_seconds,
            max_duration_seconds,
            tuple(title_keywords),
        )

    @staticmethod
    def _parse_duration_minutes(value: str, label: str) -> Optional[float]:
        text = value.strip()
        if not text:
            return None
        try:
            minutes = float(text)
        except ValueError as exc:
            raise ValueError(f"{label}必须是数字，或留空表示不限。") from exc
        if minutes != minutes or minutes in {float("inf"), float("-inf")}:
            raise ValueError(f"{label}必须是有限数字。")
        if minutes < 0:
            raise ValueError(f"{label}不能小于 0。")
        return minutes * 60

    @staticmethod
    def _parse_title_keywords(value: str) -> tuple[str, ...]:
        keywords = []
        seen = set()
        for item in re.split(r"[,\uff0c\n]+", value):
            keyword = item.strip()
            normalized = keyword.casefold()
            if keyword and normalized not in seen:
                keywords.append(keyword)
                seen.add(normalized)
        return tuple(keywords)

    def _run_worker(
        self,
        library_path: Path,
        mode: str,
        uids: list,
        count: int,
        bvids: list,
        cookies_from_browser: Optional[str],
        min_duration_seconds: Optional[float] = None,
        max_duration_seconds: Optional[float] = None,
        title_keywords: tuple[str, ...] = (),
        resume: bool = False,
    ) -> None:
        failed = False
        try:
            workflow = self.factory.case_builder(
                library_path,
                log=self._thread_log,
                progress=self._thread_progress,
            )
            if resume:
                # The UID discovery result is kept by the tab.  Resume the
                # processing queue directly so Bilibili is not queried again.
                workflow.run(
                    bvids,
                    should_stop=self.stop_event.is_set,
                    min_duration_seconds=min_duration_seconds,
                    max_duration_seconds=max_duration_seconds,
                    title_keywords=title_keywords,
                )
            elif mode == "uid":
                workflow.run_from_users(
                    uids,
                    count,
                    should_stop=self.stop_event.is_set,
                    on_bvids=self._thread_bvids,
                    cookies_from_browser=cookies_from_browser,
                    min_duration_seconds=min_duration_seconds,
                    max_duration_seconds=max_duration_seconds,
                    title_keywords=title_keywords,
                )
            else:
                workflow.run(
                    bvids,
                    should_stop=self.stop_event.is_set,
                    min_duration_seconds=min_duration_seconds,
                    max_duration_seconds=max_duration_seconds,
                    title_keywords=title_keywords,
                )
            if not self.stop_event.is_set():
                self._thread_log("案例库构建完成。")
        except Exception as exc:
            failed = True
            self._thread_log(f"任务失败：{exc}")
            self._ui_events.put(("error", str(exc)))
        finally:
            self._ui_events.put(("finished", self.stop_event.is_set(), failed))

    def _request_stop(self) -> None:
        self.stop_event.set()
        self._append_log("已请求停止；当前步骤结束后将退出。")
        self.progress_status.set("已请求停止，等待当前步骤结束……")
        self.stop_button.configure(state=tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.uid_mode_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.manual_mode_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        if running:
            self.uid_input.configure(state=tk.DISABLED)
            self.count_input.configure(state=tk.DISABLED)
            self.cookie_retry_button.configure(state=tk.DISABLED)
            self.min_duration_input.configure(state=tk.DISABLED)
            self.max_duration_input.configure(state=tk.DISABLED)
            self.title_keywords_input.configure(state=tk.DISABLED)
            self.bvid_input.configure(state=tk.DISABLED)
        else:
            self._update_source_controls()

    def _update_source_controls(self) -> None:
        uid_mode = self.source_mode.get() == "uid"
        self.uid_input.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
        self.count_input.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
        self.cookie_retry_button.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
        self.min_duration_input.configure(state=tk.NORMAL)
        self.max_duration_input.configure(state=tk.NORMAL)
        self.title_keywords_input.configure(state=tk.NORMAL)
        self.bvid_input.configure(state=tk.DISABLED if uid_mode else tk.NORMAL)

    def _thread_log(self, message: str) -> None:
        self._ui_events.put(("log", message))

    def _thread_bvids(self, bvids: list[str]) -> None:
        self._ui_events.put(("bvids", bvids))

    def _thread_progress(
        self,
        stage: str,
        overall_percent: float,
        stage_percent: Optional[float],
    ) -> None:
        self._ui_events.put(
            ("progress", stage, overall_percent, stage_percent)
        )

    def _schedule_event_poll(self) -> None:
        if self._event_poll_scheduled:
            return
        self._event_poll_scheduled = True
        self.after(50, self._drain_ui_events)

    def _drain_ui_events(self) -> None:
        self._event_poll_scheduled = False
        latest_progress: dict[str, tuple[int, tuple]] = {}
        progress_sequence = 0
        terminal_status: Optional[str] = None
        while True:
            try:
                event = self._ui_events.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "log":
                self._append_log(event[1])
            elif event_type == "bvids":
                self._task_bvids = list(event[1])
                self.bvid_input.configure(state=tk.NORMAL)
                self.bvid_input.delete("1.0", tk.END)
                self.bvid_input.insert("1.0", "\n".join(event[1]))
                self.bvid_input.configure(state=tk.DISABLED)
            elif event_type == "progress":
                lane = self._progress_lane(event[1]) or "overall"
                latest_progress[lane] = (progress_sequence, event)
                progress_sequence += 1
            elif event_type == "error":
                terminal_status = "任务失败"
                messagebox.showerror("案例库构建失败", event[1])
            elif event_type == "finished":
                self._worker_active = False
                self._set_running(False)
                stopped = bool(event[1]) if len(event) > 1 else False
                failed = bool(event[2]) if len(event) > 2 else False
                self._resume_available = stopped and not failed and bool(
                    self._task_bvids
                )
                self.start_button.configure(
                    text="继续构建" if self._resume_available else "开始构建"
                )
                if self._resume_available:
                    terminal_status = "已停止，可继续构建"

        # Whisper and yt-dlp can emit many updates between two Tk refreshes.
        # Rendering only the newest value for each lane keeps the UI responsive
        # without sacrificing the visible, near-real-time progress.
        for _sequence, event in sorted(latest_progress.values()):
            self._show_progress(event[1], event[2], event[3])
        if terminal_status is not None:
            self.progress_status.set(terminal_status)

        if self._worker_active or not self._ui_events.empty():
            self._schedule_event_poll()

    def _show_progress(
        self,
        stage: str,
        overall_percent: float,
        stage_percent: Optional[float],
    ) -> None:
        overall_percent = max(0.0, min(100.0, overall_percent))
        self.progress_value.set(overall_percent)
        lane = self._progress_lane(stage)
        if stage_percent is None:
            status = stage
        else:
            stage_percent = max(0.0, min(100.0, stage_percent))
            status = f"{stage}：{stage_percent:.0f}%"
        self.progress_status.set(f"总进度 {overall_percent:.0f}% · {status}")

        if lane is None:
            if stage in {"任务已停止", "案例库构建完成", "没有可处理的 BV 号"}:
                self._finish_pipeline_progress(stage)
            return

        if stage_percent is None:
            lane_value = 98.0 if "写入案例库" in stage else 0.0
        else:
            lane_value = stage_percent
        self.pipeline_value[lane].set(lane_value)
        self.pipeline_status[lane].set(
            self._format_lane_status(stage, stage_percent)
        )

    @staticmethod
    def _progress_lane(stage: str) -> Optional[str]:
        if any(
            marker in stage
            for marker in (
                "读取视频信息",
                "下载音频",
                "视频信息读取完成",
                "筛选条件",
            )
        ):
            return "download"
        if "语音转录" in stage:
            return "transcribe"
        if any(
            marker in stage
            for marker in (
                "摘要和关键词",
                "写入案例库",
                "入库成功",
                "处理失败",
                "已存在",
            )
        ):
            return "analysis"
        return None

    def _format_lane_status(
        self,
        stage: str,
        stage_percent: Optional[float],
    ) -> str:
        position = re.match(r"^\[(\d+)/(\d+)\]\s*(.*)$", stage)
        if position:
            index = int(position.group(1))
            total = position.group(2)
            detail = position.group(3).rstrip("…")
            bvid = ""
            if 1 <= index <= len(self._task_bvids):
                bvid = f" {self._task_bvids[index - 1]}"
            prefix = f"[{index}/{total}]{bvid}"
        else:
            prefix = ""
            detail = stage.rstrip("…")

        percent = "" if stage_percent is None else f" · {stage_percent:.0f}%"
        return f"{prefix} · {detail}{percent}".strip(" ·")

    def _reset_pipeline_progress(self) -> None:
        for lane in self.pipeline_value:
            self.pipeline_value[lane].set(0.0)
            self.pipeline_status[lane].set("等待中")

    def _finish_pipeline_progress(self, stage: str) -> None:
        if stage == "案例库构建完成":
            for lane in self.pipeline_value:
                self.pipeline_value[lane].set(100.0)
                self.pipeline_status[lane].set("已完成")
        elif stage == "任务已停止":
            for lane in self.pipeline_status:
                current = self.pipeline_status[lane].get()
                if current not in {"等待中", "已完成"}:
                    self.pipeline_status[lane].set(f"{current} · 已停止")

    def _discard_pending_events(self) -> None:
        while True:
            try:
                self._ui_events.get_nowait()
            except queue.Empty:
                break

    def _clear_log(self) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.delete("1.0", tk.END)
        self.log_output.configure(state=tk.DISABLED)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        if any(
            message.startswith(prefix)
            for prefix in ("[download] Destination:", "[ExtractAudio] Destination:")
        ):
            return
        if any(marker in message for marker in ("失败", "错误")):
            tag = "error"
        elif any(marker in message for marker in ("停止", "风控", "回退")):
            tag = "warning"
        elif any(marker in message for marker in ("成功", "完成")):
            tag = "success"
        else:
            tag = None
        lane, lane_tag = self._log_lane(message)
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.insert(tk.END, f"[{timestamp}] ", "timestamp")
        self.log_output.insert(tk.END, f"[{lane}] ", lane_tag)
        if tag is None:
            self.log_output.insert(tk.END, f"{message}\n")
        else:
            self.log_output.insert(tk.END, f"{message}\n", tag)
        self.log_output.see(tk.END)
        self.log_output.configure(state=tk.DISABLED)

    @staticmethod
    def _log_lane(message: str) -> tuple[str, str]:
        if any(
            marker in message
            for marker in ("预取视频", "下载音频", "音频已存在", "筛选跳过")
        ):
            return "下载", "download"
        if any(
            marker in message
            for marker in ("转写", "Whisper", "whisper", "MLX", "语音转录后端")
        ):
            return "转录", "transcribe"
        if any(marker in message for marker in ("摘要和关键词", "入库")):
            return "分析", "analysis"
        return "任务", "task"

