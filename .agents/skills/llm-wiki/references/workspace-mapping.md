# Workspace Mapping

Map the original `llm-wiki` idea onto this workspace before deciding where to write.

## Three Layers -> Seven Layers

| Original `llm-wiki` idea | Workspace home | Primary owner |
| --- | --- | --- |
| Raw sources | `raw/` and `kb/intake/` | `literature-corpus-builder`, `repo-cataloger` |
| Persistent wiki knowledge | `kb/library/`, `kb/programs/`, `kb/wiki/`, `kb/user/` | split by artifact type |
| Schema / workflow contract | `AGENTS.md` plus skill `SKILL.md` files | schema + owner skills |

The important adjustment is that this repo separates "persistent wiki knowledge" by ownership and reopening needs instead of keeping every page in one flat markdown tree.

## Page-Type Mapping

| External `llm-wiki` page concept | Recommended workspace target |
| --- | --- |
| `wiki/sources/<slug>.md` | `kb/library/literature/<source-id>/note.md` or `kb/library/repos/<repo-id>/repo-notes.md` |
| Entity / concept page | `kb/wiki/` only when it is reused across programs; otherwise keep it inside the relevant program discussion, design, or evidence artifact |
| Topic synthesis | `kb/wiki/topics/` when cross-program, otherwise `kb/programs/<program-id>/evidence/` or `design/` |
| Comparison page | `kb/wiki/comparisons/` when it should remain reusable, otherwise the relevant `programs/<id>/design/` or `ideas/` artifact |
| Overview / landing page | `kb/user/navigation.md` and `kb/user/obsidian-start-here.md` |
| Index | `kb/wiki/index.md` |
| Log | `kb/wiki/log.md` |

## Placement Rule

Use this priority order when choosing a durable home:

1. Source-specific close reading -> `kb/library/.../note.md` or `repo-notes.md`
2. Program-specific research state -> `kb/programs/<program-id>/...`
3. Cross-program reusable synthesis -> `kb/wiki/...`
4. Human reopen entrypoint -> `kb/user/...`
5. Export-only deliverable -> `output/...`

If a page is valuable mainly because a human needs to reopen it quickly, prefer `kb/user/` even if it links to deeper canonical artifacts elsewhere.

## Obsidian Rules

- Prefer relative markdown links everywhere human-readable pages are authored.
- Treat `kb/user/` and `kb/wiki/` as the first-class markdown browsing layer.
- Treat `kb/user/kb/` as generated output, not a manual authoring surface.
- Avoid pushing humans into `kb/intake/`, `index.yaml`, `graph.yaml`, or other machine-first files when a markdown landing page can link them there more gently.
- If you need a new human-readable category under `kb/wiki/`, prefer markdown-first folders such as `topics/` or `comparisons/` rather than inventing more YAML-heavy indirection.
