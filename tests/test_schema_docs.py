from __future__ import annotations

import re
from pathlib import Path

from repo_paths import REPO_ROOT

from research.core import UNIT_KIND_DIRS, kind_payload_skeleton
from research.paper_notes import (
    PAPER_DEEP_READ_SCHEMA,
    PAPER_NOTE_CLAIM_SCHEMA,
    PAPER_NOTE_FILL_SCHEMA,
    PAPER_TYPES,
    required_paper_sections,
)


def test_schema_payload_sections_are_backed_by_skeleton_keys() -> None:
    project_root = REPO_ROOT
    schemas = project_root / "runtime/lib/research/SCHEMAS.md"
    text = schemas.read_text(encoding="utf-8")
    table_lines = [line for line in text.splitlines() if re.match(r"^\| (paper|repo|dataset|blog|idea|experiment|concept) \|", line)]

    assert set(UNIT_KIND_DIRS) == {line.split("|")[1].strip() for line in table_lines}
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        kind, section_cell = cells[0], cells[1]
        documented = {token.split("{", 1)[0] for token in re.findall(r"`([^`]+)`", section_cell)}
        skeleton_keys = set(kind_payload_skeleton(kind))
        assert documented <= skeleton_keys


def test_schema_confirmation_gate_documents_default_confirmer_and_evidence() -> None:
    project_root = REPO_ROOT
    text = (project_root / "runtime/lib/research/SCHEMAS.md").read_text(encoding="utf-8")

    assert "`--confirmed-by` 或 `identity.default_confirmed_by`" in text
    assert "至少一条 `--evidence`" in text


def test_paper_v2_schema_documentation_tracks_the_runtime_matrix() -> None:
    text = (REPO_ROOT / "runtime/lib/research/SCHEMAS.md").read_text(encoding="utf-8")
    paper_contract = text.split(
        '### paper 类型与多维深读矩阵 <a id="paper-element-sets"></a>', 1
    )[1].split("\n---\n", 1)[0]

    for schema in (
        PAPER_NOTE_FILL_SCHEMA,
        PAPER_DEEP_READ_SCHEMA,
        PAPER_NOTE_CLAIM_SCHEMA,
    ):
        assert schema in paper_contract
    for paper_type in PAPER_TYPES:
        assert f"`{paper_type}`" in paper_contract
        for spec in required_paper_sections(paper_type):
            assert f"`{spec.section_id}`" in paper_contract
            for claim_type in spec.claim_types:
                assert f"`{claim_type}`" in paper_contract
