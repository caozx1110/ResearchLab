# R1 reproducible dependency closure

## STEP 0

Start from latest integration HEAD supplied by root. Read AGENTS/SSOT. Preserve Python >=3.9 support and existing Linux/macOS CI jobs.

## Ownership

- `requirements-dev.txt`
- `.agents/lib/research/tests/test_r1_conversational_release.py`
- `CHANGELOG.md` only if wording needs precision

Do not edit runtime requirements, CI workflow, installer, or application code unless the closure proves a runtime dependency is missing; STOP first in that case.

## Reproduced gap

`pytest==8.4.2` is pinned, but its transitive dependencies remain range-resolved. Current managed metadata gives: iniconfig 2.1.0 (>=3.8), packaging 26.2 (>=3.8), pluggy 1.6.0 (>=3.9), Pygments 2.20.0 (>=3.9), exceptiongroup 1.3.1 (>=3.7; Python <3.11), tomli 2.4.1 (>=3.8; Python <3.11). Official PyPI reports colorama 0.4.6 and Python floor compatible with 3.9; pytest requires it only on Windows.

## Required

1. Pin the complete pytest runtime closure in `requirements-dev.txt`, retaining exact environment markers: exceptiongroup/tomli only for Python <3.11 and colorama only for Windows. Keep `-r requirements.txt` and pytest exact.
2. Extend release tests to parse exact pins with markers and assert the full expected closure, not only top-level pytest. Assert every selected pin's declared Python floor remains compatible with 3.9 using a maintained expected table (no network in tests).
3. Ensure `pip check` and the existing test suite pass in the managed Python 3.9 environment. Do not claim hash-locked wheels; describe it as exact version closure.

No push. Small commit, targeted + full, diff-check, clean status.
