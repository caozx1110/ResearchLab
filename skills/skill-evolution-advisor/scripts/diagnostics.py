#!/usr/bin/env python3
"""Owner-only CLI for local diagnostic issue capture and review."""

from __future__ import annotations

import argparse
import json
import os
import stat
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
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, print_resolved_project_roots
from research.diagnostics import (
    REPRODUCIBLE_VALUES,
    REVIEW_STATUSES,
    SEVERITIES,
    SOURCES,
    STATUSES,
    apply_diagnostic_retrospective,
    capture_runtime_failure,
    diagnostics_policy,
    export_diagnostic_preview,
    list_diagnostic_issues,
    load_diagnostic_detail,
    record_diagnostic_issue,
    review_diagnostic_issue,
)
from research.paths import kb_root, project_root


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local-only redacted diagnostic issues.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    policy = subparsers.add_parser("policy", help="Read the normalized effective policy without writing")
    policy.add_argument("--skill", default="")

    record = subparsers.add_parser("record", help="Explicitly record one redacted issue")
    record.add_argument("--category", required=True)
    record.add_argument("--severity", choices=sorted(SEVERITIES), required=True)
    record.add_argument("--skill", required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--expected", default="")
    record.add_argument("--actual", default="")
    record.add_argument("--trigger", default="")
    record.add_argument("--source", choices=sorted(SOURCES), default="agent")
    record.add_argument("--reproducible", choices=sorted(REPRODUCIBLE_VALUES), default="unknown")
    record.add_argument("--context", default="")
    record.add_argument("--error-class", default="")

    runtime = subparsers.add_parser("capture-runtime-failure", help="Policy-gated nonzero owner exit capture")
    runtime.add_argument("--skill", required=True)
    runtime.add_argument("--operation", required=True)
    runtime.add_argument("--returncode", type=int, required=True)
    runtime.add_argument("--public-summary", default="")

    listing = subparsers.add_parser("list", help="List locally recorded issues")
    listing.add_argument("--status", choices=sorted(STATUSES), default="")
    listing.add_argument("--skill", default="")

    review = subparsers.add_parser("review", help="Confirm, dismiss, or resolve one issue")
    review.add_argument("--id", required=True)
    review.add_argument("--status", choices=sorted(REVIEW_STATUSES), required=True)

    export = subparsers.add_parser("export-preview", help="Render a local redacted preview; never upload")
    export.add_argument("--authorized", action="store_true", help="Assert explicit authorization in the current user message")
    export.add_argument("--status", choices=sorted(STATUSES), default="")
    export.add_argument("--skill", default="")

    detail = subparsers.add_parser("detail", help="Read one private local-detailed artifact")
    detail.add_argument("--id", required=True)

    apply_retrospective = subparsers.add_parser(
        "apply-retrospective",
        help="Apply one digest-bound Agent hypothesis from a private runtime JSON file",
    )
    apply_retrospective.add_argument("--id", required=True)
    apply_retrospective.add_argument("--expected-detail-digest", required=True)
    apply_retrospective.add_argument("--analysis-file", required=True)
    return parser


def _load_private_analysis(root: Path, value: str) -> dict[str, object]:
    resolved_root = root.absolute()
    runtime_root = kb_root(resolved_root) / ".runtime"
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = runtime_root / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        relative = candidate.relative_to(runtime_root)
    except ValueError as exc:
        raise SystemExit("retrospective analysis file must stay inside the private runtime area") from exc
    if not relative.parts:
        raise SystemExit("retrospective analysis file must be one regular private runtime file")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory = -1
    descriptor = -1
    try:
        directory = os.open(resolved_root, directory_flags)
        for part in ("kb", ".runtime", *relative.parts[:-1]):
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=directory)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > 16 * 1024
        ):
            raise SystemExit("retrospective analysis file must be one regular private runtime file")
        chunks: list[bytes] = []
        remaining = 16 * 1024 + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        current = os.fstat(descriptor)
        identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(content) != metadata.st_size
            or any(getattr(metadata, field) != getattr(current, field) for field in identity)
        ):
            raise SystemExit("retrospective analysis file changed during its anchored read")
    except SystemExit:
        raise
    except OSError as exc:
        raise SystemExit("retrospective analysis file must be one regular private runtime file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)

    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("retrospective analysis file is not valid UTF-8 JSON") from exc
    expected = {"explanation", "reproduction", "optimization_candidates", "next_validation"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise SystemExit("retrospective analysis must use the closed structured schema")
    return payload


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    if args.command == "policy":
        _print_json(diagnostics_policy(root, args.skill))
        return 0
    if args.command == "record":
        issue, created = record_diagnostic_issue(
            root,
            category=args.category,
            severity=args.severity,
            skill=args.skill,
            summary=args.summary,
            expected=args.expected,
            actual=args.actual,
            trigger=args.trigger,
            source=args.source,
            reproducible=args.reproducible,
            context=args.context,
            error_class=args.error_class,
        )
        _print_json({"created": created, "issue": issue})
        return 0
    if args.command == "capture-runtime-failure":
        issue = capture_runtime_failure(
            root,
            skill=args.skill,
            operation=args.operation,
            returncode=args.returncode,
            public_summary=args.public_summary,
        )
        _print_json({"captured": issue is not None, "issue": issue})
        return 0
    if args.command == "list":
        _print_json({"issues": list_diagnostic_issues(root, status=args.status, skill=args.skill)})
        return 0
    if args.command == "review":
        _print_json(review_diagnostic_issue(root, issue_id=args.id, status=args.status))
        return 0
    if args.command == "export-preview":
        _print_json(
            export_diagnostic_preview(
                root,
                authorized=args.authorized,
                status=args.status,
                skill=args.skill,
            )
        )
        return 0
    if args.command == "detail":
        _print_json(load_diagnostic_detail(root, issue_id=args.id))
        return 0
    if args.command == "apply-retrospective":
        analysis = _load_private_analysis(root, args.analysis_file)
        _print_json(
            apply_diagnostic_retrospective(
                root,
                issue_id=args.id,
                expected_detail_digest=args.expected_detail_digest,
                explanation=str(analysis["explanation"]),
                reproduction=analysis["reproduction"],
                optimization_candidates=analysis["optimization_candidates"],
                next_validation=analysis["next_validation"],
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
