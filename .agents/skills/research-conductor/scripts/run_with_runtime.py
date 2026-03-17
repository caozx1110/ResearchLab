#!/usr/bin/env python3
"""Run a research skill script with a remembered Python runtime."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import find_project_root, load_runtime_registry, preferred_runtime_record


def resolve_runtime(project_root: Path, runtime_id: str) -> dict[str, str]:
    if runtime_id:
        registry = load_runtime_registry(project_root)
        record = registry.get("items", {}).get(runtime_id)
        if not isinstance(record, dict):
            raise SystemExit(f"Runtime not found: {runtime_id}")
        return {key: str(value) for key, value in record.items()}
    preferred = preferred_runtime_record(project_root)
    if not preferred:
        raise SystemExit(
            "No preferred research runtime is remembered yet.\n"
            "Register one first with "
            "`python3 .agents/skills/research-conductor/scripts/manage_workspace.py "
            "remember-runtime --python <path-to-python> --label research-default`."
        )
    return {key: str(value) for key, value in preferred.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-id", default="", help="Optional remembered runtime ID")
    parser.add_argument("script", help="Skill script to execute with the remembered runtime")
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help="Arguments passed through to the skill script")
    args = parser.parse_args()

    project_root = find_project_root()
    runtime = resolve_runtime(project_root, args.runtime_id)
    python_executable = runtime.get("python", "")
    if not python_executable:
        raise SystemExit("Remembered runtime is missing its python executable path.")

    command = [python_executable, args.script, *args.script_args]
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
