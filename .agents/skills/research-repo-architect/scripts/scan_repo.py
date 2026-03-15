#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _doc_utils import agent_dir, default_doc_root, dump_yaml_text, repo_doc_dir, resolve_repo_paths


IGNORE_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "site-packages",
}

HEAVY_DIR_NAMES = {
    "media",
    "assets",
    "logs",
    "checkpoints",
    "weights",
    "thirdparty",
    "external_dependencies",
    "demo_data",
    "legal",
    "meshes",
}

MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "cargo.toml",
    "go.mod",
    "cmakelists.txt",
    "makefile",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
}

KEY_DIR_NAMES = {
    "configs",
    "conf",
    "hydra",
    "launch",
    "model",
    "models",
    "data",
    "datasets",
    "trainer",
    "training",
    "experiment",
    "experiments",
    "eval",
    "evaluation",
    "policy",
    "policies",
    "engine",
    "runner",
    "pipeline",
    "scripts",
    "examples",
    "docs",
    "tests",
    "sim",
    "sim2sim",
    "envs",
    "tasks",
    "robot",
    "hardware",
    "deploy",
    "deployment",
    "teleop",
    "control",
    "src",
    "utils",
}

CONFIG_DIR_NAMES = {"configs", "conf", "hydra", "launch"}
DOC_DIR_NAMES = {"docs", "doc", "getting_started"}
EXAMPLE_DIR_NAMES = {"examples", "example", "benchmarks"}
TEST_DIR_NAMES = {"tests", "test"}
SUBSYSTEM_HINT_CHILDREN = {
    "scripts",
    "src",
    "control",
    "model",
    "models",
    "data",
    "configs",
    "eval",
    "policy",
    "deploy",
}

ENTRYPOINT_EXTENSIONS = {".py", ".sh", ".bash"}
ENTRYPOINT_HINTS = (
    "train",
    "finetune",
    "eval",
    "infer",
    "inference",
    "serve",
    "server",
    "client",
    "deploy",
    "export",
    "convert",
    "benchmark",
    "rollout",
    "download",
    "main",
    "run",
    "teleop",
    "record",
)

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".ipynb": "Jupyter",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".h": "C/C++ Header",
    ".c": "C",
    ".cu": "CUDA",
    ".cuh": "CUDA",
    ".rs": "Rust",
    ".go": "Go",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".md": "Markdown",
}

FRAMEWORK_HINTS = {
    "PyTorch": ("torch", "torchvision"),
    "Hugging Face Transformers": ("transformers", "automodel.from_pretrained"),
    "DeepSpeed": ("deepspeed",),
    "Tyro": ("tyro",),
    "LeRobot": ("lerobot",),
    "MuJoCo": ("mujoco",),
    "TensorRT": ("tensorrt",),
    "ZeroMQ": ("pyzmq", "zeromq", "zmq"),
    "ROS2": ("ros2", "rclpy", "ament"),
    "Pinocchio": ("pinocchio",),
    "Unitree SDK2": ("unitree_sdk2", "unitree sdk"),
    "Docker": ("dockerfile", "docker/", "docker-compose"),
}

KIND_KEYWORDS = {
    "training": ("train", "finetune"),
    "evaluation": ("eval", "benchmark", "rollout"),
    "inference": ("infer", "inference", "serve", "server", "client"),
    "deployment": ("deploy", "export"),
    "teleop": ("teleop",),
    "data": ("convert", "prepare", "download", "record"),
    "simulation": ("sim",),
}


def relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def prune_dir(name: str, depth: int) -> bool:
    lowered = name.lower()
    if lowered in IGNORE_DIR_NAMES:
        return True
    if depth >= 1 and lowered in HEAVY_DIR_NAMES:
        return True
    return False


def safe_read_text(path: Path, limit: int = 200_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def iter_files(root: Path, max_depth: int) -> list[Path]:
    files: list[Path] = []
    for current, dirs, filenames in os.walk(root, topdown=True):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts if current_path != root else ()
        depth = len(rel_parts)
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not prune_dir(d, depth + 1)]
        for filename in filenames:
            files.append(current_path / filename)
    return files


def top_level_dirs(root: Path) -> list[Path]:
    return sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name.lower() not in IGNORE_DIR_NAMES],
        key=lambda path: path.name.lower(),
    )


def top_level_files(root: Path) -> list[Path]:
    return sorted(
        [path for path in root.iterdir() if path.is_file() and not path.name.startswith(".")],
        key=lambda path: path.name.lower(),
    )


def collect_readmes(root: Path) -> list[str]:
    readmes = []
    for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.name.lower().startswith("readme"):
            readmes.append(relative_path(path, root))
    return readmes


def collect_manifests(root: Path) -> list[str]:
    manifests: set[str] = set()
    for candidate in root.glob("*"):
        if candidate.is_file() and candidate.name.lower() in MANIFEST_NAMES:
            manifests.add(relative_path(candidate, root))
    for child in top_level_dirs(root):
        for candidate in child.glob("*"):
            if candidate.is_file() and candidate.name.lower() in MANIFEST_NAMES:
                manifests.add(relative_path(candidate, root))
    gitmodules = root / ".gitmodules"
    if gitmodules.exists():
        manifests.add(relative_path(gitmodules, root))
    return sorted(manifests)


def collect_named_dirs(root: Path, names: set[str], max_depth: int = 2) -> list[str]:
    results: set[str] = set()
    for current, dirs, _ in os.walk(root, topdown=True):
        current_path = Path(current)
        rel_parts = current_path.relative_to(root).parts if current_path != root else ()
        depth = len(rel_parts)
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if not prune_dir(d, depth + 1)]
        if current_path != root and current_path.name.lower() in names:
            results.add(relative_path(current_path, root))
    return sorted(results)


def detect_languages(files: list[Path], root: Path) -> tuple[str, list[dict[str, Any]]]:
    counts = Counter()
    for path in files:
        suffix = path.suffix.lower()
        language = LANGUAGE_BY_SUFFIX.get(suffix)
        if language:
            counts[language] += 1
        elif path.name.lower() == "dockerfile":
            counts["Docker"] += 1
        elif path.name.lower() == "makefile":
            counts["Make"] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    primary = ordered[0][0] if ordered else "Unknown"
    return primary, [{"language": language, "count": count} for language, count in ordered[:10]]


def detect_frameworks(root: Path, manifests: list[str], readmes: list[str]) -> list[str]:
    text_sources = [root / rel for rel in manifests + readmes]
    combined = "\n".join(safe_read_text(path).lower() for path in text_sources if path.exists())
    detected = []
    for framework, keywords in FRAMEWORK_HINTS.items():
        if any(keyword in combined for keyword in keywords):
            detected.append(framework)
    return detected


def classify_entrypoint(relpath: str) -> str:
    lowered = relpath.lower()
    for kind, keywords in KIND_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return kind
    if lowered.endswith(".sh"):
        return "shell"
    return "general"


def entrypoint_evidence(path: Path) -> list[str]:
    evidence: list[str] = []
    lowered = path.name.lower()
    if path.suffix.lower() in {".sh", ".bash"}:
        evidence.append("shell-script")
    if any(hint in lowered for hint in ENTRYPOINT_HINTS):
        evidence.append("filename-hint")
    text = safe_read_text(path, limit=40_000)
    lowered_text = text.lower()
    if "if __name__ == \"__main__\"" in text or "if __name__ == '__main__'" in text:
        evidence.append("__main__")
    if "tyro.cli" in lowered_text:
        evidence.append("tyro.cli")
    if "argparse.argumentparser" in lowered_text:
        evidence.append("argparse")
    if "@click.command" in lowered_text or "click.command(" in lowered_text:
        evidence.append("click")
    return evidence


def collect_entrypoints(root: Path, files: list[Path], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in files:
        rel = relative_path(path, root)
        rel_lower = rel.lower()
        if path.suffix.lower() not in ENTRYPOINT_EXTENSIONS:
            continue
        if not (
            any(hint in rel_lower for hint in ENTRYPOINT_HINTS)
            or "scripts/" in rel_lower
            or "/scripts/" in rel_lower
            or "examples/" in rel_lower
            or "/examples/" in rel_lower
        ):
            continue
        evidence = entrypoint_evidence(path)
        if path.suffix.lower() == ".py" and not any(
            marker in evidence for marker in ("__main__", "tyro.cli", "argparse", "click")
        ):
            continue
        if not evidence:
            continue
        kind = classify_entrypoint(rel)
        score = len(evidence) * 10
        if kind in {"training", "evaluation", "inference", "deployment", "teleop", "simulation"}:
            score += 20
        if rel.count("/") <= 2:
            score += 5
        candidates.append(
            {
                "path": rel,
                "kind": kind,
                "evidence": ", ".join(sorted(set(evidence))),
                "score": score,
            }
        )
    ordered = sorted(candidates, key=lambda item: (-item["score"], item["path"]))
    trimmed = []
    seen = set()
    for item in ordered:
        if item["path"] in seen:
            continue
        seen.add(item["path"])
        trimmed.append({k: v for k, v in item.items() if k != "score"})
        if len(trimmed) >= limit:
            break
    return trimmed


def collect_subsystems(root: Path) -> list[dict[str, Any]]:
    subsystems = []
    explicit_names = {"gr00t", "gear_sonic", "gear_sonic_deploy", "decoupled_wbc"}
    for child in top_level_dirs(root):
        child_lower = child.name.lower()
        child_files = {path.name.lower() for path in child.iterdir() if path.is_file()}
        child_dirs = {path.name.lower() for path in child.iterdir() if path.is_dir()}
        manifest_paths = sorted(
            relative_path(path, root)
            for path in child.iterdir()
            if path.is_file() and path.name.lower() in MANIFEST_NAMES
        )
        if not (
            child_lower in explicit_names
            or manifest_paths
            or (child_dirs & SUBSYSTEM_HINT_CHILDREN)
        ):
            continue
        subsystems.append(
            {
                "path": relative_path(child, root),
                "manifest_paths": manifest_paths,
                "children": sorted(child_dirs & SUBSYSTEM_HINT_CHILDREN),
            }
        )
    return subsystems


def collect_key_dirs(root: Path) -> list[str]:
    results: set[str] = set()
    for child in top_level_dirs(root):
        if child.name.lower() in KEY_DIR_NAMES:
            results.add(relative_path(child, root))
        for grandchild in child.iterdir() if child.is_dir() else []:
            if grandchild.is_dir() and grandchild.name.lower() in KEY_DIR_NAMES:
                results.add(relative_path(grandchild, root))
    return sorted(results)


def infer_repo_type(
    primary_language: str,
    languages: list[dict[str, Any]],
    subsystems: list[dict[str, Any]],
    frameworks: list[str],
) -> str:
    subsystem_count = len(subsystems)
    language_names = {item["language"] for item in languages}
    has_native = bool({"C++", "CUDA", "C", "C/C++ Header"} & language_names)
    if has_native and subsystem_count >= 2:
        return "Mixed-language robotics or systems monorepo"
    if primary_language in {"Python", "Jupyter"} and any(
        framework in frameworks for framework in ("PyTorch", "Hugging Face Transformers", "LeRobot")
    ):
        return "Python research library or experiment repo"
    if primary_language == "C++":
        return "C++ systems or deployment repo"
    return "Research software repository"


def build_tree(root: Path) -> str:
    lines = [f"{root.name}/"]
    important_files = [
        path for path in top_level_files(root) if path.name.lower().startswith("readme") or path.name.lower() in MANIFEST_NAMES
    ]
    for path in important_files:
        lines.append(f"  {path.name}")
    for directory in top_level_dirs(root):
        lines.append(f"  {directory.name}/")
        child_dirs = [
            child for child in sorted(directory.iterdir(), key=lambda p: p.name.lower())
            if child.is_dir() and child.name.lower() not in IGNORE_DIR_NAMES
        ]
        shown = 0
        for child in child_dirs:
            if shown >= 8:
                lines.append("    ...")
                break
            if child.name.lower() in HEAVY_DIR_NAMES:
                lines.append(f"    {child.name}/")
                shown += 1
                continue
            lines.append(f"    {child.name}/")
            shown += 1
        child_files = [
            child for child in sorted(directory.iterdir(), key=lambda p: p.name.lower())
            if child.is_file() and (child.name.lower().startswith("readme") or child.name.lower() in MANIFEST_NAMES)
        ]
        for child in child_files[:4]:
            lines.append(f"    {child.name}")
    return "\n".join(lines) + "\n"


def build_report(facts: dict[str, Any]) -> str:
    lines = [f"# Scan Report: {facts['repo_name']}", ""]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Repo root: `{facts['repo_root']}`")
    lines.append(f"- Repo type hint: `{facts['repo_type_hint']}`")
    lines.append(f"- Primary language: `{facts['primary_language']}`")
    if facts["framework_hints"]:
        lines.append("- Framework hints: " + ", ".join(f"`{item}`" for item in facts["framework_hints"]))
    lines.append("")

    for title, key in (
        ("Readmes", "readmes"),
        ("Manifests", "manifests"),
        ("Docs Dirs", "docs_dirs"),
        ("Example Dirs", "example_dirs"),
        ("Test Dirs", "test_dirs"),
        ("Config Roots", "config_roots"),
        ("Key Dirs", "key_dirs"),
    ):
        lines.append(f"## {title}")
        lines.append("")
        if facts[key]:
            for item in facts[key]:
                lines.append(f"- `{item}`")
        else:
            lines.append("- None detected")
        lines.append("")

    lines.append("## Subsystems")
    lines.append("")
    if facts["subsystems"]:
        for subsystem in facts["subsystems"]:
            manifests = subsystem["manifest_paths"] or ["no nested manifest detected"]
            lines.append(
                f"- `{subsystem['path']}`: manifests={', '.join(manifests)}; children={', '.join(subsystem['children']) or 'n/a'}"
            )
    else:
        lines.append("- None detected")
    lines.append("")

    lines.append("## Entrypoints")
    lines.append("")
    if facts["entrypoints"]:
        for item in facts["entrypoints"]:
            lines.append(
                f"- `{item['path']}` [{item['kind']}] via {item['evidence']}"
            )
    else:
        lines.append("- None detected")
    lines.append("")

    lines.append("## Language Counts")
    lines.append("")
    if facts["languages"]:
        for item in facts["languages"]:
            lines.append(f"- `{item['language']}`: {item['count']}")
    else:
        lines.append("- None detected")
    lines.append("")

    lines.append("## Scan Notes")
    lines.append("")
    for note in facts["scan_notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def build_facts(repo_root: Path, files: list[Path], entrypoint_limit: int) -> dict[str, Any]:
    readmes = collect_readmes(repo_root)
    manifests = collect_manifests(repo_root)
    primary_language, languages = detect_languages(files, repo_root)
    frameworks = detect_frameworks(repo_root, manifests, readmes)
    key_dirs = collect_key_dirs(repo_root)
    docs_dirs = collect_named_dirs(repo_root, DOC_DIR_NAMES)
    example_dirs = collect_named_dirs(repo_root, EXAMPLE_DIR_NAMES)
    test_dirs = collect_named_dirs(repo_root, TEST_DIR_NAMES)
    config_roots = collect_named_dirs(repo_root, CONFIG_DIR_NAMES)
    subsystems = collect_subsystems(repo_root)
    entrypoints = collect_entrypoints(repo_root, files, limit=entrypoint_limit)
    external_dependencies = [
        relative_path(path, repo_root)
        for path in top_level_dirs(repo_root)
        if path.name.lower() in {"external_dependencies", "thirdparty", "submodules"}
    ]
    top_dirs = [relative_path(path, repo_root) for path in top_level_dirs(repo_root)]
    top_files = [relative_path(path, repo_root) for path in top_level_files(repo_root)[:20]]

    notes = [
        "Use agent/report.md and agent/tree.txt as a fact layer before writing narrative docs.",
        "Treat framework and repo-type fields as heuristics; verify critical claims against source files.",
    ]
    if subsystems:
        notes.append("Document major subsystems separately if the repository behaves like a monorepo.")
    if entrypoints:
        notes.append("Use detected entrypoints to prioritize workflow tracing before reading utility modules.")

    return {
        "repo_name": repo_root.name,
        "repo_root": str(repo_root),
        "scan_generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_type_hint": infer_repo_type(primary_language, languages, subsystems, frameworks),
        "primary_language": primary_language,
        "languages": languages,
        "framework_hints": frameworks,
        "readmes": readmes,
        "manifests": manifests,
        "top_level_dirs": top_dirs,
        "top_level_files": top_files,
        "docs_dirs": docs_dirs,
        "example_dirs": example_dirs,
        "test_dirs": test_dirs,
        "config_roots": config_roots,
        "key_dirs": key_dirs,
        "subsystems": subsystems,
        "entrypoints": entrypoints,
        "external_dependencies": external_dependencies,
        "scan_notes": notes,
    }
def write_outputs(repo_root: Path, doc_root: Path, facts: dict[str, Any]) -> None:
    doc_dir = repo_doc_dir(doc_root, repo_root.name)
    repo_agent_dir = agent_dir(doc_dir)
    repo_agent_dir.mkdir(parents=True, exist_ok=True)
    (repo_agent_dir / "facts.json").write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (repo_agent_dir / "facts.yaml").write_text(dump_yaml_text(facts), encoding="utf-8")
    (repo_agent_dir / "report.md").write_text(build_report(facts), encoding="utf-8")
    (repo_agent_dir / "tree.txt").write_text(build_tree(repo_root), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan research repositories and write fact-layer outputs under doc/repos/<repo>/agent/.")
    parser.add_argument("repo_paths", nargs="+", help="One or more local repository paths")
    parser.add_argument("--doc-root", type=Path, default=None, help="Directory that contains doc/repos/<repo>/")
    parser.add_argument("--max-depth", type=int, default=6, help="Maximum directory depth to walk during scanning")
    parser.add_argument("--entrypoint-limit", type=int, default=24, help="Maximum number of entrypoints to record")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_paths = resolve_repo_paths(args.repo_paths)
    doc_root = args.doc_root.resolve() if args.doc_root else default_doc_root(repo_paths)
    doc_root.mkdir(parents=True, exist_ok=True)

    for repo_path in repo_paths:
        files = iter_files(repo_path, max_depth=args.max_depth)
        facts = build_facts(repo_path, files, entrypoint_limit=args.entrypoint_limit)
        write_outputs(repo_path, doc_root, facts)
        print(f"[ok] scanned {repo_path.name} -> {(doc_root / repo_path.name / 'agent').as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
