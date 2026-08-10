# Dispatcher, init, and ordinary verbs

Load only this reference for ordinary dispatch, initialization, setup, status, discovery, intake, update, or recall. Review and recovery have separate direct references.

## Private Agent protocol

- `--agent-protocol <safe-name>.json` is a global private option placed before the verb. A relative name is owned under the workspace runtime state and never checkpointed.
- `kb-agent-protocol/v1.child_results` keeps owner output and structured arguments; `next_actions` carries exact owner continuation; `details` carries diagnostics. Public stdout is the only user-facing surface.
- Do not replay raw stdout/stderr, internal paths, parameters, state codes, or protocol payloads. Preserve the original non-zero business result when diagnostic recording fails.

## Initialization and setup

- `init` activates a safe new workspace-root layout and idempotently creates core workspace/config state. It never migrates a legacy layout or existing Git repository.
- When protocol state is `ready_with_optional_setup`, present “现在设置”（recommended）or “先跳过”. Deferring writes no preference and does not block work.
- Quick setup collects the real signer, language/terminology style, focus, resources, constraints, `link_autodrive`, and `discussion_style` in one compact exchange. Show current defaults and accept “默认即可”.
- Apply only protocol-provided `field_inputs`. Preserve existing resource keys; append and deduplicate constraints; never guess dotted keys.
- Missing signer does not block listing review items. Save it headlessly only when a confirmation needs it, without overwriting unrelated preferences.

## Ordinary verb semantics

- `help`: fixed grouped capability menu. With missing core/runtime rules it stays stdlib-only and read-only.
- `doctor`: read-only runtime/workspace diagnosis; details remain private. It must stay available when workspace rules are missing.
- `update`: check only until the user authorizes apply. Preserve manifest-recorded local/fork/branch provenance; never fall back silently to upstream or `main`.
- `obsidian update|status`: regenerate or inspect managed derived views; never edit canonical records, human notes, or `.obsidian/`.
- `status` / `find` / `recall`: filter owner output. Formal findings use only current confirmed claims; navigation passages are not conclusions.
- `next`: compare the complete durable candidate set using information gain, cost/risk, blockers, and current effective preferences. Mechanical candidate order is not priority.
- `add`: honor `link_autodrive`; ask-first performs light intake, auto-deep-read continues the ingest pipeline. Type inference is limited to established URL/file-kind rules.
- `ingest`: continue an existing canonical workflow without re-scaffolding filled or verified work. Intake may prepare the correct analyzer, but all judgements remain pending user confirmation.
- `recall`: retrieve only the explicitly requested bounded learning/diagnostic summary; never preload the full memory at session start.

## Preference boundary

Each real consumer loads only its task-eligible selected subset. Hard constraints remain active; unselected soft preferences are neutral. `kb-cli` does not copy preferences into another owner's artifacts or use reporting style to change a frozen review candidate set.
