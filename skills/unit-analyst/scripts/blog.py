#!/usr/bin/env python3
"""Blog analyzer adapter for the shared deterministic note lifecycle.

The runtime Agent authors every judgement.  This adapter supplies only blog
schema, artifact, rendering, and CLI values; the shared flow transports and
verifies evidence without trying to understand the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if (
    not (skills_dir / "metadata.yaml").is_file()
    or not (lib / "research" / "__init__.py").is_file()
    or not (lib / "research" / "bootstrap.py").is_file()
):
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.analyzer_note_flow import AnalyzerNoteFlow, AnalyzerNoteSpec
from research.git_ops import checkpoint_and_report


NOTE_ELEMENTS: tuple[str, ...] = (
    "positioning",
    "key_points",
    "credibility",
    "reusable_explanation",
)
PREFERENCE_SKILL = "blog-analyst"
PREFERENCE_OPERATION = "complete-note"
PREFERENCE_ORIENTATION_NAME = "blog-orientation.yaml"
ELEMENT_CLAIM_TYPE: dict[str, str] = {
    "positioning": "inference",
    "key_points": "inference",
    "credibility": "evaluation",
    "reusable_explanation": "inference",
}
ELEMENT_TARGET: dict[str, tuple[str, str, str]] = {
    "positioning": ("positioning", "main_value", "str"),
    "key_points": ("content", "key_points", "list"),
    "credibility": ("credibility", "best_use", "str"),
    "reusable_explanation": ("content", "intuitions", "list"),
}
ELEMENT_HEADING: dict[str, str] = {
    "positioning": "Positioning",
    "key_points": "Key Points",
    "credibility": "Credibility",
    "reusable_explanation": "Reusable Explanation",
}
EVIDENCE_REF_FORMAT: dict[str, str] = {
    "source_unit_id": "b-... (this blog unit id)",
    "artifact": "parse-cache.yaml (unit-relative artifact the quote lives in)",
    "locator": "section or section:<anchor> (HTML/Markdown; no page numbers)",
    "quote": (
        "short verbatim snippet — script checks it is a whitespace-normalized "
        "substring of the artifact"
    ),
    "summary": "optional one-line paraphrase",
}

SPEC = AnalyzerNoteSpec(
    kind="blog",
    command="complete-note",
    id_option="--blog-id",
    id_key="blog_id",
    preference_skill=PREFERENCE_SKILL,
    preference_operation=PREFERENCE_OPERATION,
    preference_orientation_name=PREFERENCE_ORIENTATION_NAME,
    note_elements=NOTE_ELEMENTS,
    element_claim_types=ELEMENT_CLAIM_TYPE,
    element_targets=ELEMENT_TARGET,
    element_headings=ELEMENT_HEADING,
    evidence_ref_format=EVIDENCE_REF_FORMAT,
    cache_id_keys=("blog_id", "unit_id", "paper_id"),
    fill_name="blog-fill.yaml",
    note_name="blog-note.md",
    claims_name="blog-claims.yaml",
    state_field="full_note_status",
    source_identity="blog-source-artifacts",
    parser_description=(
        "Prepare fillable blog structures + verify agent-filled understanding."
    ),
    scaffold_description=(
        "Agent fills all four required_elements with its own understanding, each "
        "backed by >=1 verbatim evidence_ref from the parse-cache. Then run "
        "`complete-note --phase verify` to validate + verbatim-check evidence + "
        "write blog-note.md + payload content. Empty or unevidenced elements are "
        "rejected; the script validates runtime-Agent content and never authors it."
    ),
    note_intro=(
        "> 本笔记由 runtime agent 依据 parse-cache 填写；脚本已逐字校验每条 evidence。",
        "> 博客来源为网页内容（HTML section/anchor 定位，无页码）。",
    ),
    prepare_guidance=(
        "下一步：agent 读 parse-cache 填四要素"
        "(positioning/key_points/credibility/reusable_explanation)"
        "带证据，再跑 `blog.py complete-note --phase verify --blog-id <id>`。"
    ),
    preference_label="blog note",
    cache_identity_label="blog",
    prepare_history_action="blog-note-scaffolded",
    prepare_history_summary=(
        "Prepared 4-element fillable blog note skeleton (script authored nothing)."
    ),
    verify_history_action="blog-note-verified",
    verify_history_summary=(
        "Verified + persisted agent 4-element blog note (evidence-grounded)."
    ),
    scaffold_checkpoint_message="milestone: scaffold blog note {id}",
    verify_checkpoint_message="milestone: blog note {id}",
    confirm_checkpoint_message="milestone: confirm blog {id}",
)


def _checkpoint_proxy(*args, **kwargs):
    """Keep historical tests' monkeypatch point while delegating the lifecycle."""
    return checkpoint_and_report(*args, **kwargs)


FLOW = AnalyzerNoteFlow(
    SPEC,
    script_path=SCRIPT_PATH,
    default_project_root=PROJECT_ROOT,
    checkpoint=_checkpoint_proxy,
)

# Compatibility call points used by installed callers and characterization tests.
add_confirmation_arguments = FLOW.add_confirmation_arguments
_index_targets = FLOW.index_targets
_cache_path = FLOW.cache_path
_load_cache_chunks = FLOW.load_cache_chunks
_cache_unit_id = FLOW.cache_unit_id
_normalized_cache_payload = FLOW.normalized_cache_payload
_chunk_locator = FLOW.chunk_locator
_evidence_digest = FLOW.evidence_digest
build_note_scaffold = FLOW.build_note_scaffold
blog_preference_orientation = FLOW.preference_orientation
blog_preference_context = FLOW.preference_context
resolve_blog_preferences = FLOW.resolve_preferences
_persist_preference_binding = FLOW.persist_preference_binding
_elements_by_name = FLOW.elements_by_name
_claim_from_element = FLOW.claim_from_element
verify_note_fill = FLOW.verify_note_fill
_apply_note_fill_to_payload = FLOW.apply_note_fill_to_payload
render_note_md = FLOW.render_note_md
_finalize_post_actions = FLOW.finalize_post_actions
_resolve_fill_input = FLOW.resolve_fill_input
_unit_owned_fill_path = FLOW.unit_owned_fill_path
next_for_agent_note = FLOW.next_for_agent_note
build_parser = FLOW.build_parser
_run_complete_note = FLOW.run_note
_run_confirm = FLOW.run_confirm
main = FLOW.main


if __name__ == "__main__":
    raise SystemExit(main())
