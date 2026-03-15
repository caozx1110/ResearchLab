# Output Schema

Use this schema when creating or refreshing `doc/repos/<repo-name>/`.

## Per-Repo Layout

Each repository should contain:

- `human/`
  - `overview.md`
  - `architecture.md`
  - `workflows.md`
  - `research-notes.md`
  - `todo.md`
- `agent/`
  - `summary.yaml`
  - `facts.json`
  - `facts.yaml`
  - `report.md`
  - `tree.txt`
  - `summary-seed.yaml` after refresh

Treat `agent/` as machine-oriented evidence and scaffolding, not as final narrative documentation. Treat `human/` as the reader-facing knowledge base.

## `summary.yaml`

Keep `agent/summary.yaml` compact and machine-readable. Prefer empty strings or empty lists over prose paragraphs.

Recommended keys:

```yaml
repo_name:
purpose:
repo_type:
primary_language:
frameworks: []
entrypoints: []
config_system:
main_workflows: []
key_modules: []
extension_points: []
datasets: []
artifacts: []
external_dependencies: []
risks: []
open_questions: []
```

## `overview.md`

Write this file to `human/overview.md`.

Required sections:

- Repository purpose
- Main capabilities
- Key entrypoints
- Technology stack
- Quick orientation for readers and agents

## `architecture.md`

Write this file to `human/architecture.md`.

Required sections:

- System map
- Key modules and responsibilities
- Configuration flow
- Data or control flow
- Extension points
- Architectural risks

Optional sections:

- Dependency hotspots
- Registration mechanisms
- Notable design tradeoffs

## `workflows.md`

Write this file to `human/workflows.md`.

Document only the workflows that are actually present.

Typical sections:

- Training workflow
- Evaluation workflow
- Inference or demo workflow
- Data preparation workflow
- Experiment management workflow

Each workflow should answer:

- where it starts
- which modules it passes through
- what inputs it expects
- what artifacts it produces

## `research-notes.md`

Write this file to `human/research-notes.md`.

Required sections:

- Observed strengths
- Bottlenecks or risks
- Improvement ideas
- Open research questions

For each improvement idea, include:

- evidence
- affected modules
- expected gain
- implementation cost or risk

## `todo.md`

Write this file to `human/todo.md`.

Group tasks by priority.

Suggested fields per task:

- title
- priority
- background
- affected files or modules
- suggested action
- expected payoff

## `index.md`

Create this file only for multi-repository work, at `doc/repos/index.md`.

Recommended sections:

- Repository table
- Shared stack or conventions
- Major differences
- Reuse opportunities
- Comparative research directions

If you want a machine-generated comparison before editing the human-facing index, use `scripts/refresh_docs.py --write-generated-index` to emit `doc/repos/index.generated.md`.
