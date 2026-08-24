from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import yaml

from repo_paths import REPO_ROOT


PROPOSAL_ROOT = REPO_ROOT / "docs" / "proposals" / "markdown-first"
SAMPLE_ROOT = PROPOSAL_ROOT / "examples" / "vault"
ADR_PATH = REPO_ROOT / "docs" / "decisions" / "0005-markdown-first-material-and-semantic-ownership.md"
MARKDOWN_LINK = re.compile(r"!?(?:\[[^\]]*\])\(([^)]+)\)")
WIKILINK = re.compile(r"!??\[\[([^\]]+)\]\]")
BLOCK_ID = re.compile(r"^\^([A-Za-z0-9-]+)\s*$", re.MULTILINE)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    assert end >= 0, path
    payload = yaml.safe_load(text[4:end])
    assert isinstance(payload, dict), path
    return payload


def _iter_sample_markdown() -> list[Path]:
    return sorted(SAMPLE_ROOT.rglob("*.md"))


def test_proposal_and_adr_are_explicitly_unaccepted_candidates() -> None:
    assert _frontmatter(PROPOSAL_ROOT / "README.md")["status"] == "proposal"
    assert _frontmatter(PROPOSAL_ROOT / "NON_ARXIV_INGESTION.md")["status"] == "proposal"
    adr = ADR_PATH.read_text(encoding="utf-8")
    assert "- Status: Proposed" in adr
    assert "#44" in adr and "#43" in adr
    assert "只有合入 default branch 后" in adr


def test_sample_has_one_home_and_static_fallbacks() -> None:
    assert (SAMPLE_ROOT / "Home.md").is_file()
    assert (SAMPLE_ROOT / "Reviews" / "README.md").is_file()
    assert not (SAMPLE_ROOT / ".obsidian").exists()
    assert (SAMPLE_ROOT / "Views" / "Materials.md").is_file()
    assert (SAMPLE_ROOT / "Views" / "Review.md").is_file()
    assert (SAMPLE_ROOT / "Views" / "Recovery.md").is_file()
    assert (SAMPLE_ROOT / "Views" / "Materials.base").is_file()
    assert (SAMPLE_ROOT / "Views" / "Review.base").is_file()


def test_source_indexes_expose_kind_specific_reader_entries() -> None:
    expected = {
        "web-article": ("document.md", "source.html", "evidence-ready"),
        "repo-example": ("snapshot/README.md", "snapshot/src/train.py", "analysis-ready"),
        "dataset-example": ("card.md", "schema.yaml", "reader-ready"),
        "artifact-example": ("preview.md", "source.json", "reader-ready"),
    }
    for name, (reader, raw, readiness) in expected.items():
        root = SAMPLE_ROOT / "Sources" / name
        index = root / "index.md"
        props = _frontmatter(index)
        assert props["readiness"] == readiness
        for property_name in (
            "material_id",
            "object_type",
            "source_type",
            "source_status",
            "reader_path",
            "projects",
            "updated",
            "needs_review",
        ):
            assert property_name in props, (name, property_name)
        assert (root / reader).is_file(), (name, reader)
        assert (root / raw).is_file(), (name, raw)
        text = index.read_text(encoding="utf-8")
        assert "入口" in text


def test_sample_standard_markdown_links_resolve() -> None:
    missing: list[str] = []
    for path in _iter_sample_markdown() + [ADR_PATH]:
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {target}")
    assert missing == []


def test_sample_wikilinks_have_readable_targets() -> None:
    missing: list[str] = []
    for path in _iter_sample_markdown():
        text = path.read_text(encoding="utf-8")
        for raw in WIKILINK.findall(text):
            target = raw.split("|", 1)[0].split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://")):
                continue
            base = SAMPLE_ROOT if target.startswith(("Sources/", "Notes/", "Projects/", "Views/", "Inbox/")) else path.parent
            candidate = base / (target if Path(target).suffix else f"{target}.md")
            if not candidate.exists():
                # A wikilink may intentionally point at a non-Markdown source file.
                candidate = base / target
            if not candidate.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {raw}")
    assert missing == []


def test_sample_bases_are_valid_yaml_and_reference_defined_properties() -> None:
    for path in sorted((SAMPLE_ROOT / "Views").glob("*.base")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), path
        assert isinstance(payload.get("views"), list) and payload["views"], path
        properties = payload.get("properties", {})
        assert isinstance(properties, dict), path
        for view in payload["views"]:
            assert view.get("type") in {"table", "cards", "list", "map"}, path
            for item in view.get("order", []):
                if isinstance(item, str) and not item.startswith(("file.", "formula.")):
                    assert item in properties, (path, item)


def test_base_views_use_only_the_candidate_reader_property_vocabulary() -> None:
    candidate = {
        "material_id",
        "object_type",
        "title",
        "source_type",
        "source_status",
        "readiness",
        "reader_path",
        "projects",
        "tags",
        "updated",
        "needs_review",
        "status",
        "confirmation_status",
    }
    for path in sorted((SAMPLE_ROOT / "Views").glob("*.base")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        for property_name in payload.get("properties", {}):
            assert property_name in candidate, (path, property_name)
        for view in payload["views"]:
            for item in view.get("order", []):
                if isinstance(item, str) and not item.startswith(("file.", "formula.")):
                    assert item in candidate, (path, item)


def test_sample_block_ids_are_unique_and_source_layers_are_not_claimed_as_notes() -> None:
    seen: dict[str, Path] = {}
    for path in _iter_sample_markdown():
        for block_id in BLOCK_ID.findall(path.read_text(encoding="utf-8")):
            assert block_id not in seen, (block_id, seen[block_id], path)
            seen[block_id] = path
    for path in (SAMPLE_ROOT / "Sources").rglob("*.md"):
        if path.name == "index.md" or path.name == "document.md":
            text = path.read_text(encoding="utf-8")
            assert "file://" not in text
    adr = ADR_PATH.read_text(encoding="utf-8")
    assert "原始 artifact/parse-cache/locator 是 evidence authority" in adr
    assert "不承载 evidence、正文或授权" in adr
