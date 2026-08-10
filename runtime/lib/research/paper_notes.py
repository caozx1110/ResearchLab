"""Versioned contracts for multidimensional paper deep-read notes.

The runtime Agent authors every summary and claim.  This module only owns the
stable schema identities, required section matrix, claim-type boundaries, and
the narrow v2 detection used by generic receipt currentness checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PAPER_NOTE_FILL_SCHEMA = "paper-note-fill/v2"
PAPER_DEEP_READ_SCHEMA = "paper-deep-read/v2"
PAPER_NOTE_CLAIM_SCHEMA = "paper-note-claim/v2"
PAPER_TYPES: tuple[str, ...] = ("method_system", "benchmark", "survey")


@dataclass(frozen=True)
class PaperSectionSpec:
    section_id: str
    heading: str
    claim_types: tuple[str, ...]

    def contract_payload(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "heading": self.heading,
            "claim_types": list(self.claim_types),
        }


COMMON_PAPER_SECTIONS: tuple[PaperSectionSpec, ...] = (
    PaperSectionSpec("research_problem", "Research Problem and Motivation", ("inference",)),
    PaperSectionSpec("contributions", "Contributions and Innovations", ("inference", "evaluation")),
    PaperSectionSpec("approach", "Approach", ("inference",)),
    PaperSectionSpec("evaluation_design", "Evaluation Design and Comparisons", ("inference", "evaluation")),
    PaperSectionSpec("results_boundaries", "Results and Boundaries", ("evaluation",)),
    PaperSectionSpec("limitations_reliability", "Limitations, Assumptions, and Reliability", ("evaluation",)),
    PaperSectionSpec("transfer_open_questions", "Transferable Insights and Open Questions", ("inference", "evaluation")),
)

TYPE_PAPER_SECTIONS: dict[str, tuple[PaperSectionSpec, ...]] = {
    "method_system": (
        PaperSectionSpec("architecture_mechanism", "Architecture and Mechanism", ("inference",)),
        PaperSectionSpec("training_inference", "Training and Inference", ("inference",)),
        PaperSectionSpec("baselines_ablations", "Baselines and Ablations", ("evaluation",)),
        PaperSectionSpec("failure_scenarios", "Failure Scenarios", ("evaluation",)),
    ),
    "benchmark": (
        PaperSectionSpec("task_data_construction", "Task and Data Construction", ("inference",)),
        PaperSectionSpec("metrics_protocol", "Metrics and Protocol", ("evaluation",)),
        PaperSectionSpec("coverage_bias_leakage", "Coverage, Bias, and Leakage", ("evaluation",)),
        PaperSectionSpec("benchmark_reliability", "Benchmark Reliability", ("evaluation",)),
    ),
    "survey": (
        PaperSectionSpec("scope_inclusion", "Scope and Inclusion", ("inference",)),
        PaperSectionSpec("taxonomy", "Taxonomy", ("inference",)),
        PaperSectionSpec("trend_evidence", "Trend Evidence", ("evaluation",)),
        PaperSectionSpec("gaps_disagreement", "Gaps and Disagreement", ("evaluation",)),
        PaperSectionSpec("coverage_limits", "Coverage Limits", ("evaluation",)),
    ),
}

PAPER_SECTION_SPECS: dict[str, PaperSectionSpec] = {
    spec.section_id: spec
    for spec in (
        *COMMON_PAPER_SECTIONS,
        *(spec for paper_type in PAPER_TYPES for spec in TYPE_PAPER_SECTIONS[paper_type]),
    )
}


def required_paper_sections(paper_type: str) -> tuple[PaperSectionSpec, ...]:
    if paper_type not in PAPER_TYPES:
        return ()
    return (*COMMON_PAPER_SECTIONS, *TYPE_PAPER_SECTIONS[paper_type])


def paper_section_contract() -> dict[str, Any]:
    return {
        "common": [spec.contract_payload() for spec in COMMON_PAPER_SECTIONS],
        "by_paper_type": {
            paper_type: [spec.contract_payload() for spec in TYPE_PAPER_SECTIONS[paper_type]]
            for paper_type in PAPER_TYPES
        },
    }


def is_v2_paper_analysis(record: Mapping[str, Any] | Any) -> bool:
    """Recognize v2 from either persisted analysis or canonical claim markers."""

    if not isinstance(record, Mapping) or str(record.get("kind") or "") != "paper":
        return False
    payload = record.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    deep_read = payload.get("deep_read")
    if (
        isinstance(deep_read, Mapping)
        and str(deep_read.get("schema") or "") == PAPER_DEEP_READ_SCHEMA
    ):
        return True
    claims = payload.get("claims")
    return bool(
        isinstance(claims, (list, tuple))
        and any(
            isinstance(claim, Mapping)
            and str(claim.get("paper_note_schema") or "") == PAPER_NOTE_CLAIM_SCHEMA
            for claim in claims
        )
    )


def v2_paper_substance(record: Mapping[str, Any] | Any) -> dict[str, Any]:
    payload = record.get("payload") if isinstance(record, Mapping) else {}
    payload = payload if isinstance(payload, Mapping) else {}
    return {
        "deep_read": payload.get("deep_read") if isinstance(payload.get("deep_read"), Mapping) else {},
        "core_content": payload.get("core_content") if isinstance(payload.get("core_content"), Mapping) else {},
        "critique": payload.get("critique") if isinstance(payload.get("critique"), Mapping) else {},
    }


__all__ = [
    "COMMON_PAPER_SECTIONS",
    "PAPER_DEEP_READ_SCHEMA",
    "PAPER_NOTE_CLAIM_SCHEMA",
    "PAPER_NOTE_FILL_SCHEMA",
    "PAPER_SECTION_SPECS",
    "PAPER_TYPES",
    "PaperSectionSpec",
    "TYPE_PAPER_SECTIONS",
    "is_v2_paper_analysis",
    "paper_section_contract",
    "required_paper_sections",
    "v2_paper_substance",
]
