#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.common import clean_text, infer_repo_roles, infer_topics_and_tags, read_text_excerpt, write_text_if_changed, write_yaml_if_changed
from research.v2 import append_history, apply_record_governance, build_index, locate_record, project_root, rel, write_record

IGNORE_DIRS = {".git", "__pycache__", ".venv", "node_modules", "build", "dist", "outputs", "logs", ".mypy_cache"}
ENTRYPOINT_HINTS = {
    "train.py",
    "main.py",
    "run.py",
    "eval.py",
    "evaluate.py",
    "infer.py",
    "inference.py",
    "demo.py",
    "app.py",
}


def _candidate_repo_roots(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    source = record.get("source", {})
    for backup in source.get("backup_paths", []):
        path = root / str(backup)
        if path.exists():
            paths.append(path if path.is_dir() else path.parent)
    original_uri = str(source.get("original_uri") or "")
    if original_uri and not original_uri.startswith("http"):
        path = Path(original_uri).expanduser()
        if path.exists():
            paths.append(path.resolve() if path.is_dir() else path.resolve().parent)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _pick_repo_root(root: Path, record: dict) -> Path | None:
    for candidate in _candidate_repo_roots(root, record):
        if candidate.is_dir():
            return candidate
    return None


def _readme_excerpt(repo_root: Path | None) -> str:
    if repo_root is None:
        return ""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        path = repo_root / name
        if path.exists():
            return clean_text(read_text_excerpt(path, limit=5000))
    return ""


def scan_structure_payload(root: Path, record: dict) -> dict:
    repo_root = _pick_repo_root(root, record)
    if repo_root is None:
        return {
            "status": "pending_user_confirmation",
            "information_types": ["fact", "inference", "unverified"],
            "repo_root": "",
            "top_level_dirs": [],
            "top_level_files": [],
            "languages": [],
            "core_modules": [],
            "entrypoints": [],
            "training_flow": ["未检测到本地源码快照，待人工补充。"],
            "inference_flow": [],
            "config_system": [],
            "data_flow": [],
            "critical_modules": [],
        }

    top_level_dirs = sorted(item.name for item in repo_root.iterdir() if item.is_dir() and item.name not in IGNORE_DIRS)
    top_level_files = sorted(item.name for item in repo_root.iterdir() if item.is_file())[:40]
    entrypoints: list[str] = []
    core_modules: set[str] = set()
    config_system: set[str] = set()
    data_flow: set[str] = set()
    critical_modules: set[str] = set()
    training_flow: list[str] = []
    inference_flow: list[str] = []
    language_counter: Counter[str] = Counter()

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS]
        current = Path(dirpath)
        relative_dir = current.relative_to(repo_root)
        if len(relative_dir.parts) > 4:
            dirnames[:] = []
            continue
        for filename in filenames:
            path = current / filename
            relative = path.relative_to(repo_root).as_posix()
            suffix = path.suffix.lower()
            if suffix:
                language_counter[suffix] += 1
            lowered = filename.lower()
            if lowered in ENTRYPOINT_HINTS or (lowered.endswith(".sh") and "train" in lowered):
                entrypoints.append(relative)
            if any(token in relative.lower() for token in ("config", "configs", "hydra", "yaml", "toml")):
                config_system.add(relative)
            if any(token in relative.lower() for token in ("data", "dataset", "loader", "dataloader")):
                data_flow.add(relative)
            if any(token in relative.lower() for token in ("model", "policy", "agent", "trainer", "engine")):
                critical_modules.add(relative)
            if relative_dir.parts:
                head = relative_dir.parts[0]
                if head not in {"tests", "docs"}:
                    core_modules.add(head)
            if any(token in lowered for token in ("train", "trainer", "fit")):
                training_flow.append(f"可能训练入口：`{relative}`")
            if any(token in lowered for token in ("eval", "infer", "demo", "serve")):
                inference_flow.append(f"可能推理/评测入口：`{relative}`")

    languages = [f"{suffix}:{count}" for suffix, count in language_counter.most_common(8)]
    return {
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "unverified"],
        "repo_root": repo_root.as_posix(),
        "top_level_dirs": top_level_dirs,
        "top_level_files": top_level_files,
        "languages": languages,
        "core_modules": sorted(core_modules)[:20],
        "entrypoints": sorted(set(entrypoints))[:20],
        "training_flow": sorted(set(training_flow))[:10],
        "inference_flow": sorted(set(inference_flow))[:10],
        "config_system": sorted(config_system)[:20],
        "data_flow": sorted(data_flow)[:20],
        "critical_modules": sorted(critical_modules)[:20],
    }


def capability_map(record: dict, structure_payload: dict, readme_excerpt: str, root: Path) -> dict:
    title = str(record.get("title") or "")
    roles = infer_repo_roles(f"{title}\n{readme_excerpt}", project_root=root)
    inferred_topics, inferred_tags = infer_topics_and_tags(f"{title}\n{readme_excerpt}", project_root=root)
    boundary = "待人工确认该仓库最适合承担的数据/训练/推理/部署角色，以及不适合的使用场景。"
    if roles:
        boundary = f"当前自动推测该仓库偏向承担：{', '.join(roles)}。仍需人工确认真正边界。"
    capabilities = [
        f"根据结构扫描，核心模块包括：{', '.join(structure_payload.get('core_modules', [])[:4]) or '待确认'}。",
        f"主要入口包括：{', '.join(structure_payload.get('entrypoints', [])[:4]) or '待确认'}。",
    ]
    if readme_excerpt:
        capabilities.append(f"README 摘录信号：{clean_text(readme_excerpt)[:180]}")
    return {
        "repo_id": record["id"],
        "status": "pending_user_confirmation",
        "information_types": ["inference", "evaluation", "unverified"],
        "candidate_roles": roles,
        "inferred_topics": inferred_topics,
        "inferred_tags": inferred_tags,
        "problem": "待人工确认该仓库主要解决的问题定义与指标对象。",
        "core_capabilities": capabilities,
        "boundary": boundary,
        "supported_tasks": [f"候选角色：{role}" for role in roles] or ["待确认支持的核心任务"],
        "unsupported_tasks": ["待确认不适合承担的任务和边界条件"],
        "reuse_candidates": ["直接复用训练/评测脚本", "借鉴配置系统与关键模块拆分"],
        "modification_risks": ["依赖重量、复现门槛、入口耦合度待人工确认"],
    }


def note_template(record: dict, structure_payload: dict, capability_payload: dict, readme_excerpt: str) -> str:
    return f"""# {record.get('title', '')}

## 能力概览

- 解决的问题：
- 候选角色：{", ".join(capability_payload.get("candidate_roles", [])) or "-"}
- 功能边界：{capability_payload.get("boundary", "")}
- 当前 topics：{", ".join(record.get("topics", [])) or "-"}
- 当前 tags：{", ".join(record.get("tags", [])) or "-"}

## README / Context 摘录

{readme_excerpt or "待人工补充 README / 文档上下文。"}

## 结构扫描摘要

- 顶层目录：{", ".join(structure_payload.get("top_level_dirs", [])) or "-"}
- 入口文件：{", ".join(structure_payload.get("entrypoints", [])) or "-"}
- 配置系统：{", ".join(structure_payload.get("config_system", [])) or "-"}
- 数据流线索：{", ".join(structure_payload.get("data_flow", [])) or "-"}

## 核心模块


## 训练流程 / 推理流程


## 可复用 / 可借鉴 / 可改造点


## 风险与限制


## Pipeline 适配性


"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze repo units in v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("scan-structure", "map-capability", "complete-note", "confirm"):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--repo-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    record, path = locate_record(root, args.repo_id)
    if record.get("kind") != "repo":
        raise SystemExit(f"{args.repo_id} is not a repo record")
    unit_root = path.parent
    repo_root = _pick_repo_root(root, record)
    readme_excerpt = _readme_excerpt(repo_root)

    if args.command == "scan-structure":
        scan_path = unit_root / "structure-scan.yaml"
        payload = scan_structure_payload(root, record)
        write_yaml_if_changed(scan_path, payload)
        record = apply_record_governance(root, record, infer_missing=True, source_label="repo-analyst")
        record["payload"]["structure"]["scan_status"] = "pending_user_confirmation"
        record["payload"]["structure"]["repo_root"] = payload["repo_root"]
        record["payload"]["structure"]["top_level_dirs"] = payload["top_level_dirs"]
        record["payload"]["structure"]["top_level_files"] = payload["top_level_files"]
        record["payload"]["structure"]["languages"] = payload["languages"]
        record["payload"]["structure"]["core_modules"] = payload["core_modules"]
        record["payload"]["structure"]["entrypoints"] = payload["entrypoints"]
        record["payload"]["structure"]["training_flow"] = payload["training_flow"]
        record["payload"]["structure"]["inference_flow"] = payload["inference_flow"]
        record["payload"]["structure"]["config_system"] = payload["config_system"]
        record["payload"]["structure"]["data_flow"] = payload["data_flow"]
        record["payload"]["structure"]["critical_modules"] = payload["critical_modules"]
        record["status"] = "screened"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        append_history(
            record,
            action="repo-structure-scanned",
            summary="Generated repo structure scan.",
            information_types=["fact", "inference", "unverified"],
            artifacts=[rel(root, scan_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {scan_path.relative_to(root)}")
        return 0

    if args.command == "map-capability":
        scan_payload = scan_structure_payload(root, record)
        scan_path = unit_root / "structure-scan.yaml"
        write_yaml_if_changed(scan_path, scan_payload)
        map_path = unit_root / "capability-map.yaml"
        payload = capability_map(record, scan_payload, readme_excerpt, root)
        write_yaml_if_changed(map_path, payload)
        record = apply_record_governance(
            root,
            record,
            explicit_topics=payload["inferred_topics"],
            explicit_tags=payload["inferred_tags"],
            infer_missing=True,
            source_label="repo-analyst",
        )
        record["payload"]["capability"]["problem"] = payload["problem"]
        record["payload"]["capability"]["core_capabilities"] = payload["core_capabilities"]
        record["payload"]["capability"]["boundary"] = payload["boundary"]
        record["payload"]["capability"]["supported_tasks"] = payload["supported_tasks"]
        record["payload"]["capability"]["unsupported_tasks"] = payload["unsupported_tasks"]
        record["payload"]["capability"]["candidate_roles"] = payload["candidate_roles"]
        record["payload"]["reuse"]["directly_reusable"] = payload["reuse_candidates"]
        record["payload"]["risk"]["constraints"] = payload["modification_risks"]
        record["status"] = "screened"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["summary"] = payload["boundary"]
        append_history(
            record,
            action="repo-capability-mapped",
            summary="Generated repo capability map.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, scan_path), rel(root, map_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {map_path.relative_to(root)}")
        return 0

    if args.command == "complete-note":
        structure_payload = scan_structure_payload(root, record)
        capability_payload = capability_map(record, structure_payload, readme_excerpt, root)
        note_path = unit_root / "repo-note.md"
        context_path = unit_root / "repo-context.md"
        write_text_if_changed(note_path, note_template(record, structure_payload, capability_payload, readme_excerpt))
        write_text_if_changed(
            context_path,
            (
                f"# Repo Context: {record.get('title', '')}\n\n"
                f"- repo_id: `{record.get('id')}`\n"
                f"- repo_root: `{structure_payload.get('repo_root') or '-'}`\n"
                f"- entrypoints: {', '.join(structure_payload.get('entrypoints', [])) or '-'}\n\n"
                f"{readme_excerpt or '待人工补充 README / docs 摘录。'}\n"
            ),
        )
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        append_history(
            record,
            action="repo-note-created",
            summary="Created full repo note scaffold.",
            information_types=["inference", "evaluation", "unverified"],
            artifacts=[rel(root, note_path), rel(root, context_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {note_path.relative_to(root)}")
        print(f"[ok] wrote {context_path.relative_to(root)}")
        return 0

    if args.command == "confirm":
        record["confirmation_status"] = "confirmed"
        record["needs_human_confirmation"] = False
        record["status"] = "active"
        append_history(record, action="repo-confirmed", summary="Repo analysis confirmed by user.", information_types=["fact"])
        write_record(root, record)
        build_index(root)
        print(f"[ok] confirmed {args.repo_id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
