#!/usr/bin/env python3
"""Render and verify the installer's exact, byte-bound Agent plan artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ws_sync import release_destination


BEGIN_MARKER = b"# >>> workspace-oss managed >>>"
END_MARKER = b"# <<< workspace-oss managed <<<"
SOURCE_BOUND_OPERATIONS = {"copy", "overwrite", "write", "write-manifest", "write-managed-block"}
PLAN_DIGEST_PLACEHOLDER = "<PLAN_DIGEST>"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-plan", default="")
    parser.add_argument("--expected-plan-digest", default="")
    parser.add_argument("--expected-source-tree-digest", default="")
    parser.add_argument("--expected-source-commit", default="")
    parser.add_argument("--current-action", default="")
    parser.add_argument("--current-scope", default="")
    parser.add_argument("--current-workspace", default="")
    parser.add_argument("--current-tool", action="append", default=[])
    parser.add_argument("--current-distributable-root", default="")
    parser.add_argument("--current-runtime-root", default="")
    parser.add_argument("--current-operation-time", default="")
    parser.add_argument("--current-force", action="store_true")
    parser.add_argument("--current-kb-on-path", action="store_true")

    parser.add_argument("--output")
    parser.add_argument("--action")
    parser.add_argument("--scope")
    parser.add_argument("--workspace")
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--source-strategy")
    parser.add_argument("--source-checkout")
    parser.add_argument("--source-origin")
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--source-commit")
    parser.add_argument("--distributable-root")
    parser.add_argument("--operation-time")
    parser.add_argument(
        "--target-record",
        nargs=6,
        action="append",
        default=[],
        metavar=("KIND", "VALUE", "PATH", "SOURCE", "CONDITION", "CONTENT_SHA256"),
    )
    parser.add_argument("--conflict", action="append", default=[])
    parser.add_argument("--apply-arg", action="append", default=[])
    return parser


def _require_generation_args(args: argparse.Namespace) -> None:
    for name in (
        "output",
        "action",
        "scope",
        "workspace",
        "source_strategy",
        "source_checkout",
        "source_origin",
        "source_commit",
        "distributable_root",
        "operation_time",
    ):
        if not getattr(args, name):
            raise SystemExit(f"--{name.replace('_', '-')} is required")


def _git_tracked_paths(source_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(source_root),
                "ls-files",
                "-z",
                "--",
                ".agents",
                "LICENSE",
                "install.sh",
                "install-lib",
                "requirements.txt",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"distributable root must be a Git worktree: {exc}") from exc
    return sorted(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def distributable_tree(source_root: Path) -> dict[str, Any]:
    """Return canonical payload and installer-input bytes without following links."""
    source_root = source_root.resolve()
    entries: list[dict[str, Any]] = []
    for relative in _git_tracked_paths(source_root):
        destination = release_destination(relative)
        installer_input = (
            relative == "install.sh"
            or relative == "requirements.txt"
            or relative.startswith("install-lib/")
        )
        if destination is None and not installer_input:
            continue
        source = source_root / relative
        mode = source.lstat().st_mode
        destinations: list[str] = []
        if destination is not None:
            destinations.append(destination)
            if relative == ".agents/AGENTS.md":
                destinations.append("AGENTS.md")
        entry: dict[str, Any] = {
            "path": relative,
            "role": "installer-input" if installer_input else "managed-payload",
            "destinations": destinations,
            "mode": f"{stat.S_IMODE(mode):04o}",
        }
        if stat.S_ISREG(mode):
            entry.update({"type": "regular", "byte_sha256": sha256_file(source)})
        elif stat.S_ISLNK(mode):
            entry.update({"type": "symlink", "target": os.readlink(source)})
        else:
            raise ValueError(f"unsupported distributable path type: {relative}")
        entries.append(entry)

    if not any(item["path"] == ".agents/AGENTS.md" for item in entries):
        raise ValueError("canonical distributable tree is missing .agents/AGENTS.md")
    entries.sort(key=lambda item: str(item["path"]))
    digest = sha256_bytes(canonical_json(entries))
    return {"schema": 1, "entry_count": len(entries), "entries": entries, "digest": digest}


def _managed_block_digest(content: bytes) -> str | None:
    lines = content.splitlines(keepends=True)
    begin = end = None
    offset = 0
    for line in lines:
        bare = line.rstrip(b"\r\n")
        if bare == BEGIN_MARKER:
            if begin is not None:
                return None
            begin = offset
        if bare == END_MARKER and begin is not None:
            end = offset + len(line)
            break
        offset += len(line)
    if begin is None or end is None:
        return None
    return sha256_bytes(content[begin:end])


def target_precondition(path: Path, *, managed_block: bool) -> dict[str, Any]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return {"type": "absent"}
    if stat.S_ISREG(mode):
        content = path.read_bytes()
        state: dict[str, Any] = {
            "type": "regular",
            "mode": f"{stat.S_IMODE(mode):04o}",
            "byte_sha256": sha256_bytes(content),
        }
        if managed_block:
            block_digest = _managed_block_digest(content)
            state["managed_block_sha256"] = block_digest or "absent"
        return state
    if stat.S_ISLNK(mode):
        return {"type": "symlink", "target": os.readlink(path)}
    if stat.S_ISDIR(mode):
        return {"type": "directory", "mode": f"{stat.S_IMODE(mode):04o}"}
    return {"type": "other", "mode": stat.S_IFMT(mode)}


def normalize_target(raw: dict[str, Any]) -> dict[str, Any]:
    operation = str(raw.get("operation") or "").strip()
    path_text = str(raw.get("path") or "").strip()
    if not operation or not path_text:
        raise ValueError("plan target requires operation and path")
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError("plan target paths must be absolute")
    target: dict[str, Any] = {"operation": operation, "path": path_text}
    source = str(raw.get("source") or "").strip()
    if source:
        target["source"] = source
    condition = str(raw.get("condition") or "").strip()
    if condition:
        target["condition"] = condition
    content_sha256 = str(raw.get("content_sha256") or "").strip()
    if content_sha256:
        if len(content_sha256) != 64 or any(char not in "0123456789abcdef" for char in content_sha256):
            raise ValueError("target content sha256 must be lowercase hexadecimal")
        target["source_content_sha256"] = content_sha256
    elif operation in SOURCE_BOUND_OPERATIONS:
        raise ValueError(f"source-bound plan target lacks a content digest: {path_text}")
    elif operation == "symlink":
        target["source_content_sha256"] = sha256_bytes(source.encode("utf-8"))
    if operation == "conditional-runtime-tree":
        target.update(
            {
                "owner": "workspace-oss project Python dependency resolver",
                "cleanup": "preserved by update, reinstall, and uninstall; remove only by explicit user request",
                "boundary": "project .venv root; resolver-managed descendants are intentionally not enumerated",
            }
        )
    target["precondition"] = target_precondition(path, managed_block="managed-block" in operation)
    return target


def _payload_for_digest(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(payload)
    normalized.pop("plan_digest", None)
    contract = normalized.get("apply_contract")
    if isinstance(contract, dict):
        contract.pop("requires_plan_digest", None)
        argv = contract.get("argv")
        if isinstance(argv, list) and "--expected-plan-digest" in argv:
            index = argv.index("--expected-plan-digest")
            if index + 1 < len(argv):
                argv[index + 1] = PLAN_DIGEST_PLACEHOLDER
    return normalized


def plan_digest(payload: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(_payload_for_digest(payload)))


def _read_plan(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Agent plan must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Agent plan is unreadable or invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != 2:
        raise ValueError("Agent plan has an unsupported schema")
    return payload


def verify_plan(args: argparse.Namespace) -> int:
    plan_path = Path(args.verify_plan).expanduser().resolve(strict=False)
    payload = _read_plan(plan_path)
    actual_digest = plan_digest(payload)
    recorded_digest = str(payload.get("plan_digest") or "")
    if not args.expected_plan_digest or actual_digest != recorded_digest or actual_digest != args.expected_plan_digest:
        raise ValueError("Agent plan digest no longer matches the reviewed plan")

    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError("Agent plan source binding is missing")
    recorded_tree = source.get("distributable_tree")
    if not isinstance(recorded_tree, dict):
        raise ValueError("Agent plan distributable tree is missing")
    root = Path(str(source.get("distributable_root") or ""))
    if root.resolve() != Path(args.current_distributable_root).resolve():
        raise ValueError("current source checkout differs from the reviewed Agent plan")
    current_tree = distributable_tree(root)
    expected_tree = str(args.expected_source_tree_digest or "")
    if (
        not expected_tree
        or current_tree != recorded_tree
        or current_tree["digest"] != expected_tree
    ):
        raise ValueError("source distributable tree no longer matches the reviewed plan")
    if str(source.get("commit") or "") != args.expected_source_commit:
        raise ValueError("source commit binding no longer matches the reviewed plan")

    expected_identity = {
        "action": args.current_action,
        "scope": args.current_scope,
        "workspace": str(Path(args.current_workspace).resolve()),
        "tools": sorted(set(args.current_tool)),
        "operation_time": args.current_operation_time,
    }
    actual_identity = {
        "action": payload.get("action"),
        "scope": payload.get("scope"),
        "workspace": payload.get("workspace"),
        "tools": payload.get("tools"),
        "operation_time": payload.get("operation_time"),
    }
    if actual_identity != expected_identity:
        raise ValueError("current install request differs from the reviewed Agent plan")
    options = payload.get("options")
    if options != {"force": args.current_force, "kb_on_path": args.current_kb_on_path}:
        raise ValueError("current install options differ from the reviewed Agent plan")

    targets = payload.get("targets")
    if not isinstance(targets, list) or payload.get("target_count") != len(targets):
        raise ValueError("Agent plan target list is invalid")
    conditional_runtime_targets = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("Agent plan target is invalid")
        operation = str(target.get("operation") or "")
        if operation == "conditional-runtime-tree":
            conditional_runtime_targets.append(target)
        path = Path(str(target.get("path") or ""))
        if operation in SOURCE_BOUND_OPERATIONS and not target.get("source_content_sha256"):
            raise ValueError("Agent plan source target is missing its content digest")
        current = target_precondition(path, managed_block="managed-block" in operation)
        if current != target.get("precondition"):
            raise ValueError(f"install target changed after plan review: {path}")
    if len(conditional_runtime_targets) != 1:
        raise ValueError("Agent plan must declare exactly one conditional runtime tree")
    if Path(str(conditional_runtime_targets[0]["path"])).resolve() != Path(args.current_runtime_root).resolve():
        raise ValueError("current managed runtime root differs from the reviewed Agent plan")
    contract = payload.get("apply_contract")
    if not isinstance(contract, dict) or contract.get("plan_path") != str(plan_path):
        raise ValueError("Agent plan path differs from its reviewed apply contract")
    print(actual_digest)
    return 0


def generate_plan(args: argparse.Namespace) -> int:
    _require_generation_args(args)
    output = Path(args.output).expanduser()
    if output.exists() and (output.is_symlink() or not output.is_file()):
        raise SystemExit("plan output must be a regular file or a new path")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise SystemExit("plan output parent must be an existing regular directory")
    output = output.resolve(strict=False)

    targets: list[dict[str, Any]] = []
    for kind, value, path, source, condition, content_sha256 in args.target_record:
        if kind == "fields":
            targets.append(
                normalize_target(
                    {
                        "operation": value,
                        "path": path,
                        "source": source,
                        "condition": condition,
                        "content_sha256": content_sha256,
                    }
                )
            )
            continue
        if kind == "json":
            loaded = json.loads(value)
            if not isinstance(loaded, dict):
                raise ValueError("target JSON must be an object")
            targets.append(normalize_target(loaded))
            continue
        raise ValueError(f"unsupported target record kind: {kind}")

    tree = distributable_tree(Path(args.distributable_root))
    apply_argv = list(args.apply_arg)
    apply_argv.extend(
        [
            "--apply-agent-plan",
            str(output),
            "--expected-plan-digest",
            PLAN_DIGEST_PLACEHOLDER,
            "--expected-source-tree-digest",
            tree["digest"],
        ]
    )
    conditional = [target for target in targets if target.get("operation") == "conditional-runtime-tree"]
    payload: dict[str, Any] = {
        "schema": 2,
        "install_name": "workspace-oss",
        "mode": "agent-plan",
        "zero_write_scope": "workspace-home-and-runtime",
        "action": args.action,
        "scope": args.scope,
        "tools": sorted(set(args.tool)),
        "workspace": str(Path(args.workspace).resolve()),
        "operation_time": args.operation_time,
        "options": {
            "force": "--force" in args.apply_arg,
            "kb_on_path": "--kb-on-path" in args.apply_arg,
        },
        "source": {
            "strategy": args.source_strategy,
            "checkout": args.source_checkout,
            "origin": args.source_origin,
            "branch": args.source_branch,
            "commit": args.source_commit,
            "distributable_root": str(Path(args.distributable_root).resolve()),
            "distributable_tree": tree,
        },
        "target_count": len(targets),
        "targets": targets,
        "conflicts": sorted(set(str(item) for item in args.conflict if str(item).strip())),
        "conditional_runtime_changes": conditional,
        "apply_contract": {
            "executable": "bash",
            "argv": apply_argv,
            "plan_path": str(output),
            "requires_same_source_commit": args.source_commit,
            "requires_source_tree_digest": tree["digest"],
            "requires_explicit_install_request": True,
            "requires_plan_review": True,
            "headless": True,
            "preserve_user_data": True,
        },
    }
    digest = plan_digest(payload)
    payload["plan_digest"] = digest
    payload["apply_contract"]["requires_plan_digest"] = digest
    digest_index = payload["apply_contract"]["argv"].index("--expected-plan-digest") + 1
    payload["apply_contract"]["argv"][digest_index] = digest
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass
    print(digest)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.verify_plan:
            return verify_plan(args)
        return generate_plan(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
