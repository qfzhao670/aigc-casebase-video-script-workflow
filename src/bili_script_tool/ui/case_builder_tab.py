"""Case-library builder tab."""

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..config import Settings
from ..services.factory import ServiceFactory


class CaseBuilderTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, settings: Settings, factory: ServiceFactory):
        super().__init__(parent, padding=12)
        self.settings = settings
        self.factory = factory
        self.stop_event = threading.Event()
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
        bvids = [line.strip() for line in self.bvid_input.get("1.0", tk.END).splitlines()]
        bvids = [bvid for bvid in bvids if bvid]
        if not path_text:
            messagebox.showwarning("缺少案例库", "请选择案例库文件。")
            return
        if not bvids:
            messagebox.showwarning("缺少 BV 号", "请至少输入一个 BV 号。")
            return

        self.stop_event.clear()
        self._set_running(True)
        self._append_log("开始执行案例库构建任务。")
        worker = threading.Thread(
            target=self._run_worker,
            args=(Path(path_text), bvids),
            daemon=True,
        )
        worker.start()

    def _run_worker(self, library_path: Path, bvids: list) -> None:
        try:
            workflow = self.factory.case_builder(library_path, log=self._thread_log)
            workflow.run(bvids, should_stop=self.stop_event.is_set)
            self._thread_log("任务结束。")
        except Exception as exc:
            self._thread_log(f"任务失败：{exc}")
            self.after(0, messagebox.showerror, "案例库构建失败", str(exc))
        finally:
            self.after(0, self._set_running, False)

    def _request_stop(self) -> None:
        self.stop_event.set()
        self._append_log("已请求停止；当前步骤结束后将退出。")
        self.stop_button.configure(state=tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.bvid_input.configure(state=tk.DISABLED if running else tk.NORMAL)

    def _thread_log(self, message: str) -> None:
        self.after(0, self._append_log, message)

    def _append_log(self, message: str) -> None:
        self.log_output.configure(state=tk.NORMAL)
        self.log_output.insert(tk.END, message + "\n")
        self.log_output.see(tk.END)
        self.log_output.configure(state=tk.DISABLED)

