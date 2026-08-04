"""Shared deterministic prepare/verify/confirm flow for document analyzers.

The flow transports Agent-authored understanding and verifies its evidence.  It
does not infer, summarize, grade, or otherwise author material judgements.
"""
from __future__ import annotations

import argparse
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .common import (
    add_project_root_argument,
    clean_text,
    load_yaml,
    print_resolved_project_roots,
    write_text_if_changed,
    write_yaml_if_changed,
)
from .confirm import confirm_unit, write_record
from .evidence import (
    attach_claims,
    build_verification_receipt,
    validate_claims,
    verify_claim_evidence,
)
from .git_ops import checkpoint_and_report as default_checkpoint_and_report
from .index import build_index
from .paths import (
    candidate_pools_path,
    passage_search_cache_path,
    project_root,
    rel,
    topic_taxonomy_path,
)
from .preference_selection import (
    canonical_digest,
    regular_file_binding,
    regular_tree_binding,
    resolve_operation_preferences,
    task_context_digest,
)
from .records import (
    append_history,
    canonical_record_snapshot_for_record,
    command_mutation,
    locate_record,
)


Checkpoint = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class AnalyzerNoteSpec:
    """Kind-specific values for the shared note lifecycle."""

    kind: str
    command: str
    id_option: str
    id_key: str
    preference_skill: str
    preference_operation: str
    preference_orientation_name: str
    note_elements: tuple[str, ...]
    element_claim_types: Mapping[str, str]
    element_targets: Mapping[str, tuple[str, str, str]]
    element_headings: Mapping[str, str]
    evidence_ref_format: Mapping[str, str]
    cache_id_keys: tuple[str, ...]
    fill_name: str
    note_name: str
    claims_name: str
    state_field: str
    source_identity: str
    parser_description: str
    scaffold_description: str
    note_intro: tuple[str, ...]
    prepare_guidance: str
    preference_label: str
    cache_identity_label: str
    prepare_history_action: str
    prepare_history_summary: str
    verify_history_action: str
    verify_history_summary: str
    scaffold_checkpoint_message: str
    verify_checkpoint_message: str
    confirm_checkpoint_message: str

    @property
    def id_dest(self) -> str:
        return self.id_option.removeprefix("--").replace("-", "_")


class AnalyzerNoteFlow:
    """One canonical deterministic lifecycle, configured by ``AnalyzerNoteSpec``."""

    def __init__(
        self,
        spec: AnalyzerNoteSpec,
        *,
        script_path: Path,
        default_project_root: Path,
        checkpoint: Checkpoint | None = None,
    ) -> None:
        self.spec = spec
        self.script_path = script_path
        self.default_project_root = default_project_root
        self._checkpoint = checkpoint or default_checkpoint_and_report
        self._active_mutation: ContextVar[bool] = ContextVar(
            f"{spec.kind}_analyzer_active_mutation", default=False
        )
        self._pending_checkpoint: ContextVar[
            tuple[Path, str, str, list[Path]] | None
        ] = ContextVar(f"{spec.kind}_analyzer_pending_checkpoint", default=None)

    def index_targets(self, root: Path) -> list[Path]:
        return [
            root / "kb" / "index.yaml",
            root / "kb" / "index.md",
            topic_taxonomy_path(root),
            candidate_pools_path(root),
            passage_search_cache_path(root),
        ]

    def _transaction(
        self,
        op_name: str,
        root: Path,
        targets: Sequence[Path],
        operation: Callable[[], int],
    ) -> int:
        active_token = self._active_mutation.set(True)
        checkpoint_token = self._pending_checkpoint.set(None)
        pending: tuple[Path, str, str, list[Path]] | None = None
        try:
            with command_mutation(
                root,
                f"{self.spec.preference_skill}:{op_name}",
                list(targets),
            ):
                result = operation()
            pending = self._pending_checkpoint.get()
        finally:
            self._pending_checkpoint.reset(checkpoint_token)
            self._active_mutation.reset(active_token)
        if pending is not None:
            self._checkpoint(
                pending[0],
                trigger=pending[1],
                message=pending[2],
                target_paths=pending[3],
            )
        return result

    @staticmethod
    def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--confirmed-by", default="")
        parser.add_argument("--evidence", action="append", required=True)
        parser.add_argument("--user-authorization", default="")
        parser.add_argument("--authorization-source", default="")

    @staticmethod
    def cache_path(unit_root: Path) -> Path:
        return unit_root / "parse-cache.yaml"

    def cache_unit_id(self, payload: Mapping[str, object]) -> str:
        for key in self.spec.cache_id_keys:
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return ""

    def normalized_cache_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        primary_key = self.spec.cache_id_keys[0]
        if "paper_id" not in payload or primary_key in payload or "unit_id" in payload:
            return payload
        normalized = dict(payload)
        normalized[primary_key] = normalized.pop("paper_id")
        return normalized

    def load_cache_chunks(self, unit_root: Path) -> tuple[list[dict], str]:
        cache_path = self.cache_path(unit_root)
        if not cache_path.exists():
            return [], "section"
        payload = load_yaml(cache_path, default={})
        if not isinstance(payload, dict):
            return [], "section"
        payload = self.normalized_cache_payload(payload)
        chunks = payload.get("chunks") or []
        locator_kind = str(payload.get("locator_kind") or "section")
        if not isinstance(chunks, list):
            return [], locator_kind
        return [chunk for chunk in chunks if isinstance(chunk, dict)], locator_kind

    @staticmethod
    def chunk_locator(chunk: Mapping[str, object]) -> str:
        label = str(chunk.get("label") or "")
        if label.startswith("section:"):
            return label
        anchor = str(chunk.get("anchor") or "")
        if anchor:
            return f"section:{anchor}"
        return "section"

    def evidence_digest(
        self,
        chunks: Sequence[Mapping[str, object]],
        *,
        chunk_limit: int,
        excerpt_chars: int,
    ) -> list[dict]:
        digest: list[dict] = []
        for chunk in chunks[:chunk_limit]:
            text = clean_text(str(chunk.get("text") or ""))
            if not text:
                continue
            digest.append(
                {
                    "locator": self.chunk_locator(chunk),
                    "artifact": "parse-cache.yaml",
                    "label": str(chunk.get("label") or ""),
                    "excerpt": text[:excerpt_chars],
                }
            )
        return digest

    def build_note_scaffold(
        self,
        record: dict,
        source_chunks: list[dict],
        *,
        digest_chunks: int,
        digest_chars: int,
        preference_task_context: Mapping[str, object] | None = None,
    ) -> dict:
        spec = self.spec
        scaffold: dict[str, Any] = {
            spec.id_key: record["id"],
            "kind": spec.kind,
            "status": "awaiting_agent_fill",
            "phase": "prepare",
            "fill_contract": {
                "description": spec.scaffold_description,
                "required_elements": list(spec.note_elements),
                "element_claim_types": dict(spec.element_claim_types),
                "evidence_ref_format": dict(spec.evidence_ref_format),
            },
            "evidence_digest": self.evidence_digest(
                source_chunks,
                chunk_limit=digest_chunks,
                excerpt_chars=digest_chars,
            ),
            "elements": [
                {
                    "element": name,
                    "claim_type": spec.element_claim_types[name],
                    "content": "",
                    "evidence_refs": [],
                }
                for name in spec.note_elements
            ],
        }
        if preference_task_context is not None:
            context = dict(preference_task_context)
            scaffold["preference_consumer"] = {
                "skill": spec.preference_skill,
                "operation": spec.preference_operation,
                "task_context": context,
                "task_context_digest": task_context_digest(
                    skill=spec.preference_skill,
                    operation=spec.preference_operation,
                    canonical_inputs=context,
                ),
            }
        return scaffold

    def preference_orientation(self, record: Mapping[str, object]) -> dict[str, object]:
        spec = self.spec
        phase_contract = {
            "prepare": "owner-writes-canonical-orientation-before-agent-authoring",
            "author": "runtime-agent",
            "verify": "owner-recomputes-context-before-business-write",
            "fillable_fields": ["elements[].content", "elements[].evidence_refs"],
        }
        return {
            "schema": "analyzer-preference-orientation/v1",
            "canonical_id": str(record.get("id") or ""),
            "canonical_kind": spec.kind,
            "skill": spec.preference_skill,
            "operation": spec.preference_operation,
            "phase_contract": phase_contract,
            "required_elements": list(spec.note_elements),
            "element_claim_types": dict(spec.element_claim_types),
            "evidence_locator_family": "html-section-anchor",
        }

    def preference_context(
        self,
        root: Path,
        record: Mapping[str, object],
        unit_root: Path,
    ) -> dict[str, object]:
        spec = self.spec
        orientation_path = unit_root / spec.preference_orientation_name
        orientation_binding = regular_file_binding(
            orientation_path,
            logical_identity=spec.preference_orientation_name,
            trusted_root=root,
        )
        orientation = load_yaml(orientation_path, default={})
        expected_orientation = self.preference_orientation(record)
        if orientation != expected_orientation:
            raise ValueError("immutable analyzer orientation contract was modified")

        cache_path = self.cache_path(unit_root)
        cache_binding = regular_file_binding(
            cache_path,
            logical_identity="parse-cache.yaml",
            trusted_root=root,
        )
        cache = load_yaml(cache_path, default={})
        if not isinstance(cache, dict) or self.cache_unit_id(cache) != str(
            record.get("id") or ""
        ):
            raise ValueError(
                f"canonical {spec.cache_identity_label} parse cache has a mismatched identity"
            )
        record_binding = regular_file_binding(
            unit_root / "record.yaml",
            logical_identity="record.yaml",
            trusted_root=root,
        )
        source_binding = regular_tree_binding(
            unit_root / "source",
            logical_identity=spec.source_identity,
            trusted_root=root,
        )
        return {
            "canonical_id": str(record.get("id") or ""),
            "canonical_kind": spec.kind,
            "operation": spec.preference_operation,
            "record_content_digest": record_binding["bytes_digest"],
            "phase_contract_digest": canonical_digest(expected_orientation["phase_contract"]),
            "immutable_orientation_digest": orientation_binding["bytes_digest"],
            "parse_cache_identity_digest": cache_binding["identity_digest"],
            "parse_cache_bytes_digest": cache_binding["bytes_digest"],
            "source_artifacts_identity_digest": source_binding["identity_digest"],
            "source_artifacts_bytes_digest": source_binding["bytes_digest"],
        }

    def resolve_preferences(
        self,
        root: Path,
        record: Mapping[str, object],
        unit_root: Path,
        *,
        selection_id: str,
    ) -> dict[str, object]:
        context = self.preference_context(root, record, unit_root)
        return resolve_operation_preferences(
            root,
            selection_id=selection_id,
            skill=self.spec.preference_skill,
            operation=self.spec.preference_operation,
            canonical_inputs=context,
        )

    def persist_preference_binding(
        self,
        record: dict,
        binding: Mapping[str, object],
    ) -> None:
        payload = record.setdefault("payload", {})
        contexts = payload.get("preference_contexts")
        contexts = dict(contexts) if isinstance(contexts, Mapping) else {}
        if binding:
            contexts[self.spec.preference_operation] = dict(binding)
        else:
            contexts.pop(self.spec.preference_operation, None)
        if contexts:
            payload["preference_contexts"] = contexts
        else:
            payload.pop("preference_contexts", None)

    @staticmethod
    def elements_by_name(fill: Any) -> dict[str, dict]:
        elements: dict[str, dict] = {}
        if isinstance(fill, dict):
            raw = fill.get("elements")
            if isinstance(raw, (list, tuple)):
                for item in raw:
                    if isinstance(item, dict) and str(item.get("element") or "").strip():
                        elements[str(item.get("element")).strip().lower()] = item
        return elements

    def claim_from_element(self, name: str, element: Mapping[str, object]) -> dict:
        return {
            "id": f"claim-{name}",
            "text": clean_text(str(element.get("content") or "")),
            "claim_type": str(
                element.get("claim_type")
                or self.spec.element_claim_types.get(name, "inference")
            ),
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": element.get("evidence_refs") or [],
        }

    def verify_note_fill(self, fill: Any, unit_dir: Path) -> tuple[list[str], list[dict]]:
        violations: list[str] = []
        elements = self.elements_by_name(fill)
        claims: list[dict] = []
        for name in self.spec.note_elements:
            element = elements.get(name)
            if element is None:
                violations.append(
                    f"element '{name}': missing (all four elements are required)"
                )
                continue
            content = clean_text(str(element.get("content") or ""))
            if not content:
                violations.append(
                    f"element '{name}': empty content — the agent must fill it"
                )
            refs = element.get("evidence_refs") or []
            if not refs:
                violations.append(
                    f"element '{name}': no evidence_refs — every element must cite >=1 verbatim quote"
                )
            claim = self.claim_from_element(name, element)
            claims.append(claim)
            for violation in verify_claim_evidence(claim, unit_dir):
                violations.append(f"element '{name}': {violation}")
        for violation in validate_claims(claims):
            violations.append(f"claim-structure: {violation}")
        return violations, claims

    def apply_note_fill_to_payload(self, record: dict, claims: list[dict]) -> None:
        payload = record.setdefault("payload", {})
        sections = {
            section: payload.setdefault(section, {})
            for section, _field, _shape in self.spec.element_targets.values()
        }
        by_id = {str(claim.get("id") or ""): claim for claim in claims}
        for name in self.spec.note_elements:
            claim = by_id.get(f"claim-{name}")
            if claim is None:
                continue
            text = clean_text(str(claim.get("text") or ""))
            section, field, shape = self.spec.element_targets[name]
            target = sections[section]
            if shape == "list":
                existing = target.get(field)
                items = list(existing) if isinstance(existing, list) else []
                if text and text not in items:
                    items.append(text)
                target[field] = items
            else:
                target[field] = text

    def render_note_md(self, record: dict, claims: list[dict]) -> str:
        title = str(record.get("title") or record.get("id") or "")
        by_id = {str(claim.get("id") or ""): claim for claim in claims}
        lines = [f"# {title}", "", *self.spec.note_intro, ""]
        for name in self.spec.note_elements:
            lines.extend([f"## {self.spec.element_headings[name]}", ""])
            claim = by_id.get(f"claim-{name}")
            content = clean_text(str(claim.get("text") or "")) if claim else ""
            lines.extend([content or "-", ""])
            refs = (claim.get("evidence_refs") if claim else None) or []
            if refs:
                lines.append("证据：")
                for ref in refs:
                    if not isinstance(ref, dict):
                        continue
                    locator = str(ref.get("locator") or "?")
                    quote = clean_text(str(ref.get("quote") or ""))
                    summary = clean_text(str(ref.get("summary") or ""))
                    suffix = f" — {summary}" if summary else ""
                    lines.append(f'- [{locator}] "{quote}"{suffix}')
                lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def finalize_post_actions(
        self,
        root: Path,
        *,
        trigger: str,
        message: str,
        defer_post_actions: bool,
        target_paths: Sequence[Path],
    ) -> dict[str, Any]:
        if defer_post_actions:
            return {"committed": False, "status": "deferred"}
        index_paths = build_index(root)
        all_targets = [
            *target_paths,
            *index_paths,
            topic_taxonomy_path(root),
            candidate_pools_path(root),
        ]
        if self._active_mutation.get():
            self._pending_checkpoint.set((root, trigger, message, all_targets))
            return {"committed": False, "status": "pending-transaction-commit"}
        return self._checkpoint(
            root,
            trigger=trigger,
            message=message,
            target_paths=all_targets,
        )

    @staticmethod
    def resolve_fill_input(
        unit_root: Path,
        default_name: str,
        explicit: str | None,
    ) -> Path:
        if explicit:
            candidate = Path(explicit).expanduser()
            if not candidate.is_absolute():
                candidate = unit_root / explicit
            return candidate
        return unit_root / default_name

    @staticmethod
    def unit_owned_fill_path(unit_root: Path, fill_path: Path) -> Path | None:
        try:
            fill_path.resolve().relative_to(unit_root.resolve())
        except (OSError, ValueError):
            return None
        return fill_path

    def next_for_agent_note(
        self,
        root: Path,
        record: dict,
        cache_path: Path,
        fill_path: Path,
    ) -> str:
        elements = ",".join(self.spec.note_elements)
        verify_cmd = (
            f"${{RESEARCH_PYTHON:-python3}} {self.script_path} --root {root} "
            f"{self.spec.command} {self.spec.id_option} {record['id']} "
            f"--phase verify --input {fill_path.name}"
        )
        read_hint = rel(root, cache_path) if cache_path.exists() else "parse-cache.yaml"
        return (
            f"NEXT FOR AGENT: read {read_hint} (source quotes) then fill {rel(root, fill_path)} "
            f"elements [{elements}] — each needs content + >=1 verbatim quote+locator "
            f"(HTML section / section:<anchor>), then run: {verify_cmd}"
        )

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description=self.spec.parser_description)
        add_project_root_argument(parser)
        subparsers = parser.add_subparsers(dest="command", required=True)

        note = subparsers.add_parser(self.spec.command)
        note.add_argument(self.spec.id_option, required=True)
        note.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
        note.add_argument("--input", default="")
        note.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)
        note.add_argument("--defer-post-actions", action="store_true")

        confirm = subparsers.add_parser("confirm")
        confirm.add_argument(self.spec.id_option, required=True)
        self.add_confirmation_arguments(confirm)
        confirm.add_argument("--defer-post-actions", action="store_true")
        return parser

    def _note_targets(
        self,
        args: argparse.Namespace,
        root: Path,
        unit_root: Path,
        defer_post_actions: bool,
    ) -> list[Path]:
        targets = [
            unit_root / "record.yaml",
            unit_root / self.spec.fill_name,
            *(
                [unit_root / self.spec.preference_orientation_name]
                if args.phase == "prepare"
                else []
            ),
            unit_root / self.spec.note_name,
            unit_root / self.spec.claims_name,
        ]
        if not defer_post_actions:
            targets.extend(self.index_targets(root))
        return targets

    def run_note(
        self,
        args: argparse.Namespace,
        root: Path,
        record: dict,
        unit_root: Path,
        defer_post_actions: bool,
    ) -> int:
        return self._transaction(
            self.spec.command,
            root,
            self._note_targets(args, root, unit_root, defer_post_actions),
            lambda: self._run_note_body(
                args,
                root,
                record,
                unit_root,
                defer_post_actions,
            ),
        )

    def _run_note_body(
        self,
        args: argparse.Namespace,
        root: Path,
        record: dict,
        unit_root: Path,
        defer_post_actions: bool,
    ) -> int:
        spec = self.spec
        fill_scaffold_path = unit_root / spec.fill_name
        note_path = unit_root / spec.note_name
        cache_path = self.cache_path(unit_root)

        if args.phase == "prepare":
            source_chunks, _locator_kind = self.load_cache_chunks(unit_root)
            payload = self.build_note_scaffold(
                record,
                source_chunks,
                digest_chunks=12,
                digest_chars=1200,
            )
            write_yaml_if_changed(fill_scaffold_path, payload)
            orientation_path = unit_root / spec.preference_orientation_name
            write_yaml_if_changed(orientation_path, self.preference_orientation(record))
            record["maturity"] = "complete"
            record["confirmation_status"] = "pending_user_confirmation"
            record["needs_human_confirmation"] = True
            record["information_types"] = [
                "fact",
                "inference",
                "evaluation",
                "unverified",
            ]
            record["payload"].setdefault("state", {})[
                spec.state_field
            ] = "awaiting_agent_fill"
            append_history(
                record,
                action=spec.prepare_history_action,
                summary=spec.prepare_history_summary,
                information_types=["inference", "unverified"],
                artifacts=[
                    rel(root, fill_scaffold_path),
                    rel(root, orientation_path),
                    rel(root, cache_path),
                ],
            )
            write_record(root, record)
            preference_task_context = self.preference_context(root, record, unit_root)
            payload = self.build_note_scaffold(
                record,
                source_chunks,
                digest_chunks=12,
                digest_chars=1200,
                preference_task_context=preference_task_context,
            )
            write_yaml_if_changed(fill_scaffold_path, payload)
            print(f"[ok] wrote {fill_scaffold_path.relative_to(root)}")
            print(spec.prepare_guidance)
            print(self.next_for_agent_note(root, record, cache_path, fill_scaffold_path))
            self.finalize_post_actions(
                root,
                trigger="milestone",
                message=spec.scaffold_checkpoint_message.format(id=record["id"]),
                defer_post_actions=defer_post_actions,
                target_paths=[
                    unit_root / "record.yaml",
                    orientation_path,
                    fill_scaffold_path,
                ],
            )
            return 0

        fill_path = self.resolve_fill_input(unit_root, spec.fill_name, args.input)
        if not fill_path.exists():
            raise SystemExit(
                f"{spec.command} --phase verify: fill input not found: {fill_path}"
            )
        fill = load_yaml(fill_path, default={})
        if not isinstance(fill, dict):
            raise SystemExit(
                f"{spec.command} --phase verify: {fill_path} is not a mapping"
            )
        preference_selection_id = str(
            getattr(args, "preference_selection_id", "") or ""
        )
        try:
            preferences = self.resolve_preferences(
                root,
                record,
                unit_root,
                selection_id=preference_selection_id,
            )
        except ValueError as exc:
            print(
                f"[reject] {spec.preference_label} preference receipt: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        violations, claims = self.verify_note_fill(fill, unit_root)
        if violations:
            print(
                f"[reject] {spec.preference_label} fill failed verification:",
                file=sys.stderr,
            )
            for violation in violations:
                print(f"  - {violation}", file=sys.stderr)
            raise SystemExit(1)

        try:
            rechecked_preferences = self.resolve_preferences(
                root,
                record,
                unit_root,
                selection_id=preference_selection_id,
            )
        except ValueError as exc:
            print(
                f"[reject] {spec.preference_label} preference receipt: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        if (
            rechecked_preferences.get("task_context_digest")
            != preferences.get("task_context_digest")
            or rechecked_preferences.get("binding") != preferences.get("binding")
        ):
            print(
                f"[reject] {spec.preference_label} task context changed before write",
                file=sys.stderr,
            )
            raise SystemExit(1)

        self.apply_note_fill_to_payload(record, claims)
        self.persist_preference_binding(
            record,
            dict(preferences.get("binding") or {}),
        )
        attach_claims(record.setdefault("payload", {}), claims)
        build_verification_receipt(record, unit_root)
        write_text_if_changed(note_path, self.render_note_md(record, claims))
        note_payload = {spec.id_key: record["id"], "kind": spec.kind}
        attach_claims(note_payload, claims)
        write_yaml_if_changed(unit_root / spec.claims_name, note_payload)
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = [
            "fact",
            "inference",
            "evaluation",
            "unverified",
        ]
        record["payload"].setdefault("state", {})[
            spec.state_field
        ] = "pending_user_confirmation"
        append_history(
            record,
            action=spec.verify_history_action,
            summary=spec.verify_history_summary,
            information_types=["inference", "evaluation", "unverified"],
            artifacts=(
                [rel(root, note_path), rel(root, cache_path)]
                if cache_path.exists()
                else [rel(root, note_path)]
            ),
        )
        write_record(root, record)
        print(
            f"[ok] verified + wrote {note_path.relative_to(root)} "
            f"(content filled, {len(claims)} elements)"
        )
        note_targets = [
            unit_root / "record.yaml",
            note_path,
            unit_root / spec.claims_name,
        ]
        owned_fill = self.unit_owned_fill_path(unit_root, fill_path)
        if owned_fill is not None:
            note_targets.insert(1, owned_fill)
        self.finalize_post_actions(
            root,
            trigger="milestone",
            message=spec.verify_checkpoint_message.format(id=record["id"]),
            defer_post_actions=defer_post_actions,
            target_paths=note_targets,
        )
        return 0

    def run_confirm(
        self,
        args: argparse.Namespace,
        root: Path,
        record: dict,
        unit_root: Path,
        defer_post_actions: bool,
    ) -> int:
        targets = [unit_root / "record.yaml"]
        if not defer_post_actions:
            targets.extend(self.index_targets(root))
        return self._transaction(
            "confirm",
            root,
            targets,
            lambda: self._run_confirm_body(
                args,
                root,
                record,
                unit_root,
                defer_post_actions,
            ),
        )

    def _run_confirm_body(
        self,
        args: argparse.Namespace,
        root: Path,
        record: dict,
        unit_root: Path,
        defer_post_actions: bool,
    ) -> int:
        unit_id = str(getattr(args, self.spec.id_dest))
        expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
        record = confirm_unit(
            record,
            self.spec.kind,
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            method=f"{self.script_path.name} confirm",
            project_root=root,
            expected_record_snapshot=expected_record_snapshot,
        )
        write_record(root, record, expected_record_snapshot=expected_record_snapshot)
        print(f"[ok] confirmed {unit_id}")
        self.finalize_post_actions(
            root,
            trigger="milestone",
            message=self.spec.confirm_checkpoint_message.format(id=unit_id),
            defer_post_actions=defer_post_actions,
            target_paths=[unit_root / "record.yaml"],
        )
        return 0

    def main(self) -> int:
        args = self.build_parser().parse_args()
        root = project_root(self.default_project_root, explicit_root=args.root)
        print_resolved_project_roots(root)
        unit_id = str(getattr(args, self.spec.id_dest))
        record, path = locate_record(root, unit_id, kind=self.spec.kind)
        if record.get("kind") != self.spec.kind:
            raise SystemExit(f"{unit_id} is not a {self.spec.kind} record")
        unit_root = path.parent
        defer_post_actions = bool(getattr(args, "defer_post_actions", False))
        if args.command == self.spec.command:
            return self.run_note(
                args,
                root,
                record,
                unit_root,
                defer_post_actions,
            )
        if args.command == "confirm":
            return self.run_confirm(
                args,
                root,
                record,
                unit_root,
                defer_post_actions,
            )
        return 1
