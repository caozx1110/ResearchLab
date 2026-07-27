# R1 reproducible dependency lock

## STEP 0 — base sync

Start from integration commit `29ce3db`. Verify the current runtime requirements are still unbounded (`PyYAML>=6`, `pymupdf4llm>=0.0.17`) and CI installs an unpinned pytest. If not, STOP and report.

## Objective

Make a given repository commit install the same tested runtime/test dependency versions across the supported Python matrix.

## File ownership — only these files

- `requirements.txt`
- new `requirements-dev.txt`
- `.github/workflows/ci.yml`
- `.agents/lib/research/tests/test_r1_conversational_release.py`
- `CHANGELOG.md` only if a one-line dependency-lock note is needed

## Locked versions

Use the versions present in the managed acceptance runtime and compatible with Python >=3.9:

- `PyYAML==6.0.3`
- `pymupdf4llm==0.0.27`
- explicitly pin its runtime dependency `PyMuPDF==1.26.5`
- `pytest==8.4.2` in `requirements-dev.txt`, which includes `-r requirements.txt`

## Required behavior

1. Runtime installer continues consuming `requirements.txt`; no heavyweight optional backend becomes default.
2. Ubuntu and macOS CI install only `requirements-dev.txt`, not a separately unpinned pytest.
3. Extend the release gate to parse/assert exact pins and both CI jobs' locked install command.
4. Validate requirement parsing, compile/scripts/skill metadata, targeted release/installer tests, and full research suite. Do not download or upgrade packages; use the already configured runtime.

## Red lines

- Do not edit installer behavior, package code, or optional-heavy-backend policy.
- No real `kb/`, no push, small coherent commit. Report Python compatibility metadata and exact test results.
