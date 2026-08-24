from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest
from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


@dataclass(frozen=True)
class DistributionMetadata:
    version: str
    requires_python: str
    requires_dist: tuple[str, ...] = ()


# Offline snapshot of the runtime metadata for the exact dev-tool lock. Keeping
# dependency edges here makes the gate recursive: a pin for a direct dependency
# is not enough when that distribution has a selected dependency of its own.
DEV_CLOSURE_METADATA = {
    "pymupdf4llm": DistributionMetadata(
        version="0.0.27",
        requires_python=">=3.9",
        requires_dist=("pymupdf>=1.26.3",),
    ),
    "pymupdf": DistributionMetadata(version="1.26.5", requires_python=">=3.9"),
    "markdownify": DistributionMetadata(
        version="1.2.3",
        requires_python=">=3.9",
        requires_dist=("beautifulsoup4<5,>=4.9", "six<2,>=1.15"),
    ),
    "beautifulsoup4": DistributionMetadata(
        version="4.15.0",
        requires_python=">=3.9",
        requires_dist=(
            "soupsieve>=1.6.1",
            "typing-extensions>=4.0.0",
            "cchardet; extra == 'cchardet'",
            "chardet; extra == 'chardet'",
            "charset-normalizer; extra == 'charset-normalizer'",
            "html5lib; extra == 'html5lib'",
            "lxml; extra == 'lxml'",
        ),
    ),
    "soupsieve": DistributionMetadata(version="2.8.4", requires_python=">=3.9"),
    "six": DistributionMetadata(version="1.17.0", requires_python=">=3.9"),
    "pytest": DistributionMetadata(
        version="8.4.2",
        requires_python=">=3.9",
        requires_dist=(
            'colorama>=0.4; sys_platform == "win32"',
            'exceptiongroup>=1; python_version < "3.11"',
            "iniconfig>=1",
            "packaging>=20",
            "pluggy<2,>=1.5",
            "pygments>=2.7.2",
            'tomli>=1; python_version < "3.11"',
        ),
    ),
    "colorama": DistributionMetadata(version="0.4.6", requires_python=">=3.7"),
    "exceptiongroup": DistributionMetadata(
        version="1.3.1",
        requires_python=">=3.7",
        requires_dist=('typing-extensions>=4.6.0; python_version < "3.13"',),
    ),
    "iniconfig": DistributionMetadata(version="2.1.0", requires_python=">=3.8"),
    "packaging": DistributionMetadata(version="26.2", requires_python=">=3.8"),
    "pluggy": DistributionMetadata(version="1.6.0", requires_python=">=3.9"),
    "pygments": DistributionMetadata(version="2.20.0", requires_python=">=3.9"),
    "tomli": DistributionMetadata(version="2.4.1", requires_python=">=3.8"),
    "typing-extensions": DistributionMetadata(version="4.16.0", requires_python=">=3.9"),
    "tiktoken": DistributionMetadata(
        version="0.13.0",
        requires_python=">=3.9",
        requires_dist=("regex", "requests"),
    ),
    # regex 2026.7.19 raised its Python floor to 3.10. Pin a compatible
    # release for the project's Python 3.9 floor.
    "regex": DistributionMetadata(version="2025.11.3", requires_python=">=3.9"),
    "requests": DistributionMetadata(
        version="2.32.5",
        requires_python=">=3.9",
        requires_dist=(
            "charset_normalizer<4,>=2",
            "idna<4,>=2.5",
            "urllib3<3,>=1.21.1",
            "certifi>=2017.4.17",
        ),
    ),
    "charset-normalizer": DistributionMetadata(version="3.4.4", requires_python=">=3.7"),
    "idna": DistributionMetadata(version="3.11", requires_python=">=3.8"),
    "urllib3": DistributionMetadata(version="2.6.1", requires_python=">=3.9"),
    "certifi": DistributionMetadata(version="2025.11.12", requires_python=">=3.7"),
}

EXPECTED_LOCK_MARKERS = {
    "pymupdf4llm": None,
    "pymupdf": None,
    "markdownify": None,
    "beautifulsoup4": None,
    "soupsieve": None,
    "six": None,
    "pytest": None,
    "iniconfig": None,
    "packaging": None,
    "pluggy": None,
    "pygments": None,
    "exceptiongroup": 'python_version < "3.11"',
    "tomli": 'python_version < "3.11"',
    "typing-extensions": None,
    "colorama": 'sys_platform == "win32"',
    "tiktoken": None,
    "regex": None,
    "requests": None,
    "charset-normalizer": None,
    "idna": None,
    "urllib3": None,
    "certifi": None,
}

DEV_ROOTS = ("pymupdf4llm", "markdownify", "pytest", "tiktoken")

TARGET_ENVIRONMENTS = tuple(
    (python_version, sys_platform)
    for python_version in ("3.9", "3.10", "3.11", "3.12", "3.13")
    for sys_platform in ("linux", "win32")
)


def _project_root() -> Path:
    return REPO_ROOT


def _active_requirement_lines(path: Path) -> tuple[str, ...]:
    return tuple(
        stripped
        for line in path.read_text(encoding="utf-8").splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    )


def _normalized_name(name: str) -> str:
    return "-".join(filter(None, re.split(r"[-_.]+", name.lower())))


def _locked_version(requirement: Requirement) -> str:
    specifiers = list(requirement.specifier)
    assert len(specifiers) == 1, f"requirement is not an exact pin: {requirement}"
    specifier = specifiers[0]
    assert specifier.operator == "==" and "*" not in specifier.version, (
        f"requirement is not an exact pin: {requirement}"
    )
    return specifier.version


def _parse_exact_lock(lines: tuple[str, ...]) -> dict[str, Requirement]:
    lock: dict[str, Requirement] = {}
    for line in lines:
        if line.startswith(("-r ", "--requirement ")):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement as exc:
            raise AssertionError(f"invalid requirement: {line}") from exc
        assert not requirement.extras, f"locked requirement must not select extras: {line}"
        assert requirement.url is None, f"locked requirement must not use a URL: {line}"
        _locked_version(requirement)
        name = _normalized_name(requirement.name)
        assert name not in lock, f"duplicate requirement pin: {name}"
        lock[name] = requirement
    return lock


def _target_environment(python_version: str, sys_platform: str) -> dict[str, str]:
    environment = default_environment()
    environment.update(
        {
            "python_version": python_version,
            "python_full_version": f"{python_version}.0",
            "sys_platform": sys_platform,
            "platform_system": "Windows" if sys_platform == "win32" else "Linux",
            "os_name": "nt" if sys_platform == "win32" else "posix",
        }
    )
    return environment


def _selected(requirement: Requirement, environment: dict[str, str]) -> bool:
    return requirement.marker is None or requirement.marker.evaluate(environment=environment)


def _assert_recursive_dev_closure(lock: dict[str, Requirement]) -> None:
    reached_in_any_environment: set[str] = set()
    for python_version, sys_platform in TARGET_ENVIRONMENTS:
        environment = _target_environment(python_version, sys_platform)
        selected_lock = {
            name: requirement
            for name, requirement in lock.items()
            if _selected(requirement, environment)
        }
        assert all(root in selected_lock for root in DEV_ROOTS)

        reached: set[str] = set()
        pending = list(DEV_ROOTS)
        while pending:
            name = pending.pop()
            if name in reached:
                continue
            reached.add(name)
            metadata = DEV_CLOSURE_METADATA.get(name)
            assert metadata is not None, f"missing offline metadata for selected pin: {name}"
            locked = selected_lock.get(name)
            assert locked is not None, (
                f"missing exact pin for {name} on Python {python_version}/{sys_platform}"
            )
            assert _locked_version(locked) == metadata.version
            assert Version(python_version) in SpecifierSet(metadata.requires_python), (
                f"{name}=={metadata.version} does not support Python {python_version}"
            )

            for dependency_text in metadata.requires_dist:
                dependency = Requirement(dependency_text)
                if not _selected(dependency, environment):
                    continue
                dependency_name = _normalized_name(dependency.name)
                dependency_lock = selected_lock.get(dependency_name)
                assert dependency_lock is not None, (
                    f"missing exact pin for {dependency_name}, required by {name}, "
                    f"on Python {python_version}/{sys_platform}"
                )
                dependency_version = Version(_locked_version(dependency_lock))
                assert dependency_version in dependency.specifier, (
                    f"locked {dependency_name}=={dependency_version} does not satisfy "
                    f"{dependency_text}"
                )
                pending.append(dependency_name)

        assert reached == set(selected_lock), (
            f"lock selects packages outside the dev tools' runtime closure on "
            f"Python {python_version}/{sys_platform}: {sorted(set(selected_lock) - reached)}"
        )
        reached_in_any_environment.update(reached)

    assert reached_in_any_environment == set(lock), (
        "some exact pins are unreachable in every supported target environment: "
        f"{sorted(set(lock) - reached_in_any_environment)}"
    )


def test_requirements_dev_locks_complete_recursive_dev_tool_closure() -> None:
    lines = _active_requirement_lines(_project_root() / "requirements-dev.txt")
    includes = tuple(
        line for line in lines if line.startswith(("-r ", "--requirement "))
    )
    assert includes == ("-r requirements.txt",)

    lock = _parse_exact_lock(lines)
    assert {
        name: _locked_version(requirement) for name, requirement in lock.items()
    } == {
        name: metadata.version for name, metadata in DEV_CLOSURE_METADATA.items()
    }
    assert {
        name: str(requirement.marker) if requirement.marker is not None else None
        for name, requirement in lock.items()
    } == EXPECTED_LOCK_MARKERS
    _assert_recursive_dev_closure(lock)


def test_every_locked_dev_distribution_supports_python_3_9() -> None:
    for name, metadata in DEV_CLOSURE_METADATA.items():
        assert Version("3.9") in SpecifierSet(metadata.requires_python), (
            f"{name}=={metadata.version} has incompatible Requires-Python "
            f"{metadata.requires_python}"
        )


def test_recursive_gate_rejects_a_missing_second_order_pin() -> None:
    lines = _active_requirement_lines(_project_root() / "requirements-dev.txt")
    lock = _parse_exact_lock(lines)
    lock.pop("typing-extensions")

    with pytest.raises(AssertionError, match="missing exact pin for typing-extensions"):
        _assert_recursive_dev_closure(lock)


def test_lock_parser_rejects_range_resolution() -> None:
    lines = _active_requirement_lines(_project_root() / "requirements-dev.txt")
    range_resolved = tuple(
        line.replace("pluggy==1.6.0", "pluggy>=1.5,<2") for line in lines
    )
    assert range_resolved != lines

    with pytest.raises(AssertionError, match="requirement is not an exact pin"):
        _parse_exact_lock(range_resolved)
