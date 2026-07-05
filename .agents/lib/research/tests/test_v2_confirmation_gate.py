from __future__ import annotations

import pytest

from research.v2 import _record_needs_gate, normalize_record_schema, validate_write


def test_record_needs_gate_ignores_plain_source_facts() -> None:
    record = {
        "id": "p-clean-123456",
        "information_types": ["fact"],
        "source": {"kind": "paper"},
    }

    assert _record_needs_gate(record) == (False, set(), False)
    assert validate_write(record, strict=True) == []


def test_validate_write_warns_for_too_strong_ai_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    record = {
        "id": "p-ai-123456",
        "information_types": ["evaluation"],
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": True,
    }

    violations = validate_write(record, strict=False)

    assert len(violations) == 1
    assert "confirmation_status='auto_confirmed'" in violations[0]
    assert "evaluation" in violations[0]
    assert "WARN" in capsys.readouterr().err


def test_validate_write_requires_needs_human_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    record = {
        "id": "p-ai-123456",
        "information_types": ["inference"],
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": False,
    }

    violations = validate_write(record, strict=False)

    assert len(violations) == 1
    assert "needs_human_confirmation must be true" in violations[0]
    assert "WARN" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("confirmation_status", "information_types", "source", "expected"),
    [
        pytest.param("pending_user_confirmation", ["inference"], {}, True, id="ai-info-pending"),
        pytest.param("rejected", ["evaluation"], {}, True, id="ai-info-rejected"),
        pytest.param("pending_user_confirmation", ["fact"], {"kind": "ai"}, True, id="ai-source-pending"),
        pytest.param("auto_confirmed", ["evaluation"], {}, True, id="ai-info-auto-invalid"),
        pytest.param("pending_user_confirmation", ["fact"], {}, False, id="non-ai-pending"),
        pytest.param("auto_confirmed", ["fact"], {}, False, id="non-ai-auto"),
        pytest.param("confirmed", ["evaluation"], {}, False, id="confirmed-final"),
        pytest.param("rejected", ["fact"], {}, False, id="non-ai-rejected"),
    ],
)
def test_normalize_record_schema_syncs_needs_human_confirmation(
    confirmation_status: str,
    information_types: list[str],
    source: dict[str, str],
    expected: bool,
) -> None:
    normalized = normalize_record_schema(
        {
            "kind": "paper",
            "title": "Schema Sync",
            "maturity": "lightweight",
            "source": source,
            "information_types": information_types,
            "confirmation_status": confirmation_status,
            "needs_human_confirmation": not expected,
        }
    )

    assert normalized["needs_human_confirmation"] is expected


def test_normalize_record_schema_strips_backup_warning_from_source() -> None:
    normalized = normalize_record_schema(
        {
            "kind": "paper",
            "title": "Backup Warning",
            "maturity": "lightweight",
            "source": {
                "original_uri": "https://example.com/source.pdf",
                "backup_paths": ["kb/units/papers/p-backup-123456/source/source-url.txt"],
                "backup_kind": "url",
                "file_hash": "",
                "backup_warning": "URL source was not archived as a text snapshot.",
            },
            "information_types": ["fact"],
        }
    )

    assert "backup_warning" not in normalized["source"]


@pytest.mark.parametrize("confirmation_status", ["pending_user_confirmation", "rejected"])
def test_normalize_then_validate_write_accepts_ai_pending_and_rejected(
    confirmation_status: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    normalized = normalize_record_schema(
        {
            "kind": "paper",
            "title": "AI Round Trip",
            "maturity": "lightweight",
            "information_types": ["evaluation"],
            "confirmation_status": confirmation_status,
            "needs_human_confirmation": False,
        }
    )

    assert normalized["needs_human_confirmation"] is True
    assert validate_write(normalized, strict=False) == []
    assert capsys.readouterr().err == ""
    assert validate_write(normalized, strict=True) == []


def test_validate_write_accepts_pending_ai_record(capsys: pytest.CaptureFixture[str]) -> None:
    record = {
        "id": "p-ai-123456",
        "information_types": ["user_opinion"],
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
    }

    assert validate_write(record, strict=True) == []
    assert capsys.readouterr().err == ""


def test_validate_write_strict_raises_for_ai_source() -> None:
    record = {
        "id": "p-ai-source-123456",
        "information_types": ["fact"],
        "source": {"kind": "ai"},
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
    }

    with pytest.raises(SystemExit) as excinfo:
        validate_write(record, strict=True)

    message = str(excinfo.value)
    assert "source.kind=ai" in message
    assert "needs_human_confirmation" in message
