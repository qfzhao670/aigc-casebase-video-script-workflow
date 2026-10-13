import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bili_script_tool.config import WHISPER_MODEL
from bili_script_tool.domain import CaseAnalysis, CaseRecord, VideoMetadata
from bili_script_tool.errors import AIServiceError, DataValidationError, ExternalCommandError
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
    def test_uses_large_v3_turbo_model(self):
        self.assertEqual(WHISPER_MODEL, "large-v3-turbo")

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

    def test_get_user_bvids_uses_recent_flat_playlist(self):
        service = object.__new__(MediaService)
        service._run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [],
                0,
                stdout="BV1xx411c7mD\nBV1YY411c7Ab\nBV1xx411c7mD\n",
                stderr="",
            )
        )

        with mock.patch(
            "bili_script_tool.services.media_service.require_executable",
            return_value="/usr/bin/yt-dlp",
        ):
            result = service.get_user_bvids(" 12345 ", 2)

        self.assertEqual(result, ["BV1xx411c7mD", "BV1YY411c7Ab"])
        command = service._run.call_args.args[0]
        self.assertIn("--flat-playlist", command)
        self.assertEqual(command[command.index("--playlist-end") + 1], "2")
        self.assertEqual(command[-1], "https://space.bilibili.com/12345/video")

    def test_get_user_bvids_validates_uid_and_limit(self):
        service = object.__new__(MediaService)
        with self.assertRaises(DataValidationError):
            service.get_user_bvids("not-a-uid", 10)
        with self.assertRaises(DataValidationError):
            service.get_user_bvids("123", 0)

    def test_get_user_bvids_retries_risk_errors_with_browser_cookies(self):
        errors = {
            "412": "Request is blocked by server (412)",
            "352": "Request is rejected by server (352)",
        }
        for risk_code, error_message in errors.items():
            with self.subTest(risk_code=risk_code):
                service = object.__new__(MediaService)
                service.log = mock.Mock()
                service._run = mock.Mock(
                    side_effect=[
                        ExternalCommandError(error_message),
                        subprocess.CompletedProcess(
                            [],
                            0,
                            stdout="BV1Mhp46jEVW\n",
                            stderr="",
                        ),
                    ]
                )

                with mock.patch(
                    "bili_script_tool.services.media_service.require_executable",
                    return_value="/usr/bin/yt-dlp",
                ):
                    result = service.get_user_bvids(
                        "16502953",
                        1,
                        cookies_from_browser="chrome",
                    )

                self.assertEqual(result, ["BV1Mhp46jEVW"])
                self.assertEqual(service._run.call_count, 2)
                retry_command = service._run.call_args_list[1].args[0]
                self.assertEqual(
                    retry_command[retry_command.index("--cookies-from-browser") + 1],
                    "chrome",
                )
                self.assertIn(risk_code, service.log.call_args.args[0])


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

    def test_resolves_uid_before_running_existing_flow(self):
        class Repository:
            def existing_bvids(self):
                return set()

            def append(self, record):
                pass

        class Media:
            def get_user_bvids(self, uid, limit):
                self.request = (uid, limit)
                return ["BV1xx411c7mD"]

            def check_dependencies(self):
                pass

            def get_metadata(self, bvid):
                return VideoMetadata("uploader", bvid, "title")

            def download_audio(self, metadata, progress=None):
                progress(100.0)
                return Path(f"{metadata.bvid}.wav")

            def transcribe(self, audio_path, progress=None):
                progress(100.0)
                return "transcript"

        class AI:
            def analyze_transcript(self, transcript):
                return CaseAnalysis("summary", ["keyword"])

        media = Media()
        resolved = []
        workflow = CaseBuildWorkflow(Repository(), media, AI())
        result = workflow.run_from_user("12345", 1, on_bvids=resolved.extend)

        self.assertEqual(media.request, ("12345", 1))
        self.assertEqual(result, ["BV1xx411c7mD"])
        self.assertEqual(resolved, ["BV1xx411c7mD"])

    def test_resolves_multiple_uids_and_deduplicates_bvids(self):
        class Repository:
            def existing_bvids(self):
                return set()

            def append(self, record):
                pass

        class Media:
            def __init__(self):
                self.requests = []

            def get_user_bvids(self, uid, limit, cookies_from_browser=None):
                self.requests.append((uid, limit, cookies_from_browser))
                return {
                    "100": ["BV1xx411c7mD", "BV1YY411c7Ab"],
                    "200": ["BV1YY411c7Ab", "BV1ZZ411c7Cd"],
                }[uid]

            def check_dependencies(self):
                pass

            def get_metadata(self, bvid):
                return VideoMetadata("uploader", bvid, "title")

            def download_audio(self, metadata, progress=None):
                progress(100.0)
                return Path(f"{metadata.bvid}.wav")

            def transcribe(self, audio_path, progress=None):
                progress(100.0)
                return "transcript"

        class AI:
            def analyze_transcript(self, transcript):
                return CaseAnalysis("summary", ["keyword"])

        media = Media()
        resolved = []
        workflow = CaseBuildWorkflow(Repository(), media, AI())
        result = workflow.run_from_users(
            ["100", "200", "100"],
            2,
            on_bvids=resolved.extend,
            cookies_from_browser="chrome",
        )

        self.assertEqual(
            media.requests,
            [("100", 2, "chrome"), ("200", 2, "chrome")],
        )
        self.assertEqual(
            result,
            ["BV1xx411c7mD", "BV1YY411c7Ab", "BV1ZZ411c7Cd"],
        )
        self.assertEqual(resolved, result)


if __name__ == "__main__":
    unittest.main()

