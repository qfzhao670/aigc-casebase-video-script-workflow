"""Case-library builder tab."""

from datetime import datetime
from pathlib import Path
import queue
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
        self._last_progress_stage = ""
        self._last_progress_bucket = -1
        self._create_widgets()

    def _create_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

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

        ttk.Label(settings_frame, text="UID 列表").grid(
            row=3, column=0, sticky=tk.NW, padx=(0, 12), pady=(10, 0)
        )
        self.uid_input = scrolledtext.ScrolledText(
            settings_frame,
            height=3,
            wrap=tk.NONE,
        )
        self.uid_input.grid(row=3, column=1, sticky=tk.EW, pady=(10, 0))

        count_frame = ttk.Frame(settings_frame)
        count_frame.grid(row=3, column=2, sticky=tk.NW, padx=(12, 0), pady=(10, 0))
        ttk.Label(count_frame, text="每个 UID 最近").grid(row=0, column=0, columnspan=2)
        self.video_count = tk.StringVar(value="10")
        self.count_input = ttk.Spinbox(
            count_frame,
            from_=1,
            to=1000,
            textvariable=self.video_count,
            width=6,
        )
        self.count_input.grid(row=1, column=0, pady=(5, 0))
        ttk.Label(count_frame, text="条").grid(
            row=1, column=1, sticky=tk.W, padx=(5, 0), pady=(5, 0)
        )
        ttk.Label(settings_frame, text="每行一个纯数字 UID").grid(
            row=4, column=1, sticky=tk.W, pady=(4, 0)
        )
        self.use_chrome_cookies = tk.BooleanVar(value=True)
        self.cookie_retry_button = ttk.Checkbutton(
            settings_frame,
            text="遇到 412/352 风控时，使用 Chrome 的 B 站登录状态重试",
            variable=self.use_chrome_cookies,
        )
        self.cookie_retry_button.grid(
            row=5, column=1, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        input_frame = ttk.LabelFrame(
            self,
            text="BV 号列表 · 每行一个（UID 模式下自动填入）",
            padding=10,
        )
        input_frame.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        input_frame.columnconfigure(0, weight=1)
        self.bvid_input = scrolledtext.ScrolledText(input_frame, height=6, wrap=tk.NONE)
        self.bvid_input.grid(row=0, column=0, sticky=tk.EW)

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

        progress_frame = ttk.LabelFrame(self, text="任务进度", padding=10)
        progress_frame.grid(row=2, column=0, sticky=tk.EW, pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        self.progress_status = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.progress_status).grid(
            row=0, column=0, sticky=tk.W, pady=(0, 6)
        )
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_value,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.grid(row=1, column=0, sticky=tk.EW)

        log_frame = ttk.LabelFrame(self, text="执行日志", padding=10)
        log_frame.grid(row=3, column=0, sticky=tk.NSEW)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_output = scrolledtext.ScrolledText(
            log_frame,
            height=10,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log_output.grid(row=0, column=0, sticky=tk.NSEW)
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

        self.stop_event.clear()
        self._discard_pending_events()
        self._clear_log()
        self.progress_value.set(0.0)
        self.progress_status.set("正在启动……")
        self._last_progress_stage = ""
        self._last_progress_bucket = -1
        self._worker_active = True
        self._set_running(True)
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
                bvids,
                "chrome" if self.use_chrome_cookies.get() else None,
            ),
            daemon=True,
        )
        worker.start()

    def _run_worker(
        self,
        library_path: Path,
        mode: str,
        uids: list,
        count: int,
        bvids: list,
        cookies_from_browser: Optional[str],
    ) -> None:
        try:
            workflow = self.factory.case_builder(
                library_path,
                log=self._thread_log,
                progress=self._thread_progress,
            )
            if mode == "uid":
                workflow.run_from_users(
                    uids,
                    count,
                    should_stop=self.stop_event.is_set,
                    on_bvids=self._thread_bvids,
                    cookies_from_browser=cookies_from_browser,
                )
            else:
                workflow.run(bvids, should_stop=self.stop_event.is_set)
            self._thread_log("任务结束。")
        except Exception as exc:
            self._thread_log(f"任务失败：{exc}")
            self._ui_events.put(("error", str(exc)))
        finally:
            self._ui_events.put(("finished",))

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
            self.bvid_input.configure(state=tk.DISABLED)
        else:
            self._update_source_controls()

    def _update_source_controls(self) -> None:
        uid_mode = self.source_mode.get() == "uid"
        self.uid_input.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
        self.count_input.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
        self.cookie_retry_button.configure(state=tk.NORMAL if uid_mode else tk.DISABLED)
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
        while True:
            try:
                event = self._ui_events.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "log":
                self._append_log(event[1])
            elif event_type == "bvids":
                self.bvid_input.configure(state=tk.NORMAL)
                self.bvid_input.delete("1.0", tk.END)
                self.bvid_input.insert("1.0", "\n".join(event[1]))
                self.bvid_input.configure(state=tk.DISABLED)
            elif event_type == "progress":
                self._show_progress(event[1], event[2], event[3])
            elif event_type == "error":
                self.progress_status.set("任务失败")
                messagebox.showerror("案例库构建失败", event[1])
            elif event_type == "finished":
                self._worker_active = False
                self._set_running(False)
                if self.stop_event.is_set():
                    self.progress_status.set("任务已停止")

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
        if stage_percent is None:
            status = f"{stage}（总进度 {overall_percent:.0f}%）"
        else:
            stage_percent = max(0.0, min(100.0, stage_percent))
            status = (
                f"{stage}：{stage_percent:.0f}%"
                f"（总进度 {overall_percent:.0f}%）"
            )
        self.progress_status.set(status)

        bucket = -1 if stage_percent is None else int(stage_percent // 10)
        if stage != self._last_progress_stage:
            self._append_log(status)
            self._last_progress_stage = stage
            self._last_progress_bucket = bucket
        elif bucket > self._last_progress_bucket:
            self._append_log(status)
            self._last_progress_bucket = bucket

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
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_output.see(tk.END)
        self.log_output.configure(state=tk.DISABLED)

