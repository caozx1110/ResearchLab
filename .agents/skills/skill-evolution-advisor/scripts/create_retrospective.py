#!/usr/bin/env python3
"""Create a timestamped skill-evolution retrospective note and AI prompt."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug:
        raise argparse.ArgumentTypeError("slug must contain at least one letter or digit")
    return slug


def clean_items(items: list[str]) -> list[str]:
    return [item.strip() for item in items if item and item.strip()]


def bullet_lines(items: list[str], placeholder: str) -> str:
    values = clean_items(items)
    if not values:
        return f"- {placeholder}"
    return "\n".join(f"- {item}" for item in values)


def inline_list(items: list[str], placeholder: str) -> str:
    values = clean_items(items)
    return ", ".join(values) if values else placeholder


def render_skill_paths(skills: list[str]) -> str:
    values = clean_items(skills)
    if not values:
        return "- .agents/skills/<target-skill>/"
    return "\n".join(f"- .agents/skills/{skill}/" for skill in values)


def build_prompt(
    skills: list[str],
    target_skills: list[str],
    task_summary: str,
    observed_issues: list[str],
    suggestions: list[str],
) -> str:
    observed_skills = bullet_lines(skills, "none-recorded")
    target_paths = render_skill_paths(target_skills or skills)
    issues_block = bullet_lines(
        observed_issues,
        "补充本轮观察到的具体问题，例如路由不清、手工步骤重复、脚本缺失或交接不稳。",
    )
    suggestions_block = bullet_lines(
        suggestions,
        "补充针对问题的最小必要改进建议，例如修改 SKILL.md、补充脚本、收紧边界或优化 handoff。",
    )
    return f"""请你直接修改当前工作区中的相关 skill，使后续 research workflow 更顺畅、更稳定。

本次任务摘要:
- {task_summary}

本轮实际涉及的 skill:
{observed_skills}

优先检查并可能修改的 skill 路径:
{target_paths}

观察到的问题:
{issues_block}

改进建议:
{suggestions_block}

修改要求:
- 优先做最小必要修改，不要引入与上述问题无关的改动。
- 如果问题来自触发条件不清或边界模糊，优先修改 `SKILL.md` 和 `agents/openai.yaml`。
- 如果问题来自重复手工步骤或输出模板缺失，优先补充或重构 `scripts/`。
- 保持和现有 research skills 的 shared contract、handoff、validation 风格一致。
- 如果我给出的某条建议不准确，请保留问题背景，但改成你判断更合适的实现方案。

交付要求:
- 直接完成修改，不只给方案。
- 说明修改了哪些 skill 和文件。
- 解释每项修改如何对应上面的观察问题和改进建议。"""


def build_note(
    timestamp: str,
    slug: str,
    skills: list[str],
    target_skills: list[str],
    task_summary: str,
    observed_issues: list[str],
    suggestions: list[str],
) -> str:
    skills_value = inline_list(skills, "none-recorded")
    target_value = inline_list(target_skills or skills, "to-be-decided")
    prompt = build_prompt(skills, target_skills, task_summary, observed_issues, suggestions)
    return f"""# Skill Evolution Retrospective

- created_at: {timestamp}
- slug: {slug}
- status: proposed
- skills_observed: {skills_value}
- target_skills: {target_value}
- task_summary: {task_summary}

## Observed Signals

{bullet_lines(observed_issues, "What happened in the task? Which boundary, handoff, or missing resource created friction?")}

## Suggestions

{bullet_lines(suggestions, "Describe the smallest useful skill change that would address the issue above.")}

## AI Improvement Prompt

```text
{prompt}
```

## Decision

- patch_now: no
- notes:
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, type=normalize_slug)
    parser.add_argument(
        "--skill",
        action="append",
        default=[],
        help="Observed skill name. Pass multiple times for multiple skills.",
    )
    parser.add_argument(
        "--target-skill",
        action="append",
        default=[],
        help="Skill to improve. Defaults to --skill values when omitted.",
    )
    parser.add_argument("--task-summary", required=True)
    parser.add_argument(
        "--observed-issue",
        action="append",
        default=[],
        help="Observed problem or friction point. Pass multiple times for multiple issues.",
    )
    parser.add_argument(
        "--suggestion",
        action="append",
        default=[],
        help="Concrete improvement suggestion. Pass multiple times for multiple suggestions.",
    )
    parser.add_argument(
        "--stdout-prompt",
        action="store_true",
        help="Print the generated AI improvement prompt in a fenced code block after writing the note.",
    )
    parser.add_argument(
        "--root",
        default="kb/memory/skill-evolution",
        help="Root directory for retrospective notes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    notes_dir = root / "retrospectives"
    notes_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()
    timestamp = now.isoformat(timespec="seconds")
    filename_timestamp = now.strftime("%Y%m%d-%H%M%S")
    note_path = notes_dir / f"{filename_timestamp}-{args.slug}.md"

    if note_path.exists():
        print(f"refusing to overwrite existing note: {note_path}", file=sys.stderr)
        return 1

    note_path.write_text(
        build_note(
            timestamp,
            args.slug,
            args.skill,
            args.target_skill,
            args.task_summary,
            args.observed_issue,
            args.suggestion,
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    print(note_path)

    if args.stdout_prompt:
        prompt = build_prompt(
            args.skill,
            args.target_skill,
            args.task_summary,
            args.observed_issue,
            args.suggestion,
        )
        print("```text")
        print(prompt)
        print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
