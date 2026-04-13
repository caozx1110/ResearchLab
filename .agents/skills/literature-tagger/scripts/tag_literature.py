#!/usr/bin/env python3
"""Curate literature topics, tags, and tag taxonomy under kb/library/literature/."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    bootstrap_workspace,
    discover_keyword_tags,
    domain_taxonomy_seeds,
    ensure_research_runtime,
    find_project_root,
    infer_topics_and_tags,
    merge_keyword_tags,
    literature_tag_taxonomy_path,
    literature_tags_path,
    load_yaml,
    rebuild_literature_index,
    rebuild_literature_tag_index,
    research_root,
    utc_now_iso,
    write_yaml_if_changed,
    yaml_default,
)

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DEFAULT_TAXONOMY_POLICY = {
    "canonical_style": "lowercase-hyphen-slug",
    "unknown_tag_policy": "allow-with-lint",
    "notes": "Canonical tags should be short, reusable, and stable across papers.",
}


def literature_root(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "literature"


def metadata_path(project_root: Path, source_id: str) -> Path:
    return literature_root(project_root) / source_id / "metadata.yaml"


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def normalized_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    return sorted(set(cleaned))


def auto_keyword_tags(metadata: dict[str, Any]) -> set[str]:
    tagging = metadata.get("tagging", {})
    if not isinstance(tagging, dict):
        return set()
    discovered: set[str] = set()
    for value in tagging.get("auto_adopted_tags", []):
        slug = slugify_tag(str(value))
        if slug:
            discovered.add(slug)
    for item in tagging.get("keyword_candidates", []):
        if not isinstance(item, dict):
            continue
        slug = slugify_tag(str(item.get("tag") or ""))
        if slug:
            discovered.add(slug)
    return discovered


def slugify_tag(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[_./\\\s]+", "-", text)
    text = re.sub(r"[^a-z0-9-]+", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def load_metadata(path: Path) -> dict[str, Any]:
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict) or not payload.get("id"):
        raise SystemExit(f"Invalid literature metadata: {path}")
    return payload


def resolve_metadata_paths(
    project_root: Path,
    source_ids: list[str],
    *,
    select_all: bool,
    default_all: bool = False,
) -> list[Path]:
    if select_all or (default_all and not source_ids):
        paths = sorted(literature_root(project_root).glob("*/metadata.yaml"))
        if not paths:
            raise SystemExit("No canonical literature metadata found.")
        return paths
    if not source_ids:
        raise SystemExit("Provide --source-id or --all.")
    paths = [metadata_path(project_root, source_id) for source_id in source_ids]
    missing = [path for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"Missing literature metadata: {missing[0]}")
    return paths


def blank_taxonomy_payload(project_root: Path) -> dict[str, Any]:
    return {
        **yaml_default("literature-tag-taxonomy", "literature-tagger", status="active", confidence=0.8),
        "inputs": [],
        "policy": dict(DEFAULT_TAXONOMY_POLICY),
        "items": {},
    }


def normalize_taxonomy_item(canonical_tag: str, item: dict[str, Any] | None = None) -> dict[str, Any]:
    item = item or {}
    canonical = slugify_tag(str(item.get("canonical_tag") or canonical_tag))
    aliases = sorted(
        {
            alias
            for alias in (slugify_tag(str(value)) for value in item.get("aliases", []))
            if alias and alias != canonical
        }
    )
    return {
        "id": canonical,
        "canonical_tag": canonical,
        "aliases": aliases,
        "topic_hints": normalized_list(item.get("topic_hints", [])),
        "description": str(item.get("description") or "").strip(),
        "status": str(item.get("status") or "active").strip() or "active",
    }


def load_taxonomy(project_root: Path) -> dict[str, Any]:
    path = literature_tag_taxonomy_path(project_root)
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        payload = blank_taxonomy_payload(project_root)
    payload.setdefault("id", "literature-tag-taxonomy")
    payload.setdefault("status", "active")
    payload.setdefault("generated_by", "literature-tagger")
    payload.setdefault("generated_at", utc_now_iso())
    payload.setdefault("inputs", [])
    payload.setdefault("confidence", 0.8)
    payload.setdefault("policy", dict(DEFAULT_TAXONOMY_POLICY))
    payload.setdefault("items", {})
    items: dict[str, Any] = {}
    for key, value in payload["items"].items():
        if not isinstance(value, dict):
            continue
        canonical = slugify_tag(str(value.get("canonical_tag") or key))
        if not canonical:
            continue
        items[canonical] = normalize_taxonomy_item(canonical, value)
    for key, value in domain_taxonomy_seeds(project_root).items():
        canonical = slugify_tag(key)
        if canonical not in items:
            items[canonical] = normalize_taxonomy_item(canonical, value)
    payload["items"] = {key: items[key] for key in sorted(items)}
    payload["policy"] = {**DEFAULT_TAXONOMY_POLICY, **(payload["policy"] if isinstance(payload["policy"], dict) else {})}
    return payload


def write_taxonomy(project_root: Path, taxonomy: dict[str, Any], *, inputs: list[str] | None = None) -> None:
    taxonomy["generated_by"] = "literature-tagger"
    taxonomy["generated_at"] = utc_now_iso()
    taxonomy["items"] = {key: taxonomy["items"][key] for key in sorted(taxonomy.get("items", {}))}
    if inputs is not None:
        taxonomy["inputs"] = sorted(set(str(value) for value in inputs if str(value).strip()))
    write_yaml_if_changed(literature_tag_taxonomy_path(project_root), taxonomy)


def taxonomy_alias_map(taxonomy: dict[str, Any]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for canonical, item in taxonomy.get("items", {}).items():
        alias_map[canonical] = canonical
        if not isinstance(item, dict):
            continue
        for alias in item.get("aliases", []):
            normalized = slugify_tag(str(alias))
            if normalized:
                alias_map[normalized] = canonical
    return alias_map


def canonicalize_tags(tags: list[str], taxonomy: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    alias_map = taxonomy_alias_map(taxonomy)
    known = set(taxonomy.get("items", {}))
    canonical_tags: set[str] = set()
    alias_hits: set[str] = set()
    unknown: set[str] = set()
    for tag in tags:
        slug = slugify_tag(tag)
        if not slug:
            continue
        canonical = alias_map.get(slug, slug)
        canonical_tags.add(canonical)
        if canonical != slug:
            alias_hits.add(slug)
        if canonical not in known:
            unknown.add(canonical)
    return sorted(canonical_tags), sorted(alias_hits), sorted(unknown)


def sync_taxonomy_from_metadata(
    project_root: Path,
    taxonomy: dict[str, Any],
    *,
    metadata_paths: list[Path] | None = None,
) -> tuple[dict[str, Any], int, int]:
    paths = metadata_paths or resolve_metadata_paths(project_root, [], select_all=True, default_all=True)
    alias_map = taxonomy_alias_map(taxonomy)
    added = 0
    updated = 0
    for path in paths:
        metadata = load_metadata(path)
        topics = normalized_list(metadata.get("topics", []))
        discovered_tags = auto_keyword_tags(metadata)
        for raw_tag in metadata.get("tags", []):
            slug = slugify_tag(str(raw_tag))
            if not slug:
                continue
            canonical = alias_map.get(slug, slug)
            item = taxonomy["items"].get(canonical)
            if item is None:
                taxonomy["items"][canonical] = normalize_taxonomy_item(
                    canonical,
                    {
                        "aliases": [slug] if slug != canonical else [],
                        "topic_hints": topics,
                        "description": "Auto-discovered keyword tag from canonical literature metadata." if canonical in discovered_tags else "",
                        "status": "discovered" if canonical in discovered_tags else "active",
                    },
                )
                alias_map[canonical] = canonical
                if slug != canonical:
                    alias_map[slug] = canonical
                added += 1
                continue
            before_aliases = set(item.get("aliases", []))
            before_topics = set(item.get("topic_hints", []))
            aliases = set(before_aliases)
            if slug != canonical:
                aliases.add(slug)
                alias_map[slug] = canonical
            item["aliases"] = sorted(aliases)
            item["topic_hints"] = sorted(before_topics | set(topics))
            taxonomy["items"][canonical] = normalize_taxonomy_item(canonical, item)
            if set(taxonomy["items"][canonical]["aliases"]) != before_aliases or set(taxonomy["items"][canonical]["topic_hints"]) != before_topics:
                updated += 1
    taxonomy["items"] = {key: taxonomy["items"][key] for key in sorted(taxonomy["items"])}
    return taxonomy, added, updated


def refresh_views(project_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    index_payload = rebuild_literature_index(project_root, generated_by="literature-tagger")
    tag_payload = rebuild_literature_tag_index(project_root, generated_by="literature-tagger")
    return index_payload, tag_payload


def metadata_inputs(paths: list[Path]) -> list[str]:
    return [f"lit:{load_metadata(path).get('id')}" for path in paths]


def update_tagging_audit(metadata: dict[str, Any], *, mode: str, strategy: str, inputs: list[str], alias_hits: list[str] | None = None, unknown_tags: list[str] | None = None) -> None:
    existing = metadata.get("tagging", {})
    audit = {
        "updated_by": "literature-tagger",
        "updated_at": utc_now_iso(),
        "mode": mode,
        "strategy": strategy,
        "inputs": sorted(set(inputs)),
    }
    if alias_hits:
        audit["alias_hits"] = sorted(set(alias_hits))
    if unknown_tags:
        audit["unknown_tags"] = sorted(set(unknown_tags))
    if isinstance(existing, dict):
        for key in ("keyword_candidates", "auto_adopted_tags"):
            if key in existing:
                audit[key] = existing[key]
    metadata["tagging"] = audit


def command_refresh_index(_: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    index_payload, tag_payload = refresh_views(project_root)
    taxonomy = load_taxonomy(project_root)
    print(
        f"refreshed literature views: {len(index_payload.get('items', {}))} papers, "
        f"{len(tag_payload.get('items', {}))} tags, "
        f"{len(taxonomy.get('items', {}))} taxonomy entries"
    )
    return 0


def command_retag(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    paths = resolve_metadata_paths(project_root, args.source_id, select_all=args.all)
    changed = 0
    alias_hits_seen: set[str] = set()
    unknown_seen: set[str] = set()
    for path in paths:
        metadata = load_metadata(path)
        title = str(metadata.get("canonical_title") or "").strip()
        abstract = str(metadata.get("abstract") or "").strip()
        source_text = "\n".join(part for part in (title, abstract) if part)
        if not source_text:
            print(f"[skip] {metadata.get('id')}: no title or abstract text")
            continue
        inferred_topics, inferred_tags = infer_topics_and_tags(source_text)
        existing_topics = normalized_list(metadata.get("topics", []))
        existing_tags = normalized_list(metadata.get("tags", []))
        if args.mode == "replace":
            next_topics = normalized_list(inferred_topics)
            seed_tags = inferred_tags
        else:
            next_topics = normalized_list(existing_topics + inferred_topics)
            seed_tags = existing_tags + inferred_tags
        keyword_candidates = discover_keyword_tags(
            title,
            abstract,
            project_root=project_root,
            existing_tags=seed_tags,
        )
        seed_tags = merge_keyword_tags(seed_tags, keyword_candidates)
        auto_adopted_tags = [item["tag"] for item in keyword_candidates if item.get("tag") in seed_tags]
        next_tags, alias_hits, unknown_tags = canonicalize_tags(seed_tags, taxonomy)
        alias_hits_seen.update(alias_hits)
        unknown_seen.update(unknown_tags)
        existing_tagging = metadata.get("tagging", {})
        if not isinstance(existing_tagging, dict):
            existing_tagging = {}
        existing_keyword_candidates = [
            item for item in existing_tagging.get("keyword_candidates", []) if isinstance(item, dict)
        ]
        existing_auto_adopted = sorted(
            {
                slugify_tag(str(item))
                for item in existing_tagging.get("auto_adopted_tags", [])
                if slugify_tag(str(item))
            }
        )
        next_auto_adopted = sorted(set(auto_adopted_tags))
        if (
            next_topics == existing_topics
            and next_tags == existing_tags
            and existing_keyword_candidates == keyword_candidates
            and existing_auto_adopted == next_auto_adopted
        ):
            print(f"[unchanged] {metadata.get('id')}")
            continue
        metadata["topics"] = next_topics
        metadata["tags"] = next_tags
        existing_tagging["keyword_candidates"] = keyword_candidates
        existing_tagging["auto_adopted_tags"] = next_auto_adopted
        metadata["tagging"] = existing_tagging
        update_tagging_audit(
            metadata,
            mode=args.mode,
            strategy="heuristic-title-abstract",
            inputs=["field:canonical_title", "field:abstract", relative_path(project_root, literature_tag_taxonomy_path(project_root))],
            alias_hits=alias_hits,
            unknown_tags=unknown_tags,
        )
        write_yaml_if_changed(path, metadata)
        changed += 1
        print(f"[retagged] {metadata.get('id')}: {', '.join(next_tags)}")
    taxonomy, added, updated = sync_taxonomy_from_metadata(project_root, taxonomy, metadata_paths=paths)
    write_taxonomy(
        project_root,
        taxonomy,
        inputs=[relative_path(project_root, literature_tags_path(project_root)), *metadata_inputs(paths)],
    )
    index_payload, tag_payload = refresh_views(project_root)
    print(
        f"retag complete: {changed} updated, {len(index_payload.get('items', {}))} papers, "
        f"{len(tag_payload.get('items', {}))} tags, taxonomy +{added}/~{updated}"
    )
    if alias_hits_seen:
        print(f"alias-normalized: {', '.join(sorted(alias_hits_seen))}")
    if unknown_seen:
        print(f"new-canonical-tags: {', '.join(sorted(unknown_seen))}")
    return 0


def command_assign(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    paths = resolve_metadata_paths(project_root, args.source_id, select_all=False)
    manual_topics = normalized_list(args.topic)
    manual_tags = normalized_list(args.tag)
    if not manual_topics and not manual_tags:
        raise SystemExit("Provide at least one --topic or --tag.")
    changed = 0
    alias_hits_seen: set[str] = set()
    unknown_seen: set[str] = set()
    for path in paths:
        metadata = load_metadata(path)
        existing_topics = normalized_list(metadata.get("topics", []))
        existing_tags = normalized_list(metadata.get("tags", []))
        if args.replace:
            next_topics = manual_topics
            seed_tags = manual_tags
            mode = "replace"
        else:
            next_topics = normalized_list(existing_topics + manual_topics)
            seed_tags = existing_tags + manual_tags
            mode = "augment"
        next_tags, alias_hits, unknown_tags = canonicalize_tags(seed_tags, taxonomy)
        alias_hits_seen.update(alias_hits)
        unknown_seen.update(unknown_tags)
        if next_topics == existing_topics and next_tags == existing_tags:
            print(f"[unchanged] {metadata.get('id')}")
            continue
        metadata["topics"] = next_topics
        metadata["tags"] = next_tags
        update_tagging_audit(
            metadata,
            mode=mode,
            strategy="manual-assignment",
            inputs=[
                relative_path(project_root, literature_tag_taxonomy_path(project_root)),
                *[f"manual:topic:{topic}" for topic in manual_topics],
                *[f"manual:tag:{tag}" for tag in manual_tags],
            ],
            alias_hits=alias_hits,
            unknown_tags=unknown_tags,
        )
        write_yaml_if_changed(path, metadata)
        changed += 1
        print(f"[assigned] {metadata.get('id')}: {', '.join(next_tags)}")
    taxonomy, added, updated = sync_taxonomy_from_metadata(project_root, taxonomy, metadata_paths=paths)
    write_taxonomy(
        project_root,
        taxonomy,
        inputs=[relative_path(project_root, literature_tags_path(project_root)), *metadata_inputs(paths)],
    )
    index_payload, tag_payload = refresh_views(project_root)
    print(
        f"assignment complete: {changed} updated, {len(index_payload.get('items', {}))} papers, "
        f"{len(tag_payload.get('items', {}))} tags, taxonomy +{added}/~{updated}"
    )
    if alias_hits_seen:
        print(f"alias-normalized: {', '.join(sorted(alias_hits_seen))}")
    if unknown_seen:
        print(f"new-canonical-tags: {', '.join(sorted(unknown_seen))}")
    return 0


def command_taxonomy_sync(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    paths = resolve_metadata_paths(project_root, args.source_id, select_all=args.all, default_all=True)
    taxonomy, added, updated = sync_taxonomy_from_metadata(project_root, taxonomy, metadata_paths=paths)
    inputs = [relative_path(project_root, literature_tags_path(project_root)), *metadata_inputs(paths)]
    write_taxonomy(project_root, taxonomy, inputs=inputs)
    _, tag_payload = refresh_views(project_root)
    print(
        f"taxonomy sync complete: {len(paths)} papers scanned, +{added}/~{updated} taxonomy entries, "
        f"{len(tag_payload.get('items', {}))} active tags"
    )
    return 0


def command_taxonomy_upsert(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    canonical = slugify_tag(args.tag)
    if not canonical:
        raise SystemExit("Canonical tag is empty after normalization.")
    item = normalize_taxonomy_item(canonical, taxonomy.get("items", {}).get(canonical, {}))
    aliases = {alias for alias in item.get("aliases", [])}
    if args.replace_aliases:
        aliases = set()
    aliases |= {alias for alias in (slugify_tag(value) for value in args.alias) if alias and alias != canonical}
    topics = set(item.get("topic_hints", []))
    if args.replace_topics:
        topics = set()
    topics |= set(normalized_list(args.topic))
    if args.description is not None:
        item["description"] = args.description.strip()
    item["aliases"] = sorted(aliases)
    item["topic_hints"] = sorted(topics)
    item["status"] = args.status
    taxonomy["items"][canonical] = normalize_taxonomy_item(canonical, item)
    write_taxonomy(
        project_root,
        taxonomy,
        inputs=[
            f"manual:canonical:{canonical}",
            *[f"manual:alias:{alias}" for alias in taxonomy["items"][canonical]["aliases"]],
            *[f"manual:topic:{topic}" for topic in taxonomy["items"][canonical]["topic_hints"]],
        ],
    )
    _, tag_payload = refresh_views(project_root)
    print(
        f"taxonomy upserted: {canonical} (aliases={len(taxonomy['items'][canonical]['aliases'])}, "
        f"topics={len(taxonomy['items'][canonical]['topic_hints'])}, active-tags={len(tag_payload.get('items', {}))})"
    )
    return 0


def command_taxonomy_apply(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    paths = resolve_metadata_paths(project_root, args.source_id, select_all=args.all)
    changed = 0
    alias_hits_seen: set[str] = set()
    unknown_seen: set[str] = set()
    for path in paths:
        metadata = load_metadata(path)
        existing_tags = normalized_list(metadata.get("tags", []))
        next_tags, alias_hits, unknown_tags = canonicalize_tags(existing_tags, taxonomy)
        alias_hits_seen.update(alias_hits)
        unknown_seen.update(unknown_tags)
        if next_tags == existing_tags:
            print(f"[unchanged] {metadata.get('id')}")
            continue
        metadata["tags"] = next_tags
        update_tagging_audit(
            metadata,
            mode="normalize",
            strategy="taxonomy-apply",
            inputs=[relative_path(project_root, literature_tag_taxonomy_path(project_root))],
            alias_hits=alias_hits,
            unknown_tags=unknown_tags,
        )
        write_yaml_if_changed(path, metadata)
        changed += 1
        print(f"[canonicalized] {metadata.get('id')}: {', '.join(next_tags)}")
    taxonomy, added, updated = sync_taxonomy_from_metadata(project_root, taxonomy, metadata_paths=paths)
    write_taxonomy(
        project_root,
        taxonomy,
        inputs=[relative_path(project_root, literature_tags_path(project_root)), *metadata_inputs(paths)],
    )
    index_payload, tag_payload = refresh_views(project_root)
    print(
        f"taxonomy apply complete: {changed} updated, {len(index_payload.get('items', {}))} papers, "
        f"{len(tag_payload.get('items', {}))} tags, taxonomy +{added}/~{updated}"
    )
    if alias_hits_seen:
        print(f"alias-normalized: {', '.join(sorted(alias_hits_seen))}")
    if unknown_seen:
        print(f"still-unregistered-before-sync: {', '.join(sorted(unknown_seen))}")
    return 0


def command_taxonomy_lint(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    taxonomy = load_taxonomy(project_root)
    paths = resolve_metadata_paths(project_root, args.source_id, select_all=args.all, default_all=True)
    issues: list[str] = []
    alias_owner: dict[str, str] = {}
    for canonical, item in taxonomy.get("items", {}).items():
        if not SLUG_PATTERN.match(canonical):
            issues.append(f"[taxonomy] canonical tag is not slug-stable: {canonical}")
        if not isinstance(item, dict):
            issues.append(f"[taxonomy] invalid item payload for {canonical}")
            continue
        stored = slugify_tag(str(item.get("canonical_tag") or canonical))
        if stored != canonical:
            issues.append(f"[taxonomy] canonical_tag mismatch: {canonical} -> {stored}")
        for alias in item.get("aliases", []):
            normalized = slugify_tag(str(alias))
            if not normalized:
                issues.append(f"[taxonomy] empty alias under {canonical}")
                continue
            if normalized == canonical:
                issues.append(f"[taxonomy] redundant alias equals canonical tag: {canonical}")
            if not SLUG_PATTERN.match(normalized):
                issues.append(f"[taxonomy] alias is not slug-stable: {canonical} <- {alias}")
            owner = alias_owner.get(normalized)
            if owner and owner != canonical:
                issues.append(f"[taxonomy] alias collision: {normalized} -> {owner}, {canonical}")
            alias_owner[normalized] = canonical

    alias_map = taxonomy_alias_map(taxonomy)
    for path in paths:
        metadata = load_metadata(path)
        tags = metadata.get("tags", [])
        canonical_tags: list[str] = []
        for raw_tag in tags:
            raw = str(raw_tag).strip()
            slug = slugify_tag(raw)
            if not raw:
                issues.append(f"[metadata:{metadata.get('id')}] empty tag value")
                continue
            if raw != slug:
                issues.append(f"[metadata:{metadata.get('id')}] non-canonical tag formatting: {raw} -> {slug}")
            canonical = alias_map.get(slug, slug)
            canonical_tags.append(canonical)
            if slug not in alias_map and canonical not in taxonomy.get("items", {}):
                issues.append(f"[metadata:{metadata.get('id')}] tag not registered in taxonomy: {raw}")
            elif canonical != slug:
                issues.append(f"[metadata:{metadata.get('id')}] alias tag should canonicalize: {raw} -> {canonical}")
        if len(canonical_tags) != len(set(canonical_tags)):
            issues.append(f"[metadata:{metadata.get('id')}] duplicate canonical tags after normalization: {canonical_tags}")

    if not issues:
        print(
            f"taxonomy lint clean: {len(taxonomy.get('items', {}))} taxonomy entries, "
            f"{len(paths)} papers checked"
        )
        return 0
    for issue in issues:
        print(issue)
    print(f"taxonomy lint found {len(issues)} issue(s)")
    return 1 if args.strict else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh-index", help="Refresh derived literature views from current metadata.")
    refresh_parser.set_defaults(func=command_refresh_index)

    retag_parser = subparsers.add_parser("retag", help="Infer topics and tags from canonical title and abstract.")
    retag_parser.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to retag.")
    retag_parser.add_argument("--all", action="store_true", help="Retag every canonical literature entry.")
    retag_parser.add_argument("--mode", choices=("augment", "replace"), default="augment", help="Whether to append inferred tags or replace existing ones.")
    retag_parser.set_defaults(func=command_retag)

    assign_parser = subparsers.add_parser("assign", help="Manually add or replace topics and tags on canonical literature.")
    assign_parser.add_argument("--source-id", action="append", required=True, help="Canonical literature source ID to update.")
    assign_parser.add_argument("--topic", action="append", default=[], help="Topic value to add.")
    assign_parser.add_argument("--tag", action="append", default=[], help="Tag value to add.")
    assign_parser.add_argument("--replace", action="store_true", help="Replace existing topics and tags with the provided values.")
    assign_parser.set_defaults(func=command_assign)

    taxonomy_sync_parser = subparsers.add_parser("taxonomy-sync", help="Sync tag-taxonomy.yaml from current literature metadata.")
    taxonomy_sync_parser.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to scan.")
    taxonomy_sync_parser.add_argument("--all", action="store_true", help="Scan every canonical literature entry.")
    taxonomy_sync_parser.set_defaults(func=command_taxonomy_sync)

    taxonomy_upsert_parser = subparsers.add_parser("taxonomy-upsert", help="Add or update a canonical taxonomy entry.")
    taxonomy_upsert_parser.add_argument("--tag", required=True, help="Canonical tag name to create or update.")
    taxonomy_upsert_parser.add_argument("--alias", action="append", default=[], help="Alias tag that should map to the canonical tag.")
    taxonomy_upsert_parser.add_argument("--topic", action="append", default=[], help="Topic hint associated with the canonical tag.")
    taxonomy_upsert_parser.add_argument("--description", default=None, help="Short human-readable description for the tag.")
    taxonomy_upsert_parser.add_argument("--status", default="active", help="Taxonomy entry status.")
    taxonomy_upsert_parser.add_argument("--replace-aliases", action="store_true", help="Replace aliases instead of appending.")
    taxonomy_upsert_parser.add_argument("--replace-topics", action="store_true", help="Replace topic hints instead of appending.")
    taxonomy_upsert_parser.set_defaults(func=command_taxonomy_upsert)

    taxonomy_apply_parser = subparsers.add_parser("taxonomy-apply", help="Rewrite metadata tags to canonical taxonomy tags.")
    taxonomy_apply_parser.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to normalize.")
    taxonomy_apply_parser.add_argument("--all", action="store_true", help="Normalize every canonical literature entry.")
    taxonomy_apply_parser.set_defaults(func=command_taxonomy_apply)

    taxonomy_lint_parser = subparsers.add_parser("taxonomy-lint", help="Check taxonomy and metadata tags for normalization issues.")
    taxonomy_lint_parser.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to check.")
    taxonomy_lint_parser.add_argument("--all", action="store_true", help="Check every canonical literature entry.")
    taxonomy_lint_parser.add_argument("--strict", action="store_true", help="Exit non-zero when issues are found.")
    taxonomy_lint_parser.set_defaults(func=command_taxonomy_lint)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    ensure_research_runtime(project_root, "literature-tagger")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
