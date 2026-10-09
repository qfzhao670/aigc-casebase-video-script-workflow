import json
from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bili_script_tool.domain import CaseRecord
from bili_script_tool.errors import AIServiceError, DataValidationError
from bili_script_tool.services.ai_service import _parse_json, _prefilter_cases
from bili_script_tool.services.case_repository import CaseRepository


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


if __name__ == "__main__":
    unittest.main()

