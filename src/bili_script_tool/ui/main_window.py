"""Top-level application window."""

import tkinter as tk
from tkinter import ttk

from ..config import Settings
from ..services.factory import ServiceFactory
from .case_builder_tab import CaseBuilderTab
from .script_generator_tab import ScriptGeneratorTab


class MainWindow(tk.Tk):
    def __init__(self, settings: Settings):
        super().__init__()
        self.title("Bilibili 视频文案工具")
        self.geometry("1000x850")
        self.minsize(820, 680)

        style = ttk.Style(self)
        if "aqua" in style.theme_names():
            style.theme_use("aqua")

        factory = ServiceFactory(settings)
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)
        notebook.add(
            CaseBuilderTab(notebook, settings, factory),
            text="案例库构建",
        )
        notebook.add(
            ScriptGeneratorTab(notebook, settings, factory),
            text="文案生成",
        )

