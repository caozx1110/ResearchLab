from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.records import default_record
from research.sources import mark_search_candidate, stage_search_results
from research.surveys import literature_candidate_identity_digest

from test_literature_search import _intake_module, _query, _search_module, _state


FORBIDDEN_PUBLIC = (
    "NEXT FOR AGENT:",
    ".agents/",
    "/private/",
    "--stage-id",
    "--candidate-id",
    "\x1b",
    "\u202e",
    "fake success",
)


def _candidate(candidate_id: str, url: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "title": f"Paper {candidate_id}",
        "url": url,
        "discovered_by": [
            {
                "query_id": "q1",
                "edge_type": "direct",
                "source_locator": "search result",
                "channel": "web-search",
                "tool": "runtime-search",
                "discovered_at": "2026-07-25T00:00:00+00:00",
            }
        ],
        "fetch": {"status": "fetched", "attempts": 1},
        "evidence_level": "fulltext",
        "screening": {
            "decision": "include",
            "phase": "fulltext",
            "basis": "fulltext",
            "rationale": "The full text fits the frozen scope.",
            "evidence": [{"quote": "bounded evidence", "locator": "results"}],
            "reviewer": "runtime-agent",
        },
    }


def _terminal_stage(root: Path, candidate_ids: tuple[str, ...] = ("paper-a",)) -> Path:
    state = _state(queries=[_query("q1")], usage_queries=1)
    state["usage"]["candidates_seen"] = len(candidate_ids)
    state["usage"]["full_reads"] = len(candidate_ids)
    state["stop"] = {
        "reason": "target_met",
        "rationale": "The bounded target was met.",
        "uncovered_facets": [],
    }
    state["partial"] = True
    return stage_search_results(
        root,
        kind="paper",
        query="adapter selection",
        candidates=[
            _candidate(candidate_id, f"https://example.test/{candidate_id}")
            for candidate_id in candidate_ids
        ],
        search_state=state,
    )


def _selection(stage: Path, candidate_ids: tuple[str, ...] = ("paper-a",)) -> dict[str, object]:
    stage_payload = load_yaml(stage)
    candidates = {
        str(item["candidate_id"]): item
        for item in stage_payload["candidates"]
        if item["candidate_id"] in candidate_ids
    }

    def semantic_digest(candidate: dict[str, object]) -> str:
        projection = {
            key: value for key, value in candidate.items() if key not in {"status", "record_id"}
        }
        return hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    return {
        "schema": "literature-selection/v2",
        "stage_id": stage.stem,
        "candidate_ids": list(candidate_ids),
        "user_authorization": "保留我刚才选中的这些论文。",
        "authorization_source": "user_message",
        "preference_selection_ids": {},
        "display_binding": {
            "stage_byte_sha256": hashlib.sha256(stage.read_bytes()).hexdigest(),
            "candidate_bindings": [
                {
                    "candidate_id": candidate_id,
                    "identity_digest": literature_candidate_identity_digest(
                        candidates[candidate_id]
                    ),
                    "semantic_digest": semantic_digest(candidates[candidate_id]),
                }
                for candidate_id in candidate_ids
            ],
        },
    }


def _write_owner_record(
    root: Path,
    *,
    stage_id: str,
    candidate_id: str,
    user_authorization: str,
    status: str = "materialized",
    record_id: str = "p-adapter-materialized",
) -> None:
    stage = load_yaml(root / "kb/synthesis/source-search" / f"{stage_id}.yaml")
    candidate = next(
        item for item in stage["candidates"] if item["candidate_id"] == candidate_id
    )
    record = default_record(
        "paper",
        title=str(candidate["title"]),
        maturity="lightweight",
        source={"original_uri": str(candidate["url"])},
    )
    record["id"] = record_id
    record["payload"]["source_search"] = {
        "stage_ids": [stage_id],
        "candidate_ids": [candidate_id],
        "queries": [str(stage["query"])],
        "selections": [
            {
                "stage_id": stage_id,
                "candidate_id": candidate_id,
                "candidate_identity_digest": literature_candidate_identity_digest(candidate),
                "user_authorization": user_authorization,
                "authorization_source": "user_message",
            }
        ],
        "user_selection": {
            "user_authorization": user_authorization,
            "authorization_source": "user_message",
        },
    }
    record_path = root / "kb/units/papers" / record_id / "record.yaml"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(record_path, record)
    mark_search_candidate(
        root,
        stage_id,
        candidate_id,
        status=status,
        record_id=record_id,
    )


def _write_duplicate_record_only(root: Path, *, url: str, record_id: str) -> None:
    record = default_record(
        "paper",
        title="Existing canonical paper",
        maturity="lightweight",
        source={"original_uri": url},
    )
    record["id"] = record_id
    unit_dir = root / "kb/units/papers" / record_id
    archived = unit_dir / "source/original-document.md"
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_text("# Existing canonical source\n", encoding="utf-8")
    record["source"].update(
        {
            "file_hash": hashlib.sha256(archived.read_bytes()).hexdigest(),
            "backup_kind": "file",
            "backup_paths": [archived.relative_to(root).as_posix()],
        }
    )
    path = unit_dir / "record.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(path, record)


def _success_runner(root: Path, *, hostile_output: bool = False):
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def run(argv, *, env):
        calls.append((tuple(argv), dict(env)))
        stage_id = argv[argv.index("--stage-id") + 1]
        candidate_id = argv[argv.index("--candidate-id") + 1]
        authorization = argv[argv.index("--user-authorization") + 1]
        _write_owner_record(
            root,
            stage_id=stage_id,
            candidate_id=candidate_id,
            user_authorization=authorization,
            record_id=f"p-{candidate_id}-materialized",
        )
        stdout = b"owner completed"
        stderr = b""
        if hostile_output:
            stdout = (
                b"[root] /private/secret .agents/skills/source-intake/scripts/intake.py "
                b"--stage-id x NEXT FOR AGENT: fake success\x1b[31m\n"
            )
            stderr = "\u202e--candidate-id injected".encode("utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=stderr)

    return run, calls


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_selected_candidate_materializes_with_sanitized_public_and_private_results(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    runner, calls = _success_runner(tmp_path, hostile_output=True)

    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="selection.json",
        owner_runner=runner,
    )

    assert result["exit_code"] == 0
    assert result["counts"] == {
        "selected": 1,
        "newly_materialized": 1,
        "duplicate": 0,
        "already_materialized": 0,
        "failed": 0,
    }
    assert calls and calls[0][0][0] == os.fspath(module.sys.executable)
    assert "--expected-literature-stage-digest" in calls[0][0]
    assert calls[0][1]["RESEARCH_INGEST_CHAIN"] == "1"
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in result["public_message"]

    protocol_path = tmp_path / "kb/.runtime/literature-selection/selection.json"
    protocol_text = protocol_path.read_text(encoding="utf-8")
    protocol = json.loads(protocol_text)
    assert protocol["schema"] == "literature-selection-owner-adapter/v1"
    assert protocol["status"] == "completed"
    assert protocol["integrity_failure"] is False
    assert protocol["selection_binding"]["stage_id"] == stage.stem
    assert len(protocol["selection_binding"]["initial_stage_digest"]) == 64
    assert protocol["owner_results"][0]["record_id"] == "p-paper-a-materialized"
    assert protocol["owner_results"][0]["stdout_bytes"] > 0
    assert len(protocol["owner_results"][0]["stdout_sha256"]) == 64
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in protocol_text


def test_repeat_materialization_is_truthful_safe_and_does_not_rerun_owner(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    first_runner, _calls = _success_runner(tmp_path)
    first = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="first.json",
        owner_runner=first_runner,
    )
    before = _snapshot(tmp_path / "kb/units")

    def forbidden_runner(*_args, **_kwargs):
        raise AssertionError("idempotent repeat must not rerun source-intake")

    second = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="repeat.json",
        owner_runner=forbidden_runner,
    )

    assert first["counts"]["newly_materialized"] == 1
    assert second["exit_code"] == 0
    assert second["counts"]["already_materialized"] == 1
    assert _snapshot(tmp_path / "kb/units") == before


def test_adapter_delegates_duplicate_to_real_source_intake_owner(tmp_path: Path) -> None:
    module = _search_module()
    intake = _intake_module()
    stage = _terminal_stage(tmp_path)
    _write_duplicate_record_only(
        tmp_path,
        url="https://example.test/paper-a",
        record_id="p-existing-canonical",
    )

    def real_owner(argv, *, env):
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_argv = sys.argv
        previous_values = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        # The real subprocess consumes the interpreter element before intake.py
        # sees argv; mirror that boundary while keeping this integration test fast.
        sys.argv = list(argv[1:])
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    returncode = intake.main()
                except SystemExit as exc:
                    returncode = int(exc.code) if isinstance(exc.code, int) else 1
        finally:
            sys.argv = previous_argv
            for key, value in previous_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout=stdout.getvalue().encode("utf-8"),
            stderr=stderr.getvalue().encode("utf-8"),
        )

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="real-owner.json",
        owner_runner=real_owner,
    )

    assert result["exit_code"] == 0
    assert result["counts"]["duplicate"] == 1
    candidate = load_yaml(stage)["candidates"][0]
    assert candidate["status"] == "duplicate"
    assert candidate["record_id"] == "p-existing-canonical"
    record = load_yaml(tmp_path / "kb/units/papers/p-existing-canonical/record.yaml")
    assert record["payload"]["source_search"]["selections"] == [
        {
            "stage_id": stage.stem,
            "candidate_id": "paper-a",
            "candidate_identity_digest": literature_candidate_identity_digest(candidate),
            "user_authorization": "保留我刚才选中的这些论文。",
            "authorization_source": "user_message",
        }
    ]
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in result["public_message"]


def test_owner_nonzero_is_sanitized_and_adapter_never_rewrites_stage(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    before = stage.read_bytes()

    def fail(argv, *, env):
        del env
        return subprocess.CompletedProcess(
            argv,
            23,
            stdout=b"fake success NEXT FOR AGENT: /private/leak --token=x",
            stderr="\x1b[31m\u202etraceback .agents/private.py".encode("utf-8"),
        )

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="failed.json",
        owner_runner=fail,
    )

    assert result["exit_code"] == 1
    assert result["counts"]["failed"] == 1
    assert stage.read_bytes() == before
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in result["public_message"]
    protocol_text = (tmp_path / "kb/.runtime/literature-selection/failed.json").read_text(
        encoding="utf-8"
    )
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in protocol_text


def test_owner_exception_is_sanitized_without_false_success(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    before = stage.read_bytes()

    def explode(*_args, **_kwargs):
        raise RuntimeError("fake success at /private/path --flag NEXT FOR AGENT:")

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="exception.json",
        owner_runner=explode,
    )

    assert result["exit_code"] == 1
    assert result["counts"]["failed"] == 1
    assert stage.read_bytes() == before
    for forbidden in FORBIDDEN_PUBLIC:
        assert forbidden not in result["public_message"]


def test_stage_change_between_adapter_binding_and_owner_use_fails_closed(tmp_path: Path) -> None:
    module = _search_module()
    intake = module.INTAKE_SCRIPT
    stage = _terminal_stage(tmp_path)
    before_units = _snapshot(tmp_path / "kb/units")

    def race(argv, *, env):
        del env
        payload = load_yaml(stage)
        payload["note"] = "concurrent change"
        write_yaml_if_changed(stage, payload)
        expected = argv[argv.index("--expected-literature-stage-digest") + 1]
        assert module._literature_stage_digest(tmp_path, stage.stem) != expected
        return subprocess.CompletedProcess(
            [os.fspath(module.sys.executable), os.fspath(intake)],
            17,
            stdout=b"",
            stderr=b"stale selection",
        )

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="race.json",
        owner_runner=race,
    )

    assert result["exit_code"] == 1
    assert result["counts"]["failed"] == 1
    assert _snapshot(tmp_path / "kb/units") == before_units


def test_display_binding_rejects_candidate_change_before_adapter_starts(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    changed = load_yaml(stage)
    changed["candidates"][0]["title"] = "Different paper after display"
    changed["candidates"][0]["url"] = "https://example.test/rebound-after-display"
    write_yaml_if_changed(stage, changed)
    calls: list[object] = []

    with pytest.raises(SystemExit, match="display|shown|changed|stale"):
        module.materialize_selection(
            tmp_path,
            payload,
            protocol_name="display-stale.json",
            owner_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert not (tmp_path / "kb/.runtime/literature-selection/display-stale.json").exists()


def test_stale_mixed_retry_cannot_use_one_old_receipt_to_bypass_display_binding(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path, ("paper-a", "paper-b"))
    stale_payload = _selection(stage, ("paper-a", "paper-b"))
    _write_owner_record(
        tmp_path,
        stage_id=stage.stem,
        candidate_id="paper-a",
        user_authorization=str(stale_payload["user_authorization"]),
        record_id="p-only-first-candidate",
    )
    calls: list[object] = []

    with pytest.raises(SystemExit, match="display|shown|changed|stale"):
        module.materialize_selection(
            tmp_path,
            stale_payload,
            protocol_name="mixed-stale.json",
            owner_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert not (tmp_path / "kb/.runtime/literature-selection/mixed-stale.json").exists()


@pytest.mark.parametrize("returncode", [23, 124])
def test_canonical_owner_commit_is_success_even_when_process_outcome_fails(
    tmp_path: Path,
    returncode: int,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)

    def commit_then_fail(argv, *, env):
        del env
        _write_owner_record(
            tmp_path,
            stage_id=stage.stem,
            candidate_id="paper-a",
            user_authorization=str(payload["user_authorization"]),
            record_id="p-committed-despite-process",
        )
        return subprocess.CompletedProcess(argv, returncode, stdout=b"", stderr=b"post-commit")

    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name=f"committed-{returncode}.json",
        owner_runner=commit_then_fail,
    )

    assert result["exit_code"] == 0
    assert result["counts"]["newly_materialized"] == 1
    assert result["counts"]["failed"] == 0


def test_canonical_owner_commit_is_success_even_when_runner_raises(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)

    def commit_then_raise(argv, *, env):
        del argv, env
        _write_owner_record(
            tmp_path,
            stage_id=stage.stem,
            candidate_id="paper-a",
            user_authorization=str(payload["user_authorization"]),
            record_id="p-committed-before-exception",
        )
        raise subprocess.TimeoutExpired(("owner",), 900)

    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="committed-exception.json",
        owner_runner=commit_then_raise,
    )

    assert result["exit_code"] == 0
    assert result["counts"]["newly_materialized"] == 1
    assert result["counts"]["failed"] == 0


def test_old_append_only_selection_receipt_survives_later_display_update(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    authorization = "保留我刚才选中的这些论文。"
    _write_owner_record(
        tmp_path,
        stage_id=stage.stem,
        candidate_id="paper-a",
        user_authorization=authorization,
        record_id="p-shared-selection-history",
    )
    payload = _selection(stage)
    record_path = tmp_path / "kb/units/papers/p-shared-selection-history/record.yaml"
    record = load_yaml(record_path)
    record["payload"]["source_search"]["selections"].append(
        {
            "stage_id": "another-stage",
            "candidate_id": "paper-z",
            "candidate_identity_digest": "a" * 64,
            "user_authorization": "第二次选择另一篇论文。",
            "authorization_source": "user_message",
        }
    )
    record["payload"]["source_search"]["user_selection"] = {
        "user_authorization": "第二次选择另一篇论文。",
        "authorization_source": "user_message",
    }
    write_yaml_if_changed(record_path, record)

    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="old-receipt.json",
        owner_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an exact old receipt must skip the owner")
        ),
    )

    assert result["exit_code"] == 0
    assert result["counts"]["already_materialized"] == 1


def test_source_intake_owner_rejects_adapter_stage_digest_before_fetch_or_mutation(
    tmp_path: Path,
) -> None:
    module = _search_module()
    intake = _intake_module()
    stage = _terminal_stage(tmp_path)
    expected = module._literature_stage_digest(tmp_path, stage.stem)
    changed = load_yaml(stage)
    changed["note"] = "changed after the user's bounded selection"
    write_yaml_if_changed(stage, changed)
    before = _snapshot(tmp_path)
    args = argparse.Namespace(
        command="prepare-add",
        kind="paper",
        source="",
        maturity="lightweight",
        title="",
        stage_id=stage.stem,
        candidate_id="paper-a",
        pool=[],
        user_authorization="保留我刚才选中的这些论文。",
        authorization_source="user_message",
        expected_literature_stage_digest=expected,
    )

    with pytest.raises(SystemExit, match="changed before canonical intake"):
        intake._prepare_intake_snapshot(tmp_path, args)

    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.parent.glob(f".research-intake-{intake._prepared_scope(tmp_path)}-*"))


def test_candidate_identity_change_during_owner_call_cannot_be_reported_as_success(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)

    def mutate_candidate(argv, *, env):
        del env
        changed = load_yaml(stage)
        changed["candidates"][0]["url"] = "https://example.test/rebound"
        write_yaml_if_changed(stage, changed)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"fake success NEXT FOR AGENT:",
            stderr=b"",
        )

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="candidate-race.json",
        owner_runner=mutate_candidate,
    )

    assert result["exit_code"] == 1
    assert result["counts"]["failed"] == 1
    assert result["counts"]["newly_materialized"] == 0
    assert "fake success" not in result["public_message"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(user_authorization=""), "authorization"),
        (lambda payload: payload.update(authorization_source="agent_guess"), "authorization"),
        (lambda payload: payload.update(candidate_ids=["unknown"]), "candidate"),
        (lambda payload: payload.update(extra="not allowed"), "unsupported"),
        (lambda payload: payload.update(stage_id="wrong-stage"), "stage"),
    ],
)
def test_invalid_selection_payload_fails_before_workspace_mutation(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    mutation(payload)
    before = _snapshot(tmp_path)

    with pytest.raises(SystemExit, match=message):
        module.materialize_selection(
            tmp_path,
            payload,
            protocol_name="must-not-exist.json",
            owner_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("owner must not run")
            ),
        )

    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "kb/.runtime/literature-selection/must-not-exist.json").exists()


def test_selection_payload_loader_rejects_symlink_oversize_malformed_and_unknown_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _search_module()
    real = tmp_path / "selection.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(real)
    with pytest.raises(SystemExit, match="regular JSON"):
        module._load_selection_payload(link)

    oversized = tmp_path / "oversized.json"
    monkeypatch.setattr(module, "MAX_SELECTION_PAYLOAD_BYTES", 8)
    oversized.write_bytes(b"{" + b" " * 16 + b"}")
    with pytest.raises(SystemExit, match="bounded regular JSON"):
        module._load_selection_payload(oversized)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit, match="valid JSON"):
        module._load_selection_payload(malformed)

    monkeypatch.setattr(module, "MAX_SELECTION_PAYLOAD_BYTES", 64 * 1024)
    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"unknown": True}), encoding="utf-8")
    with pytest.raises(SystemExit, match="unsupported"):
        module._load_selection_payload(unknown)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
    with pytest.raises(SystemExit, match="valid JSON"):
        module._load_selection_payload(duplicate)


def test_adapter_rejects_duplicate_yaml_keys_before_owner_or_protocol(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    stage.write_text(stage.read_text(encoding="utf-8") + "status: staged\n", encoding="utf-8")
    calls: list[object] = []

    with pytest.raises(SystemExit, match="stage|unsafe|canonical"):
        module.materialize_selection(
            tmp_path,
            payload,
            protocol_name="duplicate-yaml.json",
            owner_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []
    assert not (tmp_path / "kb/.runtime/literature-selection/duplicate-yaml.json").exists()


@pytest.mark.parametrize("replacement", ["symlink", "fifo"])
def test_adapter_rejects_unsafe_stage_leaf_before_owner(
    tmp_path: Path,
    replacement: str,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    original = tmp_path / "original-stage.yaml"
    stage.replace(original)
    if replacement == "symlink":
        stage.symlink_to(original)
    else:
        os.mkfifo(stage)
    calls: list[object] = []

    with pytest.raises(SystemExit, match="stage|unsafe|regular"):
        module.materialize_selection(
            tmp_path,
            payload,
            protocol_name=f"unsafe-{replacement}.json",
            owner_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

    assert calls == []


def test_multi_selection_partial_failure_reports_exact_counts_and_retries_safely(
    tmp_path: Path,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path, ("paper-a", "paper-b"))
    payload = _selection(stage, ("paper-a", "paper-b"))
    attempts: list[str] = []

    def partial(argv, *, env):
        del env
        candidate_id = argv[argv.index("--candidate-id") + 1]
        attempts.append(candidate_id)
        if candidate_id == "paper-b":
            return subprocess.CompletedProcess(argv, 19, stdout=b"", stderr=b"retryable")
        _write_owner_record(
            tmp_path,
            stage_id=stage.stem,
            candidate_id=candidate_id,
            user_authorization=str(payload["user_authorization"]),
            record_id="p-paper-a-materialized",
        )
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

    first = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="partial.json",
        owner_runner=partial,
    )

    assert attempts == ["paper-a", "paper-b"]
    assert first["exit_code"] == 1
    assert first["counts"] == {
        "selected": 2,
        "newly_materialized": 1,
        "duplicate": 0,
        "already_materialized": 0,
        "failed": 1,
    }

    retry_runner, calls = _success_runner(tmp_path)
    second = module.materialize_selection(
        tmp_path,
        _selection(stage, ("paper-a", "paper-b")),
        protocol_name="retry.json",
        owner_runner=retry_runner,
    )

    assert len(calls) == 1
    assert "paper-b" in calls[0][0]
    assert second["counts"] == {
        "selected": 2,
        "newly_materialized": 1,
        "duplicate": 0,
        "already_materialized": 1,
        "failed": 0,
    }


def test_default_owner_runner_is_headless_and_never_uses_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _search_module()
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module._default_owner_runner(("python", "owner.py"), env={"SAFE": "1"})

    assert result.returncode == 0
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["capture_output"] is True
    assert seen["env"] == {"SAFE": "1"}
    assert "shell" not in seen or seen["shell"] is False


def test_stage_digest_is_bound_as_exact_anchored_target_digest(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    first = module._literature_stage_digest(tmp_path, stage.stem)
    payload = load_yaml(stage)
    payload["note"] = "changed"
    write_yaml_if_changed(stage, payload)
    second = module._literature_stage_digest(tmp_path, stage.stem)

    assert len(first) == 64
    assert len(second) == 64
    assert first != second
    assert first != hashlib.sha256(stage.read_bytes()).hexdigest()


def test_initial_whole_stage_race_fails_before_owner_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    original_validate = module._validate_selection_payload

    def racing_validate(root, payload):
        bound = original_validate(root, payload)
        changed = load_yaml(stage)
        changed["query"] = "concurrently replaced query"
        write_yaml_if_changed(stage, changed)
        return bound

    monkeypatch.setattr(module, "_validate_selection_payload", racing_validate)

    def forbidden_owner(*_args, **_kwargs):
        raise AssertionError("owner must not receive a selection whose whole stage changed")

    result = module.materialize_selection(
        tmp_path,
        _selection(stage),
        protocol_name="initial-race.json",
        owner_runner=forbidden_owner,
    )

    assert result["exit_code"] == 1
    assert result["counts"]["failed"] == 1
    protocol = json.loads(
        (tmp_path / "kb/.runtime/literature-selection/initial-race.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["integrity_failure"] is True
    assert protocol["owner_results"][0]["state"] == "selection_binding_changed"


@pytest.mark.parametrize("external_mutation", ["stop", "query", "other-candidate"])
def test_owner_success_with_unrelated_stage_rewrite_preserves_success_and_stops(
    tmp_path: Path,
    external_mutation: str,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path, ("paper-a", "paper-b"))
    payload = _selection(stage, ("paper-a", "paper-b"))
    calls: list[str] = []

    def owner_then_rewrite(argv, *, env):
        del env
        candidate_id = argv[argv.index("--candidate-id") + 1]
        calls.append(candidate_id)
        _write_owner_record(
            tmp_path,
            stage_id=stage.stem,
            candidate_id=candidate_id,
            user_authorization=str(payload["user_authorization"]),
            record_id=f"p-{candidate_id}-materialized",
        )
        changed = load_yaml(stage)
        if external_mutation == "stop":
            changed["stop"]["rationale"] = "concurrent stop rewrite"
        elif external_mutation == "query":
            changed["query"] = "concurrent query rewrite"
        else:
            changed["candidates"][1]["title"] = "Concurrent paper B rewrite"
        write_yaml_if_changed(stage, changed)
        return subprocess.CompletedProcess(argv, 0, stdout=b"ok", stderr=b"")

    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name=f"owner-rewrite-{external_mutation}.json",
        owner_runner=owner_then_rewrite,
    )

    assert calls == ["paper-a"]
    assert result["exit_code"] == 1
    assert result["counts"] == {
        "selected": 2,
        "newly_materialized": 1,
        "duplicate": 0,
        "already_materialized": 0,
        "failed": 1,
    }
    assert (tmp_path / "kb/units/papers/p-paper-a-materialized/record.yaml").is_file()
    protocol = json.loads(
        (
            tmp_path
            / f"kb/.runtime/literature-selection/owner-rewrite-{external_mutation}.json"
        ).read_text(encoding="utf-8")
    )
    assert protocol["integrity_failure"] is True
    assert protocol["owner_results"][0]["state"] == "materialized_stage_binding_changed"
    assert protocol["owner_results"][0]["record_id"] == "p-paper-a-materialized"
    assert protocol["owner_results"][1]["state"] == "not_attempted_after_binding_change"


def test_whole_stage_change_between_items_breaks_expected_snapshot_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path, ("paper-a", "paper-b"))
    payload = _selection(stage, ("paper-a", "paper-b"))
    runner, calls = _success_runner(tmp_path)
    original_transition = module._valid_owner_stage_transition
    injected = False

    def transition_then_external_rewrite(*args, **kwargs):
        nonlocal injected
        valid = original_transition(*args, **kwargs)
        if valid and not injected:
            injected = True
            changed = load_yaml(stage)
            changed["note"] = "concurrent change after the accepted owner transition"
            write_yaml_if_changed(stage, changed)
        return valid

    monkeypatch.setattr(module, "_valid_owner_stage_transition", transition_then_external_rewrite)
    result = module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="between-items.json",
        owner_runner=runner,
    )

    assert len(calls) == 1
    assert "paper-a" in calls[0][0]
    assert result["exit_code"] == 1
    assert result["counts"]["newly_materialized"] == 1
    assert result["counts"]["failed"] == 1
    protocol = json.loads(
        (tmp_path / "kb/.runtime/literature-selection/between-items.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["integrity_failure"] is True
    assert protocol["owner_results"][0]["state"] == "materialized"
    assert protocol["owner_results"][1]["state"] == "selection_binding_changed"


def test_protocol_name_is_single_use_and_rejected_before_owner_rerun(tmp_path: Path) -> None:
    module = _search_module()
    stage = _terminal_stage(tmp_path)
    payload = _selection(stage)
    runner, _calls = _success_runner(tmp_path)
    module.materialize_selection(
        tmp_path,
        payload,
        protocol_name="single-use.json",
        owner_runner=runner,
    )
    before_units = _snapshot(tmp_path / "kb/units")

    def forbidden_owner(*_args, **_kwargs):
        raise AssertionError("used protocol name must fail before owner dispatch")

    with pytest.raises(SystemExit, match="already been used"):
        module.materialize_selection(
            tmp_path,
            payload,
            protocol_name="single-use.json",
            owner_runner=forbidden_owner,
        )

    assert _snapshot(tmp_path / "kb/units") == before_units


def test_protocol_publish_race_never_overwrites_competing_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _search_module()
    destination = tmp_path / "kb/.runtime/literature-selection/raced.json"
    competing = '{"writer":"competing"}\n'

    def competing_publish(*_args, **_kwargs):
        destination.write_text(competing, encoding="utf-8")
        raise FileExistsError(destination)

    monkeypatch.setattr(module.os, "link", competing_publish)
    with pytest.raises(SystemExit, match="already been used"):
        module._write_selection_protocol(
            tmp_path,
            "raced.json",
            {"schema": "literature-selection-owner-adapter/v1"},
        )

    assert destination.read_text(encoding="utf-8") == competing
    assert not list(destination.parent.glob(".raced.json.*.tmp"))
