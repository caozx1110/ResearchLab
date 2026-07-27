"""Blog-analyst machinery tests (SSOT Principle 1 / §3.4).

We cannot headless-test "an agent filled *good* understanding" (that needs a real
agent). So these test the MACHINERY the script owns:

  * complete-note --phase prepare emits the 4-element fillable structure with NO
    Python judgement in the element content fields;
  * feeding synthetic filled content with legit verbatim evidence -> validates,
    clears the substance gate, and persists (content non-empty, blog-note.md written);
  * feeding fabricated evidence -> rejected, with the offending element named;
  * empty fill -> substance gate blocks confirm.

The evidence quotes are copied verbatim from a synthetic parse-cache so verification
is deterministic and offline. Blog parse-caches use HTML section/anchor locators.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import confirm_unit, has_substantive_content
from research.core import ensure_workspace, record_path, write_record
from research.evidence import attach_claims, build_verification_receipt
from research.records import kind_payload_skeleton


def _project_root() -> Path:
    return REPO_ROOT


def _load_blog_module():
    script = _project_root() / ".agents" / "skills" / "blog-analyst" / "scripts" / "blog.py"
    spec = importlib.util.spec_from_file_location("blog_analyst_script_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Synthetic parse-cache: known verbatim text in two HTML sections.
SECTION_INTRO = (
    "Transformers use self-attention to relate all positions in a sequence simultaneously. "
    "This allows the model to capture long-range dependencies without sequential bottlenecks."
)
SECTION_RESULTS = (
    "In practice this approach scales better than RNNs on long sequences. "
    "The authors report a 12% improvement on the translation benchmark. "
    "One limitation is that the quadratic memory cost restricts very long contexts."
)

JUDGEMENT_INFO_TYPES = ["evaluation", "fact", "inference", "unverified"]


def _write_parse_cache(unit_dir: Path, blog_id: str) -> Path:
    cache = unit_dir / "parse-cache.yaml"
    write_yaml_if_changed(
        cache,
        {
            "blog_id": blog_id,
            "source_type": "html",
            "locator_kind": "section",
            "chunks": [
                {
                    "label": "section:intro",
                    "text": SECTION_INTRO,
                    "page": None,
                    "anchor": "intro",
                    "locator_kind": "section",
                },
                {
                    "label": "section:results",
                    "text": SECTION_RESULTS,
                    "page": None,
                    "anchor": "results",
                    "locator_kind": "section",
                },
            ],
        },
    )
    return cache


def _blog_record(blog_id: str, *, info_types=None, content=None) -> dict:
    record = {
        "id": blog_id,
        "kind": "blog",
        "title": "Synthetic Transformer Blog",
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": list(info_types or JUDGEMENT_INFO_TYPES),
        "topics": ["transformers"],
        "tags": ["attention", "nlp"],
        "source": {"original_uri": "https://example.com/blog", "file_hash": ""},
        "payload": kind_payload_skeleton("blog", "Synthetic Transformer Blog"),
    }
    if content:
        record["payload"]["content"].update(content)
    return record


def _legit_note_fill() -> dict:
    """A synthetic 4-element fill whose every quote is verbatim from the cache."""
    return {
        "elements": [
            {
                "element": "positioning",
                "claim_type": "inference",
                "content": "Introductory explanation of the Transformer architecture for practitioners.",
                "evidence_refs": [
                    {
                        "source_unit_id": "b-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "section:intro",
                        "quote": "self-attention to relate all positions in a sequence simultaneously",
                        "summary": "defines the core mechanism",
                    }
                ],
            },
            {
                "element": "key_points",
                "claim_type": "inference",
                "content": "Self-attention enables parallel long-range dependency modelling; scales better than RNNs.",
                "evidence_refs": [
                    {
                        "source_unit_id": "b-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "section:results",
                        "quote": "scales better than RNNs on long sequences",
                        "summary": "key advantage",
                    }
                ],
            },
            {
                "element": "credibility",
                "claim_type": "evaluation",
                "content": "Benchmark result is fact (12% improvement cited); architectural claims are author opinion.",
                "evidence_refs": [
                    {
                        "source_unit_id": "b-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "section:results",
                        "quote": "12% improvement on the translation benchmark",
                        "summary": "verifiable metric",
                    }
                ],
            },
            {
                "element": "reusable_explanation",
                "claim_type": "inference",
                "content": "Self-attention lets every token attend to every other — quadratic cost but no sequential bottleneck.",
                "evidence_refs": [
                    {
                        "source_unit_id": "b-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "section:intro",
                        "quote": "capture long-range dependencies without sequential bottlenecks",
                        "summary": "intuition for reuse",
                    }
                ],
            },
        ]
    }


# --------------------------------------------------------------------------- #
# 1. complete-note --phase prepare produces the 4-element fillable skeleton.   #
# --------------------------------------------------------------------------- #
def test_note_scaffold_has_four_blank_elements(tmp_path: Path) -> None:
    blog = _load_blog_module()
    record = _blog_record("b-note-000001")
    chunks = [
        {"label": "section:intro", "text": SECTION_INTRO, "page": None, "anchor": "intro"},
    ]

    scaffold = blog.build_note_scaffold(record, chunks, digest_chunks=8, digest_chars=800)

    names = [el["element"] for el in scaffold["elements"]]
    assert names == ["positioning", "key_points", "credibility", "reusable_explanation"]
    for el in scaffold["elements"]:
        assert el["content"] == ""         # script authors nothing
        assert el["evidence_refs"] == []   # agent must attach evidence
    assert scaffold["fill_contract"]["required_elements"] == names
    assert "evidence_ref_format" in scaffold["fill_contract"]
    # HTML locator shape documented
    assert "section" in scaffold["fill_contract"]["evidence_ref_format"]["locator"]


def test_note_scaffold_has_no_python_judgement() -> None:
    """Anti-pattern guard: no Python-derived positioning or value assignment."""
    src = (
        _project_root() / ".agents" / "skills" / "blog-analyst" / "scripts" / "blog.py"
    ).read_text("utf-8")
    # No literal placeholder templates
    assert "待确认" not in src
    # No keyword-count -> grade
    import re
    assert not re.search(r"len\([^)]*hits[^)]*\)", src)
    # No Python that assigns positioning categories
    assert not re.search(r'positioning.*=.*(入门|原理|工程|教程)', src)
    assert not re.search(r'main_value.*=.*"[^"]{5,}"', src)


def test_evidence_digest_has_section_locators(tmp_path: Path) -> None:
    blog = _load_blog_module()
    record = _blog_record("b-digest-000001")
    chunks = [
        {"label": "section:intro", "text": SECTION_INTRO, "page": None, "anchor": "intro"},
        {"label": "section:results", "text": SECTION_RESULTS, "page": None, "anchor": "results"},
    ]
    scaffold = blog.build_note_scaffold(record, chunks, digest_chunks=6, digest_chars=400)

    digest = scaffold["evidence_digest"]
    assert len(digest) == 2
    # All locators are section-based (no page= for blog)
    for entry in digest:
        assert entry["locator"].startswith("section")
        assert entry["artifact"] == "parse-cache.yaml"
        assert "page=" not in entry["locator"]


# --------------------------------------------------------------------------- #
# 2. Legit filled content + verbatim evidence -> validates + clears substance   #
# --------------------------------------------------------------------------- #
def test_note_fill_legit_evidence_validates_and_clears_substance_gate(tmp_path: Path) -> None:
    blog = _load_blog_module()
    record = _blog_record("b-fill-legit-1")
    unit_dir = record_path(tmp_path, "blog", record["id"]).parent
    unit_dir.mkdir(parents=True)
    _write_parse_cache(unit_dir, "b-x")

    violations, claims = blog.verify_note_fill(_legit_note_fill(), unit_dir)
    assert violations == [], violations
    assert len(claims) == 4
    for claim in claims:
        for ref in claim["evidence_refs"]:
            ref["source_unit_id"] = record["id"]

    assert has_substantive_content(record, "blog") is False  # empty before fill
    blog._apply_note_fill_to_payload(record, claims)
    attach_claims(record["payload"], claims)
    build_verification_receipt(record, unit_dir)

    # key_points and reusable_explanation land in payload.content (substance gate)
    content = record["payload"]["content"]
    assert content["key_points"]
    assert content["intuitions"]
    # positioning lands in payload.positioning
    assert record["payload"]["positioning"]["main_value"]
    # credibility lands in payload.credibility
    assert record["payload"]["credibility"]["best_use"]
    # Substance gate now passes
    assert has_substantive_content(record, "blog") is True

    # blog-note.md renders every element + evidence citations
    note_md = blog.render_note_md(record, claims)
    assert "## Key Points" in note_md
    assert "## Credibility" in note_md
    assert "## Positioning" in note_md
    assert "## Reusable Explanation" in note_md
    assert "12% improvement on the translation benchmark" in note_md

    # Substance gate passes: a real human can confirm the judgement-track blog
    confirmed = confirm_unit(
        record, "blog", confirmed_by="czx", evidence=["kb/programs/p/decision-log.md"],
        user_authorization="I confirm this blog analysis.", authorization_source="user_message",
        project_root=tmp_path,
    )
    assert confirmed["confirmation_status"] == "confirmed"


# --------------------------------------------------------------------------- #
# 3. Fabricated evidence -> rejected, offending element named.                 #
# --------------------------------------------------------------------------- #
def test_note_fill_fabricated_evidence_is_rejected_by_element(tmp_path: Path) -> None:
    blog = _load_blog_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "b-x")

    fill = _legit_note_fill()
    # Corrupt the key_points element's quote — not verbatim in the artifact
    fill["elements"][1]["evidence_refs"][0]["quote"] = "a diffusion model we never mentioned"

    violations, _claims = blog.verify_note_fill(fill, unit_dir)
    assert violations
    assert any("element 'key_points'" in v and "not verbatim" in v for v in violations), violations
    # Untouched elements are not falsely blamed
    assert not any("element 'positioning'" in v for v in violations)
    assert not any("element 'credibility'" in v for v in violations)


# --------------------------------------------------------------------------- #
# 4. Empty fill -> substance gate blocks confirm.                              #
# --------------------------------------------------------------------------- #
def test_empty_note_fill_is_rejected_and_hollow_confirm_is_blocked(tmp_path: Path) -> None:
    blog = _load_blog_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "b-x")

    # Scaffold-shaped fill with blank content (agent produced nothing)
    empty_fill = blog.build_note_scaffold(
        _blog_record("b-x"), [], digest_chunks=1, digest_chars=10
    )
    violations, _claims = blog.verify_note_fill(empty_fill, unit_dir)
    assert violations
    assert any("empty content" in v for v in violations)
    assert any("no evidence_refs" in v for v in violations)

    # Confirmation substance gate independently refuses a hollow blog
    hollow = _blog_record("b-hollow-000001")  # content untouched == empty
    assert has_substantive_content(hollow, "blog") is False
    with pytest.raises(SystemExit, match="hollow"):
        confirm_unit(hollow, "blog", confirmed_by="czx", evidence=["kb/programs/p/log.md"])


# --------------------------------------------------------------------------- #
# 5. End-to-end through the real CLI: prepare -> fill -> verify -> confirm.    #
# --------------------------------------------------------------------------- #
def _run_cli(blog, monkeypatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["blog.py", "--root", str(root), *argv])
    return blog.main()


def test_cli_end_to_end_prepare_fill_verify_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _load_blog_module()
    ensure_workspace(tmp_path)
    blog_id = "b-e2e-000001"
    record = _blog_record(blog_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "blog", blog_id).parent
    _write_parse_cache(unit_dir, blog_id)

    # prepare -> fillable blog-fill.yaml, no grading, record stays hollow
    assert _run_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                    "--blog-id", blog_id) == 0
    fill_path = unit_dir / "blog-fill.yaml"
    scaffold = load_yaml(fill_path)
    assert [el["element"] for el in scaffold["elements"]] == list(blog.NOTE_ELEMENTS)
    for el in scaffold["elements"]:
        assert el["content"] == ""
    reloaded = load_yaml(record_path(tmp_path, "blog", blog_id))
    assert has_substantive_content(reloaded, "blog") is False  # scaffold is not content

    # Agent fills the scaffold; verify persists blog-note.md + content fields
    write_yaml_if_changed(fill_path, _legit_note_fill())
    assert _run_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                    "--blog-id", blog_id) == 0
    assert (unit_dir / "blog-note.md").exists()
    filled = load_yaml(record_path(tmp_path, "blog", blog_id))
    assert has_substantive_content(filled, "blog") is True
    assert filled["payload"]["claims"] == load_yaml(unit_dir / "blog-claims.yaml")["claims"]
    assert filled["payload"]["verification"]["artifacts"]
    assert len(filled["payload"]["verification"]["claims_digest"]) == 64

    # Fabricated fill through the CLI is rejected (non-zero exit)
    bad = _legit_note_fill()
    bad["elements"][0]["evidence_refs"][0]["quote"] = "fabricated claim not in source"
    write_yaml_if_changed(fill_path, bad)
    with pytest.raises(SystemExit):
        _run_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                 "--blog-id", blog_id)
