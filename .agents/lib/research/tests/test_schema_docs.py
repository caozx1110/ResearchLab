from __future__ import annotations

import re
from pathlib import Path

from research.v2 import UNIT_KIND_DIRS, kind_payload_skeleton


def test_schema_payload_sections_are_backed_by_skeleton_keys() -> None:
    project_root = Path(__file__).resolve().parents[4]
    schemas = project_root / ".agents/lib/research/SCHEMAS.md"
    text = schemas.read_text(encoding="utf-8")
    table_lines = [line for line in text.splitlines() if re.match(r"^\| (paper|repo|blog|idea|experiment) \|", line)]

    assert set(UNIT_KIND_DIRS) == {line.split("|")[1].strip() for line in table_lines}
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        kind, section_cell = cells[0], cells[1]
        documented = {token.split("{", 1)[0] for token in re.findall(r"`([^`]+)`", section_cell)}
        skeleton_keys = set(kind_payload_skeleton(kind))
        assert documented <= skeleton_keys
