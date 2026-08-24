# Research Vault v2 local contract

This reference is the self-contained file boundary for the `research-vault`
skill. Load it when initializing, indexing, mutating, or recovering a v2 vault.

## Semantic ownership

- Visible ordinary Markdown is the only human semantic truth.
- `Home.md`, `Preferences.md`, and pages under `Inbox/`, `Sources/`, `Notes/`,
  `Projects/`, `Decisions/`, `Experiments/`, `Reviews/`, and `Reports/` remain
  readable and editable without a database, runtime, or Obsidian plugin.
- Durable object pages use minimal visible `id`, `kind`, and `status`
  frontmatter. The ID is stable and unique; the path may change.
- Core navigation uses standard relative Markdown links. `Home.md` is
  user-owned and is never regenerated.

## Hidden and derived ownership

- `Sources/<source-id>/.source/` preserves immutable source revisions,
  manifests, assets, conversion snapshots, and source maps. It proves source
  fidelity but cannot own or overwrite visible meaning.
- Root `.research/` contains evidence bindings, receipts, operation journals,
  recovery snapshots, experiment raw artifacts, indexes, caches, logs, and
  locks. These files can prove, restore, or accelerate visible content; they
  cannot become a second semantic record.
- `.research/index/`, `.research/cache/`, `Views/`, and optional `.base` files
  are derived. Rebuilding them reads visible Markdown and source manifests and
  writes only explicitly product-owned derived targets.
- `.obsidian/`, `.agents/`, root `AGENTS.md`, and Git metadata are outside this
  skill's write ownership.

## Mutation and recovery

Every mutation must:

1. resolve a non-empty set of explicit literal targets;
2. reject escape, symlink, special, unknown hidden, product-owned, and legacy
   targets before writing;
3. acquire exact-path locks in stable order;
4. record target paths, before digests, snapshots, stage, and exact checkpoint
   paths in a root `.research/operations/` journal;
5. use temporary-file plus atomic-replace writes and expected-digest CAS;
6. revalidate current bytes before commit; and
7. commit all exact targets, restore exact before-images, or retain a
   recoverable journal without treating recovery material as newer semantics.

User edits win. A digest conflict stops the operation and must not be resolved
by copying hidden bytes over a changed Markdown page.

## Reserved compatibility boundary

The v2 vault does not read or write a `kb/` canonical tree, `record.yaml`, an
`obsidian/managed/` projection, or unknown hidden areas. Detecting those paths
is a containment stop, not a compatibility or migration feature. Tests and
validation use isolated fresh directories and never a real user vault.
