"""Reference selection and script generation tab."""

from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List

from ..config import Settings
from ..domain import CaseRecord
from ..services.factory import ServiceFactory


DEFAULT_REQUIREMENTS = """1. 口语化，适合视频口播。
2. 逻辑顺畅，过渡自然。
3. 直接输出最终文案正文，不要包含前言或后记。"""


class ScriptGeneratorTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, settings: Settings, factory: ServiceFactory):
        super().__init__(parent, padding=12)
        self.settings = settings
        self.factory = factory
        self.selected_cases: List[CaseRecord] = []
        self._create_widgets()

    def _create_widgets(self) -> None:
        inputs = ttk.LabelFrame(self, text="输入", padding=8)
        inputs.pack(fill=tk.X)
        inputs.columnconfigure(1, weight=1)

        self.library_path = tk.StringVar(value=str(self.settings.default_library))
        self.outline_path = tk.StringVar(value=str(self.settings.default_outline))
        self.selection_requirement = tk.StringVar()
        self.top_n = tk.StringVar(value="3")

        ttk.Label(inputs, text="案例库：").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(inputs, textvariable=self.library_path).grid(
            row=0, column=1, sticky=tk.EW, padx=6
        )
        ttk.Button(inputs, text="选择…", command=self._browse_library).grid(row=0, column=2)

        ttk.Label(inputs, text="大纲文件：").grid(row=1, column=0, sticky=tk.W, pady=6)
        ttk.Entry(inputs, textvariable=self.outline_path).grid(
            row=1, column=1, sticky=tk.EW, padx=6, pady=6
        )
        ttk.Button(inputs, text="选择…", command=self._browse_outline).grid(row=1, column=2)

        ttk.Label(inputs, text="案例筛选要求：").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(inputs, textvariable=self.selection_requirement).grid(
            row=2, column=1, sticky=tk.EW, padx=6
        )
        controls = ttk.Frame(inputs)
        controls.grid(row=2, column=2, sticky=tk.E)
        ttk.Combobox(
            controls,
            textvariable=self.top_n,
            values=[str(value) for value in range(1, 11)],
            width=3,
            state="readonly",
        ).pack(side=tk.LEFT)
        self.search_button = ttk.Button(controls, text="筛选", command=self._start_search)
        self.search_button.pack(side=tk.LEFT, padx=(5, 0))

        requirement_frame = ttk.LabelFrame(self, text="文案生成要求", padding=8)
        requirement_frame.pack(fill=tk.X, pady=8)
        self.generation_requirements = scrolledtext.ScrolledText(requirement_frame, height=5)
        self.generation_requirements.pack(fill=tk.X)
        self.generation_requirements.insert("1.0", DEFAULT_REQUIREMENTS)

        selection_frame = ttk.LabelFrame(
            self, text="参考案例（右侧 BV 号可手动修改）", padding=8
        )
        selection_frame.pack(fill=tk.BOTH, expand=True)
        selection_pane = ttk.PanedWindow(selection_frame, orient=tk.HORIZONTAL)
        selection_pane.pack(fill=tk.BOTH, expand=True)
        self.case_details = scrolledtext.ScrolledText(selection_pane, height=8, state=tk.DISABLED)
        self.selected_bvids = scrolledtext.ScrolledText(selection_pane, height=8, width=28)
        selection_pane.add(self.case_details, weight=3)
        selection_pane.add(self.selected_bvids, weight=1)

        action_frame = ttk.Frame(self)
        action_frame.pack(fill=tk.X, pady=8)
        self.generate_button = ttk.Button(
            action_frame,
            text="生成文案",
            command=self._start_generation,
            state=tk.DISABLED,
        )
        self.generate_button.pack(side=tk.RIGHT)

        output_frame = ttk.LabelFrame(self, text="生成结果", padding=8)
        output_frame.pack(fill=tk.BOTH, expand=True)
        self.result_output = scrolledtext.ScrolledText(output_frame, height=14)
        self.result_output.pack(fill=tk.BOTH, expand=True)
        ttk.Button(output_frame, text="保存结果…", command=self._save_result).pack(
            fill=tk.X, pady=(6, 0)
        )

        self.status = tk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status).pack(fill=tk.X, pady=(5, 0))

    def _browse_library(self) -> None:
        path = filedialog.askopenfilename(
            title="选择案例库",
            initialdir=str(self.settings.data_dir),
            filetypes=[("JSON Lines", "*.jsonl"), ("所有文件", "*.*")],
        )
        if path:
            self.library_path.set(path)

    def _browse_outline(self) -> None:
        path = filedialog.askopenfilename(
            title="选择大纲",
            initialdir=str(self.settings.project_root / "examples"),
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self.outline_path.set(path)

    def _start_search(self) -> None:
        library_path = Path(self.library_path.get().strip())
        requirement = self.selection_requirement.get().strip()
        if not library_path.is_file():
            messagebox.showwarning("案例库无效", "请选择有效的案例库文件。")
            return
        if not requirement:
            messagebox.showwarning("缺少筛选要求", "请输入案例筛选要求。")
            return

        self._set_busy(True, "正在筛选参考案例……")
        threading.Thread(
            target=self._search_worker,
            args=(library_path, requirement, int(self.top_n.get())),
            daemon=True,
        ).start()

    def _search_worker(self, library_path: Path, requirement: str, top_n: int) -> None:
        try:
            workflow = self.factory.script_generator(library_path)
            selected = workflow.select_cases(requirement, top_n)
            self.after(0, self._show_selected_cases, selected)
        except Exception as exc:
            self.after(0, messagebox.showerror, "案例筛选失败", str(exc))
        finally:
            self.after(0, self._set_busy, False, "就绪")

    def _show_selected_cases(self, cases: List[CaseRecord]) -> None:
        self.selected_cases = cases
        detail_lines = [
            f"{index}. {case.title}\n   作者：{case.uploader}\n   BV：{case.bvid}"
            for index, case in enumerate(cases, start=1)
        ]
        self.case_details.configure(state=tk.NORMAL)
        self.case_details.delete("1.0", tk.END)
        self.case_details.insert(tk.END, "\n\n".join(detail_lines) or "没有匹配到案例")
        self.case_details.configure(state=tk.DISABLED)
        self.selected_bvids.delete("1.0", tk.END)
        self.selected_bvids.insert(tk.END, "\n".join(case.bvid for case in cases))
        self.generate_button.configure(state=tk.NORMAL if cases else tk.DISABLED)

    def _start_generation(self) -> None:
        library_path = Path(self.library_path.get().strip())
        outline_path = Path(self.outline_path.get().strip())
        bvids = [
            line.strip()
            for line in self.selected_bvids.get("1.0", tk.END).splitlines()
            if line.strip()
        ]
        requirements = self.generation_requirements.get("1.0", tk.END).strip()
        if not library_path.is_file() or not outline_path.is_file():
            messagebox.showwarning("文件无效", "请检查案例库和大纲文件。")
            return
        if not bvids or not requirements:
            messagebox.showwarning("输入不完整", "请保留参考案例并填写文案要求。")
            return

        self._set_busy(True, "正在生成文案……")
        threading.Thread(
            target=self._generation_worker,
            args=(library_path, outline_path, bvids, requirements),
            daemon=True,
        ).start()

    def _generation_worker(
        self,
        library_path: Path,
        outline_path: Path,
        bvids: List[str],
        requirements: str,
    ) -> None:
        try:
            workflow = self.factory.script_generator(library_path)
            result = workflow.generate(bvids, outline_path, requirements)
            self.after(0, self._show_result, result)
        except Exception as exc:
            self.after(0, messagebox.showerror, "文案生成失败", str(exc))
        finally:
            self.after(0, self._set_busy, False, "就绪")

    def _show_result(self, result: str) -> None:
        self.result_output.delete("1.0", tk.END)
        self.result_output.insert(tk.END, result)

    def _save_result(self) -> None:
        content = self.result_output.get("1.0", tk.END).strip()
        if not content:
            messagebox.showinfo("没有内容", "当前没有可以保存的文案。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            messagebox.showinfo("保存成功", f"文案已保存到：\n{path}")

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status.set(status)
        self.search_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        if busy:
            self.generate_button.configure(state=tk.DISABLED)
        elif self.selected_bvids.get("1.0", tk.END).strip():
            self.generate_button.configure(state=tk.NORMAL)

