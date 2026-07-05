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
    ("confirmation_status", "expected"),
    [
        ("pending_user_confirmation", True),
        ("auto_confirmed", False),
        ("confirmed", False),
        ("rejected", False),
    ],
)
def test_normalize_record_schema_syncs_needs_human_confirmation(confirmation_status: str, expected: bool) -> None:
    normalized = normalize_record_schema(
        {
            "kind": "paper",
            "title": "Schema Sync",
            "maturity": "lightweight",
            "confirmation_status": confirmation_status,
            "needs_human_confirmation": not expected,
        }
    )

    assert normalized["needs_human_confirmation"] is expected


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
