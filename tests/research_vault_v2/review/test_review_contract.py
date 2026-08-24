from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "skills" / "research-review"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
VALID = FIXTURES / "valid"
NOTE = VALID / "Notes" / "anydoc-adapter-assessment.md"
REVIEW = VALID / "Reviews" / "review-anydoc-c001.md"
BINDING = VALID / ".research" / "evidence" / "binding-anydoc-e001.json"
RECEIPT = VALID / ".research" / "receipts" / "receipt-anydoc-c001.json"
MANIFEST = VALID / "Sources" / "src-anydoc" / ".source" / "manifest.json"
READER = VALID / "Sources" / "src-anydoc" / "reader.md"
SOURCE_MAP = (
    VALID
    / "Sources"
    / "src-anydoc"
    / ".source"
    / "revisions"
    / "rev-20260824-01"
    / "source-map.json"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalized_semantic_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _claim_block(markdown: str) -> tuple[str, str, str]:
    match = re.search(
        r"^### Claim (?P<claim_id>[A-Z]-\d+) — (?P<title>.+)$",
        markdown,
        flags=re.MULTILINE,
    )
    assert match is not None
    end = markdown.index("\n## Evidence", match.end())
    return match.group("claim_id"), match.group("title"), markdown[match.end() : end]


def _bullet(block: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", block, flags=re.MULTILINE)
    assert match is not None, label
    return match.group(1).strip().strip("`")


def _claim_payload(markdown: str) -> dict[str, str]:
    claim_id, title, block = _claim_block(markdown)
    prose = " ".join(
        line.strip()
        for line in block.splitlines()
        if line.strip() and not line.lstrip().startswith("-")
    )
    return {
        "schema": "research-claim-semantic/v1",
        "claim_id": claim_id,
        "text": _normalized_semantic_text(f"{title} {prose}"),
        "class": _normalized_semantic_text(_bullet(block, "Class")).casefold(),
        "scope": _normalized_semantic_text(_bullet(block, "Scope")),
        "limitations": _normalized_semantic_text(_bullet(block, "Limitations")),
    }


def _claim_digest(markdown: str) -> str:
    return _canonical_digest(_claim_payload(markdown))


def _claim_evidence_ids(markdown: str) -> list[str]:
    _claim_id, _title, block = _claim_block(markdown)
    return sorted(set(re.findall(r"\[([A-Z]-\d+)\]\(#evidence-[^)]+\)", block)))


def _evidence_payload(markdown: str) -> dict[str, Any]:
    section = markdown[markdown.index("\n## Evidence") :]
    heading = re.search(r"^### Evidence (?P<evidence_id>[A-Z]-\d+)$", section, re.MULTILINE)
    assert heading is not None
    quote_lines = [
        line[2:] if line.startswith("> ") else line[1:]
        for line in section[heading.end() :].splitlines()
        if line.startswith(">")
    ]
    quote = "\n".join(quote_lines)
    return {
        "schema": "research-visible-evidence/v1",
        "evidence_id": heading.group("evidence_id"),
        "exact_quote": quote,
        "source_id": _bullet(section, "Source ID"),
        "revision": _bullet(section, "Captured revision"),
        "locator": json.loads(_bullet(section, "Locator")),
    }


def _evidence_block_digest(markdown: str) -> str:
    return _canonical_digest(_evidence_payload(markdown))


def _evidence_set_digest(binding: dict[str, Any]) -> str:
    evidence = binding["evidence"]
    payload = {
        "schema": "research-evidence-set/v1",
        "items": [
            {
                "evidence_id": evidence["id"],
                "evidence_block_digest": evidence["block_digest"],
                "source_id": evidence["source_id"],
                "revision": evidence["revision"],
                "raw": evidence["raw"],
                "reader_digest": evidence["reader_digest"],
                "source_map_digest": evidence["source_map_digest"],
                "locator": evidence["locator"],
                "exact_quote_digest": evidence["quote_digest"],
                "integrity": binding["state"]["integrity"],
                "currency": binding["state"]["currency"],
            }
        ],
    }
    return _canonical_digest(payload)


ROLE_PLACEHOLDERS = {
    "me",
    "myself",
    "user",
    "human",
    "reviewer",
    "owner",
    "我",
    "本人",
    "用户",
    "人类",
}
AI_TOOL_TOKENS = {
    "ai",
    "assistant",
    "agent",
    "bot",
    "chatbot",
    "llm",
    "tool",
    "model",
    "codex",
    "chatgpt",
    "gpt",
    "openai",
    "anthropic",
    "gemini",
    "bard",
    "llama",
    "mistral",
    "cohere",
    "grok",
    "copilot",
    "qwen",
    "deepseek",
    "kimi",
    "devin",
    "cursor",
    "doubao",
    "tongyi",
}
MODEL_FAMILY_TOKENS = {"claude", "sonnet", "opus", "haiku", "fable"}
MODEL_VARIANTS = {
    "beta",
    "chat",
    "instant",
    "latest",
    "max",
    "mini",
    "preview",
    "pro",
    "reasoning",
    "thinking",
    "turbo",
}
LOCALIZED_AI_MARKERS = {
    "人工智能",
    "智能助手",
    "小助手",
    "机器人助理",
    "工具",
    "模型",
    "通义千问",
    "豆包",
    "文心一言",
    "讯飞星火",
    "智谱清言",
}


def _actor_is_allowed(actor: str) -> bool:
    normalized = " ".join(
        unicodedata.normalize("NFKC", str(actor or "")).strip().casefold().split()
    )
    if not normalized or normalized in ROLE_PLACEHOLDERS:
        return False
    if any(marker in normalized for marker in LOCALIZED_AI_MARKERS):
        return False
    tokens = re.findall(r"[a-z0-9]+", normalized)
    token_set = set(tokens)
    if token_set & AI_TOOL_TOKENS:
        return False
    model_tokens = token_set & MODEL_FAMILY_TOKENS
    if not model_tokens:
        return True
    possible_human_name_tokens = {
        token
        for token in token_set
        if token not in MODEL_FAMILY_TOKENS
        and token not in MODEL_VARIANTS
        and re.fullmatch(r"v?\d+", token) is None
    }
    return bool(possible_human_name_tokens)


def _case_is_authorized(case: dict[str, Any]) -> bool:
    return bool(
        case["role"] == "user"
        and case["authorization_source"] == "current_user_message"
        and case["review_id"] == "review-anydoc-c001"
        and case["decision"] in {"confirm", "reject", "defer"}
        and _actor_is_allowed(case["actor"])
    )


def _receipt_is_current(
    note_markdown: str,
    review_markdown: str,
    binding: dict[str, Any],
    receipt: dict[str, Any],
) -> bool:
    evidence = binding["evidence"]
    manifest = _load_json(MANIFEST)
    revision = manifest["revisions"][0]
    raw_path = VALID / revision["raw"]["path"]
    visible_decision = {
        "confirm": ("status: confirmed", "- Review: confirmed", "Confirmed by"),
        "reject": ("status: rejected", "- Review: rejected", "Rejected by"),
        "defer": ("status: deferred", "- Review: deferred", "Deferred by"),
    }.get(receipt.get("decision"))
    return bool(
        receipt.get("schema") == "research-review-receipt/v1"
        and receipt.get("review_id") == "review-anydoc-c001"
        and receipt.get("subject")
        == {
            "path": binding["subject"]["path"],
            "claim_id": binding["subject"]["claim_id"],
        }
        and visible_decision is not None
        and visible_decision[0] in review_markdown
        and visible_decision[1] in note_markdown
        and visible_decision[2] in review_markdown
        and receipt.get("authorization_source") == "current_user_message"
        and _actor_is_allowed(str(receipt.get("actor_declaration") or ""))
        and _claim_digest(note_markdown) == binding["subject"]["claim_digest"]
        and receipt.get("claim_digest") == binding["subject"]["claim_digest"]
        and _claim_evidence_ids(note_markdown) == [evidence["id"]]
        and _evidence_block_digest(note_markdown) == evidence["block_digest"]
        and hashlib.sha256(evidence["exact_quote"].encode("utf-8")).hexdigest()
        == evidence["quote_digest"].removeprefix("sha256:")
        and binding["state"] == {"integrity": "verified", "currency": "current"}
        and revision["revision"] == evidence["revision"]
        and manifest["current_revision"] == evidence["revision"]
        and revision["raw"] == evidence["raw"]
        and _file_digest(raw_path) == evidence["raw"]["digest"]
        and _file_digest(READER) == evidence["reader_digest"]
        and _file_digest(SOURCE_MAP) == evidence["source_map_digest"]
        and receipt.get("evidence_set_digest") == _evidence_set_digest(binding)
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def test_skill_is_concise_and_exposes_both_contracts_one_hop() -> None:
    entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    expected = {
        "references/evidence-audit-and-packets.md",
        "references/authorization-decisions-and-receipts.md",
    }
    assert len(entry.splitlines()) < 100
    assert "protocol-reference-exempt:" in entry
    assert "scripts/" not in entry
    for relative in expected:
        assert f"]({relative})" in entry
        reference = SKILL_ROOT / relative
        assert reference.is_file()
        assert len(reference.read_text(encoding="utf-8").splitlines()) < 200

    combined = entry + "\n" + "\n".join(
        (SKILL_ROOT / relative).read_text(encoding="utf-8") for relative in sorted(expected)
    )
    for phrase in (
        "current_user_message",
        "confirm",
        "reject",
        "defer",
        "claim-block semantic digest",
        "evidence-set digest",
        "stale",
        "AI/tool",
        "普通 Markdown",
    ):
        assert phrase in combined

    metadata = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    interface = metadata["interface"]
    assert interface["display_name"] == "Research Review"
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$research-review" in interface["default_prompt"]


def test_visible_markdown_is_the_only_semantic_truth() -> None:
    note = NOTE.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    hidden_payloads = [_load_json(path) for path in sorted((VALID / ".research").rglob("*.json"))]
    hidden_keys = set().union(*(_all_keys(payload) for payload in hidden_payloads))

    assert "AnyDoc is suitable as an optional local conversion adapter" in note
    assert "AnyDoc is suitable as an optional local conversion adapter" in review
    assert "Fast Rust library that converts documents" in note
    assert "Fast Rust library that converts documents" in review
    assert "- Review: confirmed" in note
    assert "Confirmed by Lin Chen" in review
    assert hidden_keys.isdisjoint(
        {
            "claim_text",
            "summary",
            "scope",
            "limitations",
            "conflicts",
            "decision_rationale",
            "project_state",
            "review_status",
        }
    )


def test_valid_fixture_binds_claim_evidence_source_and_receipt_digests() -> None:
    note = NOTE.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    binding = _load_json(BINDING)
    receipt = _load_json(RECEIPT)
    manifest = _load_json(MANIFEST)
    evidence = _evidence_payload(note)
    revision = manifest["revisions"][0]

    assert binding["subject"]["claim_digest"] == _claim_digest(note)
    assert binding["evidence"]["block_digest"] == _evidence_block_digest(note)
    assert binding["evidence"]["exact_quote"] == evidence["exact_quote"]
    assert binding["evidence"]["locator"] == evidence["locator"]
    assert binding["evidence"]["revision"] == evidence["revision"]
    assert binding["evidence"]["quote_digest"] == "sha256:" + hashlib.sha256(
        evidence["exact_quote"].encode("utf-8")
    ).hexdigest()

    raw_path = VALID / revision["raw"]["path"]
    assert revision["raw"]["digest"] == _file_digest(raw_path)
    assert revision["reader_digest"] == _file_digest(READER)
    assert revision["source_map_digest"] == _file_digest(SOURCE_MAP)
    assert binding["evidence"]["raw"] == revision["raw"]
    assert binding["evidence"]["reader_digest"] == revision["reader_digest"]
    assert binding["evidence"]["source_map_digest"] == revision["source_map_digest"]
    assert evidence["exact_quote"] in raw_path.read_text(encoding="utf-8")
    assert evidence["exact_quote"] in READER.read_text(encoding="utf-8")

    assert receipt["claim_digest"] == _claim_digest(note)
    assert receipt["evidence_set_digest"] == _evidence_set_digest(binding)
    assert receipt["claim_digest"] in review
    assert receipt["evidence_set_digest"] in review
    assert evidence["revision"] in review
    assert json.dumps(evidence["locator"], separators=(",", ":")) in review
    assert _receipt_is_current(note, review, binding, receipt)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("AnyDoc covers several", "AnyDoc only covers several"),
        ("- Class: evaluation", "- Class: recommendation"),
        ("Office-family documents", "PDF documents"),
        ("Conversion success alone", "Conversion output alone"),
    ],
)
def test_claim_semantic_mutation_makes_receipt_stale(old: str, new: str) -> None:
    note = NOTE.read_text(encoding="utf-8")
    mutated = note.replace(old, new, 1)
    binding = _load_json(BINDING)
    receipt = _load_json(RECEIPT)

    assert _claim_digest(mutated) != receipt["claim_digest"]
    assert not _receipt_is_current(mutated, REVIEW.read_text(encoding="utf-8"), binding, receipt)


def test_unrelated_markdown_formatting_does_not_invalidate_claim_receipt() -> None:
    note = NOTE.read_text(encoding="utf-8")
    reformatted = note.replace("# AnyDoc adapter assessment", "# AnyDoc adapter assessment\n\nIntroductory navigation only.")

    assert _claim_digest(reformatted) == _claim_digest(note)
    assert _receipt_is_current(
        reformatted,
        REVIEW.read_text(encoding="utf-8"),
        _load_json(BINDING),
        _load_json(RECEIPT),
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Fast Rust library", "Fast local library"),
        ("\"heading\":\"Supported Formats\"", "\"heading\":\"Other Formats\""),
        ("rev-20260824-01", "rev-20260824-02"),
        ("[E-001](#evidence-e-001)", "[E-001](#evidence-e-001), [E-002](#evidence-e-002)"),
    ],
)
def test_evidence_mutation_or_membership_change_makes_receipt_stale(old: str, new: str) -> None:
    note = NOTE.read_text(encoding="utf-8")
    mutated = note.replace(old, new, 1)

    assert not _receipt_is_current(
        mutated,
        REVIEW.read_text(encoding="utf-8"),
        _load_json(BINDING),
        _load_json(RECEIPT),
    )


def test_binding_currency_change_changes_evidence_set_and_fails_closed() -> None:
    binding = _load_json(BINDING)
    stale_binding = copy.deepcopy(binding)
    stale_binding["state"]["currency"] = "stale"
    receipt = _load_json(RECEIPT)

    assert _evidence_set_digest(stale_binding) != receipt["evidence_set_digest"]
    assert not _receipt_is_current(
        NOTE.read_text(encoding="utf-8"),
        REVIEW.read_text(encoding="utf-8"),
        stale_binding,
        receipt,
    )


def test_authorization_cases_require_current_user_scope_and_non_ai_signer() -> None:
    cases = _load_json(FIXTURES / "authorization-cases.json")
    observed = {case["id"]: _case_is_authorized(case) for case in cases}
    expected = {case["id"]: case["expected"] for case in cases}

    assert observed == expected
    assert {case["decision"] for case in cases if case["expected"]} == {
        "confirm",
        "reject",
        "defer",
    }
    assert _actor_is_allowed("Claude Martin")
    for actor in ("Claude Fable", "Sonnet latest", "Kimi", "Research Review Tool", "人工智能助手"):
        assert not _actor_is_allowed(actor)


@pytest.mark.parametrize(
    ("decision", "audit", "substantive", "evidence_count", "expected"),
    [
        ("confirm", "pass", True, 1, True),
        ("confirm", "pass-with-limitations", True, 1, True),
        ("confirm", "stale", True, 1, False),
        ("confirm", "pass", False, 1, False),
        ("confirm", "pass", True, 0, False),
        ("reject", "invalid", True, 0, True),
        ("defer", "blocked", True, 0, True),
    ],
)
def test_confirm_reject_and_defer_keep_distinct_gates(
    decision: str,
    audit: str,
    substantive: bool,
    evidence_count: int,
    expected: bool,
) -> None:
    allowed = decision in {"reject", "defer"} or bool(
        decision == "confirm"
        and audit in {"pass", "pass-with-limitations"}
        and substantive
        and evidence_count > 0
    )
    assert allowed is expected


def test_tampered_authorization_or_visible_decision_invalidates_receipt() -> None:
    note = NOTE.read_text(encoding="utf-8")
    review = REVIEW.read_text(encoding="utf-8")
    binding = _load_json(BINDING)
    receipt = _load_json(RECEIPT)

    stale_auth = copy.deepcopy(receipt)
    stale_auth["authorization_source"] = "prior_user_message"
    assert not _receipt_is_current(note, review, binding, stale_auth)

    ai_signed = copy.deepcopy(receipt)
    ai_signed["actor_declaration"] = "GPT-5 Assistant"
    assert not _receipt_is_current(note, review, binding, ai_signed)

    visible_reject = review.replace("status: confirmed", "status: rejected", 1)
    assert not _receipt_is_current(note, visible_reject, binding, receipt)
