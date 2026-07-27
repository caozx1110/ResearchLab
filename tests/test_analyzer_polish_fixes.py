"""Post-acceptance analyzer polish fixes: F6 / F9 / F8 + the F4 regression guard.

These lock in three confirmed post-acceptance-test fixes and prove the (correct)
verify-reject behavior was NOT regressed:

  * F6 — blog complete-note verify persists a git checkpoint (paper/repo already did;
    blog left its note.md + payload uncommitted). A deferred call must NOT commit.
  * F9 — a blog parse-cache carrying the legacy ``paper_id`` header key (stamped by the
    shared dual-source intake writer) is corrected on consume to blog semantics
    (``blog_id``), value + chunks preserved, idempotent, read-compatible with both keys.
  * F8 — a PDF-extracted paper title with embedded newlines renders the FULL title on a
    single H1 line in note.md, never a mid-sentence hard cut / orphaned lines.
  * F4 regression guard — blog AND repo verify STILL exit 1 and reject a fabricated
    quote when a REAL filled quote (not the scaffold example) is corrupted.

All fixtures are synthetic + offline so verification is deterministic.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, kb_git_log, record_path, write_record
from research.records import kind_payload_skeleton


def _project_root() -> Path:
    return REPO_ROOT


def _load_module(name: str, script_rel: str):
    script = _project_root() / script_rel
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_blog():
    return _load_module("blog_polish_under_test", ".agents/skills/blog-analyst/scripts/blog.py")


def _load_paper():
    return _load_module("paper_polish_under_test", ".agents/skills/paper-analyst/scripts/paper.py")


def _load_repo():
    return _load_module("repo_polish_under_test", ".agents/skills/repo-analyst/scripts/repo.py")


# --------------------------------------------------------------------------- #
# Blog fixtures (verbatim text so evidence verification is deterministic).      #
# --------------------------------------------------------------------------- #
SECTION_INTRO = (
    "Transformers use self-attention to relate all positions in a sequence simultaneously. "
    "This allows the model to capture long-range dependencies without sequential bottlenecks."
)
SECTION_RESULTS = (
    "In practice this approach scales better than RNNs on long sequences. "
    "The authors report a 12% improvement on the translation benchmark. "
    "One limitation is that the quadratic memory cost restricts very long contexts."
)


def _blog_record(blog_id: str) -> dict:
    return {
        "id": blog_id,
        "kind": "blog",
        "title": "Synthetic Transformer Blog",
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation", "fact", "inference", "unverified"],
        "topics": ["transformers"],
        "tags": ["attention"],
        "source": {"original_uri": "https://example.com/blog", "file_hash": ""},
        "payload": kind_payload_skeleton("blog", "Synthetic Transformer Blog"),
    }


def _write_blog_cache_with_legacy_header(unit_dir: Path, blog_id: str) -> Path:
    """A blog parse-cache stamped with the legacy ``paper_id`` header (the F9 bug)."""
    cache = unit_dir / "parse-cache.yaml"
    write_yaml_if_changed(
        cache,
        {
            "paper_id": blog_id,  # wrong semantics for a blog unit — sources.write_parse_cache
            "source_type": "html",
            "locator_kind": "section",
            "chunks": [
                {"label": "section:intro", "text": SECTION_INTRO, "page": None, "anchor": "intro"},
                {"label": "section:results", "text": SECTION_RESULTS, "page": None, "anchor": "results"},
            ],
        },
    )
    return cache


def _legit_blog_fill(blog_id: str = "b-x") -> dict:
    return {
        "elements": [
            {
                "element": "positioning",
                "claim_type": "inference",
                "content": "Introductory explanation of the Transformer architecture.",
                "evidence_refs": [
                    {"source_unit_id": blog_id, "artifact": "parse-cache.yaml", "locator": "section:intro",
                     "quote": "self-attention to relate all positions in a sequence simultaneously", "summary": "core"}
                ],
            },
            {
                "element": "key_points",
                "claim_type": "inference",
                "content": "Self-attention enables parallel long-range dependency modelling.",
                "evidence_refs": [
                    {"source_unit_id": blog_id, "artifact": "parse-cache.yaml", "locator": "section:results",
                     "quote": "scales better than RNNs on long sequences", "summary": "advantage"}
                ],
            },
            {
                "element": "credibility",
                "claim_type": "evaluation",
                "content": "Benchmark result is fact; architectural claims are author opinion.",
                "evidence_refs": [
                    {"source_unit_id": blog_id, "artifact": "parse-cache.yaml", "locator": "section:results",
                     "quote": "12% improvement on the translation benchmark", "summary": "metric"}
                ],
            },
            {
                "element": "reusable_explanation",
                "claim_type": "inference",
                "content": "Every token attends to every other — quadratic cost, no sequential bottleneck.",
                "evidence_refs": [
                    {"source_unit_id": blog_id, "artifact": "parse-cache.yaml", "locator": "section:intro",
                     "quote": "capture long-range dependencies without sequential bottlenecks", "summary": "intuition"}
                ],
            },
        ]
    }


def _run_blog_cli(blog, monkeypatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["blog.py", "--root", str(root), *argv])
    return blog.main()


# --------------------------------------------------------------------------- #
# F6 — blog verify persists a git checkpoint.                                   #
# --------------------------------------------------------------------------- #
def test_f6_blog_verify_creates_git_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _load_blog()
    ensure_workspace(tmp_path)
    blog_id = "b-f6-000001"
    record = _blog_record(blog_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "blog", blog_id).parent
    _write_blog_cache_with_legacy_header(unit_dir, blog_id)

    assert _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                         "--blog-id", blog_id) == 0
    write_yaml_if_changed(unit_dir / "blog-fill.yaml", _legit_blog_fill(blog_id))
    assert _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                         "--blog-id", blog_id) == 0

    # The verify artifacts (blog-note.md + record) are committed to the kb git repo.
    assert (unit_dir / "blog-note.md").exists()
    log = kb_git_log(tmp_path, limit=20)
    assert log.get("repo_exists") is True
    assert f"milestone: blog note {blog_id}" in log["text"], log["text"]
    committed = subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "show", "--format=", "--name-only", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert f"units/blogs/{blog_id}/blog-fill.yaml" in committed
    assert "blog-fill.yaml" not in subprocess.run(
        ["git", "-C", str(tmp_path / "kb"), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_f6_blog_verify_defer_does_not_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--defer-post-actions hands the checkpoint to an outer driver (paper/repo convention)."""
    blog = _load_blog()
    ensure_workspace(tmp_path)
    blog_id = "b-f6-000002"
    record = _blog_record(blog_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "blog", blog_id).parent
    _write_blog_cache_with_legacy_header(unit_dir, blog_id)

    _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                  "--blog-id", blog_id, "--defer-post-actions")
    write_yaml_if_changed(unit_dir / "blog-fill.yaml", _legit_blog_fill(blog_id))
    _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                  "--blog-id", blog_id, "--defer-post-actions")

    log = kb_git_log(tmp_path, limit=20)
    # No blog-note checkpoint was made (deferred): either no repo/commits, or no such line.
    assert f"milestone: blog note {blog_id}" not in log.get("text", "")


# --------------------------------------------------------------------------- #
# F9 — blog parse-cache legacy header is read-compatible and byte-immutable.   #
# --------------------------------------------------------------------------- #
def test_f9_blog_cache_header_is_read_compatible_without_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blog = _load_blog()
    ensure_workspace(tmp_path)
    blog_id = "b-f9-000001"
    record = _blog_record(blog_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "blog", blog_id).parent
    cache = _write_blog_cache_with_legacy_header(unit_dir, blog_id)

    before = cache.read_bytes()
    assert "paper_id" in load_yaml(cache)  # precondition: the legacy header is present

    _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                  "--blog-id", blog_id, "--defer-post-actions")

    assert cache.read_bytes() == before
    data = load_yaml(cache)
    assert data.get("paper_id") == blog_id
    assert "blog_id" not in data
    # A second consume is byte-identical too.
    _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                  "--blog-id", blog_id, "--defer-post-actions")
    assert cache.read_bytes() == before


def test_f9_load_cache_chunks_read_compatible_with_both_keys(tmp_path: Path) -> None:
    blog = _load_blog()
    # Read-compat: chunks load regardless of which header id key the cache carries.
    for header in ("paper_id", "blog_id", "unit_id"):
        unit = tmp_path / header
        unit.mkdir()
        write_yaml_if_changed(unit / "parse-cache.yaml", {
            header: "b-x", "locator_kind": "section",
            "chunks": [{"label": "section:intro", "text": SECTION_INTRO, "anchor": "intro"}],
        })
        chunks, locator_kind = blog._load_cache_chunks(unit)
        assert len(chunks) == 1 and locator_kind == "section"
    # _cache_unit_id accepts blog/unit/legacy keys, preferring blog semantics.
    assert blog._cache_unit_id({"paper_id": "b-legacy"}) == "b-legacy"
    assert blog._cache_unit_id({"blog_id": "b-new"}) == "b-new"
    assert blog._cache_unit_id({"unit_id": "b-generic"}) == "b-generic"
    assert blog._cache_unit_id({"blog_id": "b-win", "paper_id": "b-lose"}) == "b-win"


# --------------------------------------------------------------------------- #
# F8 — paper note.md renders the FULL title on a single H1 line (no cut).       #
# --------------------------------------------------------------------------- #
def test_f8_paper_note_title_is_full_single_line() -> None:
    paper = _load_paper()
    # A PDF-extracted cover title spanning three physical lines (the observed bug case).
    record = {
        "id": "p-f8-000001",
        "title": "Finer Behavioral Foundation Models via\n\nAuto-Regressive Features and Advantage\n\nWeighting",
        "payload": {},
    }
    md = paper.render_note_md(record, [])
    lines = md.splitlines()

    expected = "# Finer Behavioral Foundation Models via Auto-Regressive Features and Advantage Weighting"
    assert lines[0] == expected                      # full title on the H1 line
    assert lines[1] == ""                             # nothing orphaned directly under H1
    # The old mid-sentence cut must NOT appear as a standalone heading.
    assert "# Finer Behavioral Foundation Models via\n" not in md
    # Every title word survives (no hard character truncation).
    for word in ("Auto-Regressive", "Advantage", "Weighting"):
        assert word in lines[0]


def test_f8_single_line_title_unchanged() -> None:
    paper = _load_paper()
    record = {"id": "p-x", "title": "A Perfectly Normal Single-Line Title", "payload": {}}
    md = paper.render_note_md(record, [])
    assert md.splitlines()[0] == "# A Perfectly Normal Single-Line Title"


# --------------------------------------------------------------------------- #
# F4 regression guard — blog AND repo verify STILL exit 1 on a fabricated quote #
# when a REAL filled quote (not the scaffold example) is corrupted.             #
# --------------------------------------------------------------------------- #
def test_f4_guard_blog_verify_still_rejects_fabricated_real_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blog = _load_blog()
    ensure_workspace(tmp_path)
    blog_id = "b-reject-000001"
    record = _blog_record(blog_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "blog", blog_id).parent
    _write_blog_cache_with_legacy_header(unit_dir, blog_id)

    fill = _legit_blog_fill(blog_id)
    # Corrupt a REAL filled quote (not the scaffold EXAMPLE) — must be rejected.
    fill["elements"][1]["evidence_refs"][0]["quote"] = "a fabricated claim never in the source"
    write_yaml_if_changed(unit_dir / "blog-fill.yaml", fill)

    with pytest.raises(SystemExit) as exc:
        _run_blog_cli(blog, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                      "--blog-id", blog_id)
    assert exc.value.code == 1  # non-zero reject exit preserved

    # Machinery-level: the offending element is named, untouched ones are not blamed.
    violations, _claims = blog.verify_note_fill(fill, unit_dir)
    assert any("element 'key_points'" in v and "not verbatim" in v for v in violations), violations
    assert not any("element 'positioning'" in v for v in violations)


# Repo mini-repo fixture (verbatim file lines) for the repo verify-reject guard.
_README = (
    "# MiniVLA\n"
    "MiniVLA is a compact vision-language-action baseline for robot manipulation.\n"
    "Training uses behavior cloning on teleop demonstrations.\n"
)
_TRAIN_PY = (
    "def main():\n"
    "    # training entrypoint for the behavior cloning loop\n"
    "    model = build_policy()\n"
)
_POLICY_PY = (
    "class Policy:\n"
    "    # reusable policy head module\n"
    "    def act(self, obs):\n"
    "        return self.head(obs)\n"
)


def _make_mini_repo(base: Path) -> Path:
    repo = base / "mini-repo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(_README, encoding="utf-8")
    (repo / "train.py").write_text(_TRAIN_PY, encoding="utf-8")
    (repo / "policy.py").write_text(_POLICY_PY, encoding="utf-8")
    return repo


def _legit_capability_fill(repo_id: str) -> dict:
    return {
        "elements": [
            {
                "element": "capability",
                "claim_type": "evaluation",
                "content": "A compact VLA baseline for manipulation.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "README.md", "locator": "line=2",
                     "quote": "compact vision-language-action baseline for robot manipulation", "summary": "scope"}
                ],
            },
            {
                "element": "reuse_points",
                "claim_type": "evaluation",
                "content": "The policy head module is directly reusable.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "policy.py", "locator": "line=2",
                     "quote": "reusable policy head module", "summary": "reusable unit"}
                ],
            },
            {
                "element": "entry_map",
                "claim_type": "inference",
                "content": "Training entry is train.py:main.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "train.py", "locator": "line=2",
                     "quote": "training entrypoint for the behavior cloning loop", "summary": "train entry"}
                ],
            },
        ]
    }


def test_f4_guard_repo_verify_still_rejects_fabricated_real_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _load_repo()
    ensure_workspace(tmp_path)
    mini = _make_mini_repo(tmp_path)
    repo_id = "r-reject-000001"
    record = {
        "id": repo_id, "kind": "repo", "title": "MiniVLA", "status": "screened",
        "maturity": "lightweight", "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact", "inference", "evaluation", "unverified"],
        "topics": ["vla"], "tags": ["manipulation"],
        "source": {"original_uri": str(mini), "file_hash": ""},
        "payload": kind_payload_skeleton("repo", "MiniVLA"),
    }
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "repo", repo_id).parent

    fill = _legit_capability_fill(repo_id)
    # Corrupt a REAL filled quote (not the scaffold example) — must be rejected.
    fill["elements"][0]["evidence_refs"][0]["quote"] = "a diffusion world model we never wrote"
    write_yaml_if_changed(unit_dir / "capability-fill.yaml", fill)

    with pytest.raises(SystemExit) as exc:
        monkeypatch.setattr(sys, "argv", ["repo.py", "--root", str(tmp_path), "map-capability",
                                          "--phase", "verify", "--repo-id", repo_id, "--defer-post-actions"])
        repo.main()
    assert exc.value.code == 1  # non-zero reject exit preserved

    violations, _claims = repo.verify_capability_fill(fill, mini)
    assert any("element 'capability'" in v and "not verbatim" in v for v in violations), violations
    assert not any("element 'reuse_points'" in v for v in violations)
