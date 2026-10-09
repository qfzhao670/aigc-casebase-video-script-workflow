"""Case-library builder tab."""

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

from ..config import Settings, installed_whisper_models
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
        file_frame = ttk.Frame(self)
        file_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(file_frame, text="案例库文件：").pack(side=tk.LEFT)
        self.library_path = tk.StringVar(value=str(self.settings.default_library))
        ttk.Entry(file_frame, textvariable=self.library_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(file_frame, text="选择…", command=self._browse_library).pack(side=tk.LEFT)

        model_frame = ttk.Frame(self)
        model_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(model_frame, text="Whisper 模型：").pack(side=tk.LEFT)
        local_models = installed_whisper_models(self.settings.whisper_model_dir)
        if self.settings.whisper_model not in local_models:
            local_models.insert(0, self.settings.whisper_model)
        self.whisper_model = tk.StringVar(value=self.settings.whisper_model)
        self.model_selector = ttk.Combobox(
            model_frame,
            textvariable=self.whisper_model,
            values=local_models,
            state="readonly",
            width=18,
        )
        self.model_selector.pack(side=tk.LEFT, padx=6)
        ttk.Label(model_frame, text="仅显示项目内已下载的模型").pack(side=tk.LEFT)

        input_frame = ttk.LabelFrame(self, text="B 站 BV 号（每行一个）", padding=8)
        input_frame.pack(fill=tk.BOTH, expand=True)
        self.bvid_input = scrolledtext.ScrolledText(input_frame, height=10)
        self.bvid_input.pack(fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, pady=8)
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

        progress_frame = ttk.LabelFrame(self, text="任务进度", padding=8)
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        self.progress_status = tk.StringVar(value="就绪")
        ttk.Label(progress_frame, textvariable=self.progress_status).pack(
            fill=tk.X, pady=(0, 5)
        )
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_value,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.pack(fill=tk.X)

        log_frame = ttk.LabelFrame(self, text="执行日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_output = scrolledtext.ScrolledText(log_frame, height=16, state=tk.DISABLED)
        self.log_output.pack(fill=tk.BOTH, expand=True)

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
        model_name = self.whisper_model.get().strip()
        bvids = [line.strip() for line in self.bvid_input.get("1.0", tk.END).splitlines()]
        bvids = [bvid for bvid in bvids if bvid]
        if not path_text:
            messagebox.showwarning("缺少案例库", "请选择案例库文件。")
            return
        if not bvids:
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
        self._append_log(f"本次使用 Whisper 模型：{model_name}")
        self._schedule_event_poll()
        worker = threading.Thread(
            target=self._run_worker,
            args=(Path(path_text), bvids, model_name),
            daemon=True,
        )
        worker.start()

    def _run_worker(
        self,
        library_path: Path,
        bvids: list,
        model_name: str,
    ) -> None:
        try:
            workflow = self.factory.case_builder(
                library_path,
                log=self._thread_log,
                progress=self._thread_progress,
                whisper_model=model_name,
            )
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
        self.bvid_input.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.model_selector.configure(state=tk.DISABLED if running else "readonly")

    def _thread_log(self, message: str) -> None:
        self._ui_events.put(("log", message))

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

