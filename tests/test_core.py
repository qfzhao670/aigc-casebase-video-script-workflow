import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bili_script_tool.domain import CaseAnalysis, CaseRecord, VideoMetadata
from bili_script_tool.config import installed_whisper_models
from bili_script_tool.errors import AIServiceError, DataValidationError
from bili_script_tool.services.ai_service import _parse_json, _prefilter_cases
from bili_script_tool.services.case_repository import CaseRepository
from bili_script_tool.services.media_service import MediaService, _extract_percent
from bili_script_tool.services.workflows import CaseBuildWorkflow


def make_case(bvid: str, title: str, keywords=None) -> CaseRecord:
    return CaseRecord(
        uploader="tester",
        bvid=bvid,
        title=title,
        text="transcript",
        summary=f"{title} summary",
        keywords=keywords or [],
    )


class CaseRecordTests(unittest.TestCase):
    def test_accepts_legacy_string_keywords(self):
        record = CaseRecord.from_mapping(
            {"bvid": "BV1", "keywords": "科技, 口语", "title": "demo"}
        )
        self.assertEqual(record.keywords, ["科技", "口语"])

    def test_requires_bvid(self):
        with self.assertRaises(DataValidationError):
            CaseRecord.from_mapping({"title": "missing id"})


class RepositoryTests(unittest.TestCase):
    def test_round_trip_and_ordered_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            repository = CaseRepository(path)
            repository.append(make_case("BV1", "one"))
            repository.append(make_case("BV2", "two"))

            self.assertEqual([item.bvid for item in repository.load_all()], ["BV1", "BV2"])
            self.assertEqual(
                [item.bvid for item in repository.find_by_bvids(["BV2", "BV1"])],
                ["BV2", "BV1"],
            )

    def test_reports_invalid_line_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cases.jsonl"
            path.write_text(json.dumps({"bvid": "BV1"}) + "\nnot-json\n", encoding="utf-8")
            with self.assertRaisesRegex(DataValidationError, "第 2 行"):
                CaseRepository(path).load_all()


class AIHelpersTests(unittest.TestCase):
    def test_parses_json_code_fence(self):
        self.assertEqual(_parse_json('```json\n["BV1"]\n```'), ["BV1"])

    def test_rejects_missing_json(self):
        with self.assertRaises(AIServiceError):
            _parse_json("no structured data")

    def test_prefilter_prioritizes_requirement_matches(self):
        cases = [
            make_case("BV1", "美食探店", ["餐厅"]),
            make_case("BV2", "人工智能观察", ["科技", "AI"]),
        ]
        selected = _prefilter_cases(cases, "科技类人工智能视频", limit=1)
        self.assertEqual(selected[0].bvid, "BV2")


class MediaProgressTests(unittest.TestCase):
    def test_lists_only_downloaded_multilingual_models(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            (model_dir / "small.pt").touch()
            (model_dir / "large-v3-turbo.pt").touch()
            (model_dir / "tiny.en.pt").touch()

            self.assertEqual(
                installed_whisper_models(model_dir),
                ["small", "turbo"],
            )

    def test_media_service_accepts_frontend_model_override(self):
        class Settings:
            whisper_model = "turbo"

        service = MediaService(Settings(), whisper_model="small")
        self.assertEqual(service.whisper_model, "small")

    def test_extracts_download_and_whisper_percentages(self):
        self.assertEqual(_extract_percent("[download]  42.3% of 10MiB"), 42.3)
        self.assertEqual(_extract_percent(" 67%|###### | 123/456 frames"), 67.0)
        self.assertEqual(_extract_percent("\x1b[32m100%\x1b[0m"), 100.0)
        self.assertIsNone(_extract_percent("loading model"))

    def test_streaming_runner_splits_carriage_return_progress(self):
        service = object.__new__(MediaService)
        output = []
        service._run_streaming(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('10%\\r50%\\r100%\\n'); sys.stdout.flush()",
            ],
            output.append,
        )
        self.assertEqual(output, ["10%", "50%", "100%"])


class CaseBuildProgressTests(unittest.TestCase):
    def test_reports_transcription_and_overall_progress(self):
        class Repository:
            def existing_bvids(self):
                return set()

            def append(self, record):
                self.record = record

        class Media:
            def check_dependencies(self):
                pass

            def get_metadata(self, bvid):
                return VideoMetadata("uploader", bvid, "title")

            def download_audio(self, metadata, progress=None):
                for value in (0.0, 50.0, 100.0):
                    progress(value)
                return Path(f"{metadata.bvid}.wav")

            def transcribe(self, audio_path, progress=None):
                for value in (0.0, 50.0, 100.0):
                    progress(value)
                return "transcript"

        class AI:
            def analyze_transcript(self, transcript):
                return CaseAnalysis("summary", ["keyword"])

        updates = []
        repository = Repository()
        workflow = CaseBuildWorkflow(
            repository=repository,
            media=Media(),
            ai=AI(),
            progress=lambda stage, overall, stage_percent: updates.append(
                (stage, overall, stage_percent)
            ),
        )

        workflow.run(["BV1"])

        transcription_halfway = next(
            update
            for update in updates
            if "语音转录" in update[0] and update[2] == 50.0
        )
        self.assertAlmostEqual(transcription_halfway[1], 57.5)
        self.assertEqual(updates[-1], ("案例库构建完成", 100.0, 100.0))
        self.assertEqual(repository.record.bvid, "BV1")


if __name__ == "__main__":
    unittest.main()

