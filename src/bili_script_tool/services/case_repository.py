"""JSON Lines persistence for the case library."""

import json
from pathlib import Path
from typing import Iterable, List, Set

from ..domain import CaseRecord
from ..errors import DataValidationError


class CaseRepository:
    def __init__(self, path: Path):
        self.path = path

    def load_all(self) -> List[CaseRecord]:
        if not self.path.exists():
            return []

        records = []
        with self.path.open("r", encoding="utf-8") as source:
            for line_number, raw_line in enumerate(source, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                    records.append(CaseRecord.from_mapping(value))
                except (json.JSONDecodeError, DataValidationError) as exc:
                    raise DataValidationError(
                        f"案例库 {self.path} 第 {line_number} 行无效：{exc}"
                    ) from exc
        return records

    def existing_bvids(self) -> Set[str]:
        return {record.bvid for record in self.load_all()}

    def append(self, record: CaseRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(record.to_mapping(), ensure_ascii=False) + "\n")

    def find_by_bvids(self, bvids: Iterable[str]) -> List[CaseRecord]:
        records_by_id = {record.bvid: record for record in self.load_all()}
        return [records_by_id[bvid] for bvid in bvids if bvid in records_by_id]

