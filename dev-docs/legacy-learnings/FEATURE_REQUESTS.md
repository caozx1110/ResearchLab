# Feature Requests

## [FEAT-20260720-001] progressive-kb-init-onboarding

**Logged**: 2026-07-20T16:00:00+08:00
**Priority**: high
**Status**: completed
**Area**: frontend

### Requested Capability
After `kb init` prepares the workspace, explicitly offer a short high-value preference setup or a clear “skip for now” path, and let the user supplement preferences later through natural language.

### User Context
The real first-run response said a confirmer name was still mandatory and silently applied defaults to everything else. This made a usable initialized KB look blocked, did not ask for research focus/resources, and did not explain that setup could be deferred without losing functionality.

### Complexity Estimate
medium

### Suggested Implementation
Keep init non-TTY and scaffold-first. Return a private AgentProtocol choice between configure/defer; collect only signature, language/terminology, focus, and resources/constraints in one compact turn; show allowlisted current automation defaults; make defer an additional-write-free path; and request a real signature only before the first confirmation is applied. Preserve the fifteen-verb public surface and all governance gates.

### Metadata
- Frequency: first_time
- Related Features: `kb init`, runtime preferences, judgement confirmation
- Related Files: `.agents/skills/kb-cli/scripts/kb`, `.agents/AGENTS.md`, `.agents/skills/kb-cli/SKILL.md`, `.agents/skills/research-config-manager/SKILL.md`

### Resolution
- **Completed**: 2026-07-20T19:25:00+08:00
- **Notes**: Implemented optional configure/defer onboarding, canonical resource/constraint persistence, confirmation-time identity collection, installed-copy regressions, and cold acceptance with P0–P3 all zero.

---
## [FEAT-20260723-001] complete-r3-research-system

**Logged**: 2026-07-23T20:05:00+08:00
**Priority**: high
**Status**: in_progress
**Area**: backend

### Requested Capability
Complete the remaining review UX work and all planned R3 capabilities, including passage retrieval, survey freshness, experiment run identity, bounded OpenAlex scouting, full temporary acceptance, and automatic release-candidate version synchronization.

### User Context
The user wants the 18-skill review remediation to continue directly to completion instead of leaving the previously listed optimization backlog for later rounds.

### Complexity Estimate
complex

### Suggested Implementation
Use SSOT-first design, three disjoint worktree tracks, independent integration/cold acceptance, and keep remote release actions outside scope unless separately authorized. Advance the local bundle from `0.2.0-rc.2` to `0.2.0-rc.3`, not stable GA.

### Metadata
- Frequency: recurring
- Related Features: R2 judgement convergence, R3 backlog

---
