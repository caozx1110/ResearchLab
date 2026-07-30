from __future__ import annotations

import re
import subprocess
from pathlib import Path

from repo_paths import REPO_ROOT


LEGACY_ANALYZER_PATH = re.compile(
    r"\.agents/skills/(?:paper|repo|dataset|blog)-analyst(?:/|`|\b)"
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
LEGACY_PRIVATE_DESIGN_REFERENCE = re.compile(
    r"(?:"
    r"SSOT\s*(?:§|Part\b|Principle\b|principle\b|原则|(?:[0-9]+\.)+[0-9A-Za-z]*\b|B[34]\b)"
    r"|原则\s*[0-9]+"
    r"|\bB[34]\b"
    r"|3\.6/3\.10/3\.7"
    r"|design\s+§[0-9]+"
    r")"
)


def _discoverable_skills() -> list[str]:
    skills_root = REPO_ROOT / "skills"
    return sorted(
        path.name
        for path in skills_root.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def _current_markdown_files() -> list[Path]:
    files = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "CHANGELOG.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "SECURITY.md",
    ]
    for root in (
        REPO_ROOT / "docs",
        REPO_ROOT / "runtime",
        REPO_ROOT / "skills",
        REPO_ROOT / ".github",
        REPO_ROOT / "tools",
    ):
        files.extend(root.rglob("*.md"))
    return sorted({path for path in files if path.is_file()})


def test_distributed_readme_matches_discoverable_skill_inventory() -> None:
    skills = _discoverable_skills()
    readme = (REPO_ROOT / "runtime" / "README.md").read_text(encoding="utf-8")

    assert len(skills) == 15
    assert "15 个可发现 skill" in readme
    for skill in skills:
        assert f"`{skill}`" in readme

    assert not LEGACY_ANALYZER_PATH.search(readme)
    assert "20 个本地 skill" not in readme
    assert "`wiki-adapter`" not in readme
    assert "`research-navigator`" not in readme


def test_current_docs_do_not_reference_removed_analyzer_paths() -> None:
    stale = []
    for path in _current_markdown_files():
        text = path.read_text(encoding="utf-8")
        if LEGACY_ANALYZER_PATH.search(text):
            stale.append(path.relative_to(REPO_ROOT).as_posix())
    assert stale == []


def test_current_local_markdown_links_resolve() -> None:
    missing: list[str] = []
    for path in _current_markdown_files():
        text = path.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            # GitHub copies template bodies into /issues/<n> or /pull/<n>.
            # In that rendered context ../blob/main/... points at the repository,
            # even though resolving it beside the template source would not.
            if relative.startswith("../blob/main/") and (
                path.parent == REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
                or path == REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
            ):
                resolved = (REPO_ROOT / relative[len("../blob/main/") :]).resolve()
            else:
                resolved = (path.parent / relative).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(REPO_ROOT)} -> {target}")
    assert missing == []


def test_github_template_links_resolve_after_body_copy() -> None:
    template_paths = [
        REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
        *(REPO_ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.md"),
    ]
    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        if "DEVELOPMENT_WORKFLOW.md" not in text:
            continue
        assert "(../blob/main/docs/DEVELOPMENT_WORKFLOW.md)" in text


def test_development_protocol_fences_are_balanced() -> None:
    protocol = (REPO_ROOT / "docs" / "DEVELOPMENT_WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    fence_lines = [line for line in protocol.splitlines() if line.startswith("~~~")]
    assert len(fence_lines) % 2 == 0
    assert all(line in {"~~~", "~~~yaml", "~~~text"} for line in fence_lines)
    assert "\n~~\n" not in protocol


def test_development_contract_is_github_remote_complete() -> None:
    ignore_lines = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    # Legacy local material can remain ignored, but it has zero contractual authority.
    assert "dev-docs/" in ignore_lines

    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    design = (REPO_ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    protocol = (REPO_ROOT / "docs" / "DEVELOPMENT_WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    epic_template = (
        REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "initiative-epic.md"
    ).read_text(encoding="utf-8")
    atomic_template = (
        REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "atomic-change.md"
    ).read_text(encoding="utf-8")
    governance_template = (
        REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "development-governance.md"
    ).read_text(encoding="utf-8")
    pr_template = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(
        encoding="utf-8"
    )
    ci_workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "均已弃用为协作权威" in agents
    assert "`docs/DESIGN.md`" in agents
    assert "`docs/decisions/*.md`" in agents
    assert "remote commits、PR、Actions" in agents
    assert "只凭 fresh clone 与 GitHub" in agents
    assert "`docs/DEVELOPMENT_WORKFLOW.md`" in agents
    assert "1 Atomic Issue = 1 delivery wave = 1 consolidated PR" in agents
    assert "普通改动不要求手写 digest chain" in agents

    current_remote_contracts = [
        contributing,
        design,
        protocol,
        epic_template,
        atomic_template,
        governance_template,
        pr_template,
    ]
    # Deprecation notices may name legacy locations, but no current contract may
    # restore the old private workspace as an input or source of truth.
    forbidden_authority_claims = (
        "先从维护者取得当前 SSOT/handoff",
        "dev-docs/ 是维护者本地唯一可信",
        "当前 handoff 是施工规格",
        "typed relay receipt 为准",
    )
    for text in current_remote_contracts:
        for claim in forbidden_authority_claims:
            assert claim not in text

    assert "GitHub 上的 tracked files、Issue、PR、remote refs/commits 和 Actions" in contributing
    assert "只凭 fresh clone 与 GitHub" in design
    assert "Definition of Ready" in atomic_template
    assert "待解决的问题与证据" in atomic_template
    assert "期望 outcome" in atomic_template
    assert "Last remote checkpoint" in atomic_template
    assert "增强控制（按需）" in atomic_template
    assert "Default branch baseline SHA" in epic_template
    assert "Delivery waves" in epic_template
    assert "Definition of Done" in epic_template
    assert "Candidate head SHA" in pr_template
    assert "PR merge-candidate Actions run" in pr_template
    assert "人类 review gate" in pr_template
    assert "Agent 当前停在等待人类审查" in pr_template
    assert "Closes #" not in pr_template
    assert "Fixes #" not in pr_template
    assert "Resolves #" not in pr_template

    assert "普通流程" in protocol
    assert "何时升级到增强流程" in protocol
    assert "普通单 Agent 改动不需要自定义 comment digest" in protocol
    assert "并行 worktree 规则" in protocol
    assert "takeover" in protocol
    assert "GitHub 不可用" in protocol
    assert "不 self-approve" in protocol
    assert "由人类在 GitHub 执行 merge" in protocol

    assert "本模板不是每个普通改动的前置" in governance_template
    assert "只有一个 GitHub 账号时没有伪造第二身份" in governance_template
    assert "Require pull request" in governance_template
    assert "  push:" in ci_workflow
    assert "  pull_request:" in ci_workflow
    assert "candidate-head" in ci_workflow
    assert "tested-merge" in ci_workflow
    assert "merge_group:" not in ci_workflow

    assert (REPO_ROOT / "docs" / "decisions" / "README.md").is_file()
    assert (REPO_ROOT / "docs" / "decisions" / "_template.md").is_file()
    assert (
        REPO_ROOT
        / "docs"
        / "decisions"
        / "0001-github-remote-complete-development.md"
    ).is_file()
    assert (
        REPO_ROOT
        / "docs"
        / "decisions"
        / "0002-separate-product-source-and-local-agent-tools.md"
    ).is_file()

    if not (REPO_ROOT / ".git").exists():
        return
    result = subprocess.run(
        ["git", "ls-files", "dev-docs", "*codex_prompt*"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_tracked_sources_do_not_point_to_retired_private_design_sections() -> None:
    stale: list[str] = []
    roots = (REPO_ROOT / "runtime", REPO_ROOT / "skills", REPO_ROOT / "tests")
    candidates = [REPO_ROOT / "AGENTS.md", REPO_ROOT / "requirements.txt"]
    for root in roots:
        candidates.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {"", ".md", ".py", ".txt"}
        )
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if LEGACY_PRIVATE_DESIGN_REFERENCE.search(text):
            stale.append(path.relative_to(REPO_ROOT).as_posix())
    assert stale == []
