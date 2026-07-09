"""Claim -> evidence binding schema stub (SSOT Part 2, Principle 2).

This is an ADDITIVE, no-op landing pad for the Wave 2 evidence track. It changes
no existing behavior: it only exposes the locked `evidence_refs` schema (as
constants + a dataclass mirror) and a `verify_claim_evidence()` stub that
currently returns an empty list (no verification performed yet).

The canonical schema is documented verbatim in
`lib/research/SCHEMAS.md#evidence-claims` and locked in
`temp/SYSTEM_DESIGN_SSOT.md` Part 2 / Principle 2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Vocabulary (mirrors research-record information_types + confirmation values).
CLAIM_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}
# Judgement-class claims must carry evidence before they may be promoted to
# confirmed (SSOT Principle 2 / gate interlock). Enforcement lands in Wave 2.
JUDGEMENT_CLAIM_TYPES = {"inference", "evaluation"}
CLAIM_CONFIRMATION_VALUES = {
    "pending_user_confirmation",
    "confirmed",
    "rejected",
    "auto_confirmed",
}
# Two locator families (SSOT B4): PDF sources use page/section/para; HTML
# sources use section/anchor (no page numbers).
PDF_LOCATOR_KINDS = {"page", "section", "para"}
HTML_LOCATOR_KINDS = {"section", "anchor"}

# Locked canonical schema — kept byte-identical to
# SCHEMAS.md#evidence-claims / SSOT Part 2 Principle 2.
EVIDENCE_SCHEMA = """# 挂在每条 AI claim 上。落盘位置：note/screening 产物内的 claims 列表 + record 关联。
claim:
  id: claim-001
  text: ""                       # 断言本身
  claim_type: fact|inference|evaluation|user_opinion|unverified
  confidence: 0.0                # 可选
  confirmation_status: pending_user_confirmation|confirmed|rejected|auto_confirmed
  evidence_refs:
    - source_unit_id: p-...       # 证据所在 unit
      artifact: parse-cache.yaml  # unit 内相对路径，或 source(pdf/html)
      locator: "page=3"           # PDF: page=N|section|para ; HTML: section|anchor（B4）
      quote: ""                   # 短逐字片段（B3）——脚本校验它逐字存在于 artifact
      summary: ""                 # 可选转述
"""


@dataclass
class EvidenceRef:
    """A single evidence pointer attached to a claim (see EVIDENCE_SCHEMA)."""

    source_unit_id: str = ""
    artifact: str = ""
    locator: str = ""
    quote: str = ""
    summary: str = ""


@dataclass
class Claim:
    """An AI claim with its evidence bindings (see EVIDENCE_SCHEMA)."""

    id: str = ""
    text: str = ""
    claim_type: str = "unverified"
    confidence: float = 0.0
    confirmation_status: str = "pending_user_confirmation"
    evidence_refs: list[EvidenceRef] = field(default_factory=list)


def verify_claim_evidence(claim: dict[str, Any], unit_dir: str | Path) -> list[str]:
    """Return a list of evidence violations for `claim`.

    STUB (Wave 2 landing pad): performs no verification yet and always returns an
    empty list. The real implementation will, for each evidence_ref, load the
    referenced artifact under `unit_dir` and confirm the `quote` is a
    whitespace-normalized verbatim substring; missing quotes will be reported
    here. Returning [] keeps this a behavioral no-op until that lands.
    """
    return []


__all__ = [
    "CLAIM_TYPES",
    "JUDGEMENT_CLAIM_TYPES",
    "CLAIM_CONFIRMATION_VALUES",
    "PDF_LOCATOR_KINDS",
    "HTML_LOCATOR_KINDS",
    "EVIDENCE_SCHEMA",
    "EvidenceRef",
    "Claim",
    "verify_claim_evidence",
]
