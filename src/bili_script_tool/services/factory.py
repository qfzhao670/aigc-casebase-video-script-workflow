"""Central construction of application workflows."""

from pathlib import Path
from typing import Callable, Optional

from ..config import Settings
from .ai_service import DashScopeService
from .case_repository import CaseRepository
from .media_service import MediaService
from .workflows import CaseBuildWorkflow, ProgressCallback, ScriptGenerationWorkflow


class ServiceFactory:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _analysis_ai_service(self) -> DashScopeService:
        return DashScopeService(
            api_key=self.settings.require_api_key(),
            model=self.settings.dashscope_analysis_model,
        )

    def _generation_ai_service(self) -> DashScopeService:
        return DashScopeService(
            api_key=self.settings.require_api_key(),
            model=self.settings.dashscope_generation_model,
        )

    def case_builder(
        self,
        library_path: Path,
        log: Optional[Callable[[str], None]] = None,
        progress: Optional[ProgressCallback] = None,
        whisper_model: Optional[str] = None,
    ) -> CaseBuildWorkflow:
        return CaseBuildWorkflow(
            repository=CaseRepository(library_path),
            media=MediaService(
                self.settings,
                log=log,
                whisper_model=whisper_model,
            ),
            ai=self._analysis_ai_service(),
            log=log,
            progress=progress,
        )

    def script_generator(self, library_path: Path) -> ScriptGenerationWorkflow:
        return ScriptGenerationWorkflow(
            repository=CaseRepository(library_path),
            ai=self._generation_ai_service(),
        )

