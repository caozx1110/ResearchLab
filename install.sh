#!/usr/bin/env bash
set -euo pipefail

BEGIN_MARKER="# >>> workspace-oss managed >>>"
END_MARKER="# <<< workspace-oss managed <<<"
INSTALL_NAME="workspace-oss"

usage() {
  cat <<'EOF'
Usage: bash install.sh [install|update|uninstall] [options]

Configure Open Research Workspace Skills for Claude Code and/or Codex.
Default action is install.

Agent selection:
  --claude              Configure Claude Code only.
  --codex               Configure Codex only.
  --all                 Configure both Claude Code and Codex.

Scope selection:
  --project [DIR]       Project-scope install. DIR defaults to the current directory.
  --system              System-scope install.

Other options:
  --kb-on-path          Symlink the kb dispatcher onto PATH.
  --dry-run             Print planned changes without writing files.
  --force               For update, overwrite managed files with local drift.
  --source DIR          For update, sync from an alternate source tree.
  --uninstall           Legacy alias for the uninstall action.
  -h, --help            Show this help.

Examples:
  bash install.sh --claude --project .
  bash install.sh update --project /path/to/workspace
  bash install.sh uninstall --project /path/to/workspace
  bash install.sh --dry-run --claude --project .
  bash install.sh --all --system --kb-on-path
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf 'warn: %s\n' "$*" >&2
}

info() {
  printf '%s\n' "$*"
}

is_command() {
  command -v "$1" >/dev/null 2>&1
}

agent_detected() {
  case "$1" in
    claude) [ -d "$HOME/.claude" ] || is_command claude ;;
    codex) [ -d "$HOME/.codex" ] || is_command codex ;;
    *) return 1 ;;
  esac
}

script_dir() {
  local source dir
  source=${BASH_SOURCE[0]}
  while [ -L "$source" ]; do
    dir=$(cd -P -- "$(dirname -- "$source")" >/dev/null 2>&1 && pwd)
    source=$(readlink "$source")
    case $source in
      /*) ;;
      *) source=$dir/$source ;;
    esac
  done
  cd -P -- "$(dirname -- "$source")" >/dev/null 2>&1 && pwd
}

abs_dir() {
  [ -d "$1" ] || die "directory does not exist: $1"
  cd -P -- "$1" >/dev/null 2>&1 && pwd
}

path_on_path() {
  local needle entry normalized
  if [ -d "$1" ]; then
    needle=$(abs_dir "$1")
  else
    case $1 in
      /*) needle=$1 ;;
      *) needle=$(pwd)/$1 ;;
    esac
  fi
  IFS=:
  for entry in $PATH; do
    [ -n "$entry" ] || entry=.
    if [ -d "$entry" ]; then
      normalized=$(abs_dir "$entry" 2>/dev/null || true)
    else
      case $entry in
        /*) normalized=$entry ;;
        *) normalized=$(pwd)/$entry ;;
      esac
    fi
    if [ "$normalized" = "$needle" ]; then
      unset IFS
      return 0
    fi
  done
  unset IFS
  return 1
}

quote_path() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

same_dir() {
  [ "$(abs_dir "$1")" = "$(abs_dir "$2")" ]
}

ACTION=install
ACTION_FROM_SUBCOMMAND=0
DRY_RUN=0
CONFIG_CLAUDE=0
CONFIG_CODEX=0
AGENT_FLAG_SET=0
SCOPE=""
PROJECT_DIR=""
KB_ON_PATH=0
FORCE=0
SYNC_SOURCE=""

REPO_ROOT=$(script_dir)
[ -d "$REPO_ROOT/.agents/lib" ] || die "could not find .agents/lib next to install.sh"
[ -d "$REPO_ROOT/.agents/skills" ] || die "could not find .agents/skills next to install.sh"
[ -f "$REPO_ROOT/AGENTS.md" ] || die "could not find AGENTS.md next to install.sh"
[ -f "$REPO_ROOT/install-lib/ws_sync.py" ] || die "could not find install-lib/ws_sync.py next to install.sh"
is_command python3 || die "python3 is required"

if [ "$#" -gt 0 ]; then
  case "$1" in
    install|update|uninstall)
      ACTION=$1
      ACTION_FROM_SUBCOMMAND=1
      shift
      ;;
  esac
fi

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --uninstall)
      ACTION=uninstall
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --source)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--source requires a directory"
      SYNC_SOURCE=$2
      shift 2
      ;;
    --source=*)
      SYNC_SOURCE=${1#--source=}
      shift
      ;;
    --claude)
      CONFIG_CLAUDE=1
      AGENT_FLAG_SET=1
      shift
      ;;
    --codex)
      CONFIG_CODEX=1
      AGENT_FLAG_SET=1
      shift
      ;;
    --all)
      CONFIG_CLAUDE=1
      CONFIG_CODEX=1
      AGENT_FLAG_SET=1
      shift
      ;;
    --project)
      SCOPE=project
      if [ "${2:-}" != "" ] && [[ ${2:-} != --* ]]; then
        PROJECT_DIR=$2
        shift 2
      else
        PROJECT_DIR=$(pwd)
        shift
      fi
      ;;
    --project=*)
      SCOPE=project
      PROJECT_DIR=${1#--project=}
      shift
      ;;
    --system)
      SCOPE=system
      shift
      ;;
    --kb-on-path)
      KB_ON_PATH=1
      shift
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

prompt_agent_selection() {
  local default choice detected=()
  if agent_detected claude; then
    detected+=("claude")
  fi
  if agent_detected codex; then
    detected+=("codex")
  fi
  if [ "${#detected[@]}" -eq 2 ]; then
    default=all
  elif [ "${#detected[@]}" -eq 1 ]; then
    default=${detected[0]}
  else
    default=all
  fi
  if [ ! -t 0 ]; then
    die "agent selection requires --claude, --codex, or --all in non-interactive mode"
  fi
  printf 'Detected agents: Claude=%s Codex=%s\n' \
    "$(agent_detected claude && printf yes || printf no)" \
    "$(agent_detected codex && printf yes || printf no)"
  printf 'Configure which agents? [claude/codex/all/none] [%s]: ' "$default"
  read -r choice || choice=""
  choice=${choice:-$default}
  case "$choice" in
    claude) CONFIG_CLAUDE=1 ;;
    codex) CONFIG_CODEX=1 ;;
    all) CONFIG_CLAUDE=1; CONFIG_CODEX=1 ;;
    none) ;;
    *) die "unknown agent choice: $choice" ;;
  esac
}

prompt_scope() {
  local choice
  if [ ! -t 0 ]; then
    die "scope selection requires --project [DIR] or --system in non-interactive mode"
  fi
  printf 'Install scope? [project/system] [project]: '
  read -r choice || choice=""
  choice=${choice:-project}
  case "$choice" in
    project) SCOPE=project ;;
    system) SCOPE=system ;;
    *) die "unknown scope: $choice" ;;
  esac
}

if [ "$AGENT_FLAG_SET" -eq 0 ]; then
  if [ "$ACTION" = "install" ] || { [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 0 ]; }; then
    prompt_agent_selection
  else
    CONFIG_CLAUDE=1
    CONFIG_CODEX=1
  fi
fi
[ "$CONFIG_CLAUDE" -eq 1 ] || [ "$CONFIG_CODEX" -eq 1 ] || { [ "$ACTION" != "install" ] || die "no agents selected"; }

if [ -z "$SCOPE" ]; then
  prompt_scope
fi

if [ -z "$PROJECT_DIR" ]; then
  PROJECT_DIR=$(pwd)
fi
WORKSPACE_ROOT=$(abs_dir "$PROJECT_DIR")
SKILLS_SRC="$REPO_ROOT/.agents/skills"
KB_SCRIPT="$REPO_ROOT/.agents/skills/kb-cli/scripts/kb"
WS_KB_SCRIPT="$KB_SCRIPT"
MANIFEST_PATH="$WORKSPACE_ROOT/.agents/.install-manifest.json"
SELF_CONTAINED=0
COPY_PROJECT=0

if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
  SELF_CONTAINED=1
elif [ "$SCOPE" = "project" ]; then
  COPY_PROJECT=1
  SELF_CONTAINED=1
  WS_KB_SCRIPT="$WORKSPACE_ROOT/.agents/skills/kb-cli/scripts/kb"
fi

if [ "$ACTION" = "update" ]; then
  [ "$SCOPE" = "project" ] || die "update is only for external project copy installs; for system scope, rerun install"
  [ "$COPY_PROJECT" -eq 1 ] || die "update is only for external project copy installs; for this repo, use git pull"
fi

if [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 1 ]; then
  [ "$SCOPE" = "project" ] || die "uninstall subcommand is only for project installs; use --uninstall with --system for system scope"
  [ "$COPY_PROJECT" -eq 1 ] || die "uninstall subcommand is only for external project installs; this repo is managed by git"
fi

preflight_yaml() {
  local py
  py=${RESEARCH_PYTHON:-python3}
  info "Preflight: checking PyYAML with $(quote_path "$py")"
  if "$py" -c 'import yaml' >/dev/null 2>&1; then
    if [ -n "${VIRTUAL_ENV:-}" ]; then
      info "Active venv: $VIRTUAL_ENV"
    else
      info "No active VIRTUAL_ENV detected."
    fi
    return 0
  fi
  warn "PyYAML is not importable with $py."
  if [ -n "${VIRTUAL_ENV:-}" ]; then
    warn "Active venv: $VIRTUAL_ENV"
  else
    warn "No active VIRTUAL_ENV detected."
  fi
  if [ "$DRY_RUN" -eq 1 ] || [ ! -t 0 ]; then
    warn "Install requirements with: $py -m pip install -r $(quote_path "$REPO_ROOT/requirements.txt")"
    warn "Or set RESEARCH_PYTHON to a Python that has PyYAML installed."
    return 1
  fi
  printf 'Run "%s -m pip install -r %s" now? [y/N]: ' "$py" "$REPO_ROOT/requirements.txt"
  local answer
  read -r answer || answer=""
  case "$answer" in
    y|Y|yes|YES)
      "$py" -m pip install -r "$REPO_ROOT/requirements.txt"
      "$py" -c 'import yaml' >/dev/null 2>&1 || die "PyYAML still unavailable after install"
      ;;
    *)
      warn "Set RESEARCH_PYTHON or install requirements before running skill scripts."
      return 1
      ;;
  esac
}

source_commit() {
  git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf ''
}

file_sha256() {
  if is_command shasum; then
    shasum -a 256 "$1" | awk '{ print $1 }'
  elif is_command sha256sum; then
    sha256sum "$1" | awk '{ print $1 }'
  else
    python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
  fi
}

manifest_is_ours() {
  [ -f "$1" ] || return 1
  python3 - "$1" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if (
    data.get("schema") == 1
    and data.get("install_name") == "workspace-oss"
    and data.get("install_mode") == "copy-project"
    and isinstance(data.get("files"), dict)
):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

manifest_field() {
  local manifest=$1 field=$2
  python3 - "$manifest" "$field" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
value = data.get(sys.argv[2], "")
if value is None:
    value = ""
print(value)
PY
}

manifest_agent_enabled() {
  local manifest=$1 agent=$2
  python3 - "$manifest" "$agent" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
agent = sys.argv[2]
agents = data.get("agents")
if not isinstance(agents, dict):
    enabled = agent == "claude"
else:
    enabled = bool(agents.get(agent, False))
print("1" if enabled else "0")
PY
}

guard_agents_md_for_copy_install() {
  local target expected actual_link actual_abs expected_abs
  target="$WORKSPACE_ROOT/AGENTS.md"
  [ -e "$target" ] || [ -L "$target" ] || return 0
  expected="$REPO_ROOT/AGENTS.md"
  if [ -L "$target" ]; then
    actual_link=$(readlink "$target")
    case $actual_link in
      /*) actual_abs=$actual_link ;;
      *) actual_abs=$WORKSPACE_ROOT/$actual_link ;;
    esac
    expected_abs=$(cd -P -- "$(dirname -- "$expected")" >/dev/null 2>&1 && pwd)/$(basename -- "$expected")
    if [ "$(cd -P -- "$(dirname -- "$actual_abs")" >/dev/null 2>&1 && pwd 2>/dev/null || true)/$(basename -- "$actual_abs")" = "$expected_abs" ]; then
      return 0
    fi
    die "AGENTS.md already exists in $WORKSPACE_ROOT and is not a workspace-oss artifact; resolve the conflict before installing"
  fi
  die "AGENTS.md already exists in $WORKSPACE_ROOT; move or merge it before installing"
}

guard_copy_install_target() {
  if [ -L "$WORKSPACE_ROOT/.agents" ]; then
    die "legacy symlink install detected at $WORKSPACE_ROOT/.agents; run uninstall for the old install first, then install again"
  fi
  if [ -d "$WORKSPACE_ROOT/.agents" ]; then
    if manifest_is_ours "$MANIFEST_PATH"; then
      die "copy-project install already exists at $WORKSPACE_ROOT; use: bash install.sh update --project $(quote_path "$WORKSPACE_ROOT")"
    fi
    die "foreign .agents directory exists at $WORKSPACE_ROOT/.agents; not overwriting it"
  fi
  if [ -e "$WORKSPACE_ROOT/.agents" ]; then
    die "foreign .agents path exists at $WORKSPACE_ROOT/.agents; not overwriting it"
  fi
  guard_agents_md_for_copy_install
}

ws_sync() {
  local action=$1 commit agent_csv args=()
  shift || true
  commit=$(source_commit)
  args=("$action" "--repo" "$REPO_ROOT" "--dir" "$WORKSPACE_ROOT" "--source-commit" "$commit")
  if [ "$action" = "install" ]; then
    agent_csv=""
    [ "$CONFIG_CLAUDE" -eq 1 ] && agent_csv="claude"
    if [ "$CONFIG_CODEX" -eq 1 ]; then
      if [ -n "$agent_csv" ]; then
        agent_csv="$agent_csv,codex"
      else
        agent_csv="codex"
      fi
    fi
    args+=("--agents" "$agent_csv")
  fi
  if [ -n "$SYNC_SOURCE" ]; then
    args+=("--source" "$SYNC_SOURCE")
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    args+=("--dry-run")
  fi
  if [ "$FORCE" -eq 1 ]; then
    args+=("--force")
  fi
  python3 "$REPO_ROOT/install-lib/ws_sync.py" "${args[@]}" "$@"
}

sync_workspace_copy() {
  [ "$COPY_PROJECT" -eq 1 ] || return 0
  guard_copy_install_target
  ws_sync install
}

update_workspace_copy() {
  [ "$COPY_PROJECT" -eq 1 ] || die "update requires an external project copy install"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "update requires a real managed .agents directory"
  manifest_is_ours "$MANIFEST_PATH" || die "update requires a valid workspace-oss manifest; run install for new workspaces or fix the manifest"
  ws_sync update
}

remove_agents_md_if_managed() {
  local mode sha actual
  [ -f "$MANIFEST_PATH" ] || return 0
  mode=$(manifest_field "$MANIFEST_PATH" agents_md)
  sha=$(manifest_field "$MANIFEST_PATH" agents_md_sha)
  [ "$mode" = "managed" ] || {
    warn "preserving AGENTS.md because manifest marks it as user-managed"
    return 0
  }
  [ -f "$WORKSPACE_ROOT/AGENTS.md" ] || return 0
  actual=$(file_sha256 "$WORKSPACE_ROOT/AGENTS.md")
  if [ -n "$sha" ] && [ "$actual" = "$sha" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      info "[dry-run] rm $(quote_path "$WORKSPACE_ROOT/AGENTS.md")"
    else
      rm "$WORKSPACE_ROOT/AGENTS.md"
    fi
  else
    warn "preserving modified AGENTS.md in $WORKSPACE_ROOT"
  fi
}

uninstall_workspace_copy() {
  local had_manifest=0
  [ "$COPY_PROJECT" -eq 1 ] || die "copy-project uninstall requires an external project workspace"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "copy-project uninstall requires a real managed .agents directory"
  manifest_is_ours "$MANIFEST_PATH" || die "copy-project uninstall requires a valid workspace-oss manifest"
  had_manifest=1
  remove_symlink_if_matches "$WORKSPACE_ROOT/.claude/skills" "../.agents/skills" "$SKILLS_SRC"
  remove_managed_block "$WORKSPACE_ROOT/CLAUDE.md"
  remove_agents_md_if_managed
  ws_sync uninstall
  uninstall_kb_on_path
  [ "$had_manifest" -eq 1 ] && info "Preserved $WORKSPACE_ROOT/kb and $WORKSPACE_ROOT/.venv if present; workspace is now unmanaged."
}

ensure_dir() {
  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] mkdir -p $(quote_path "$1")"
  else
    mkdir -p "$1"
  fi
}

link_force() {
  local target=$1 link=$2
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    warn "skip non-symlink path: $link"
    return 0
  fi
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$target" ]; then
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] ln -sfn $(quote_path "$target") $(quote_path "$link")"
  else
    ln -sfn "$target" "$link"
  fi
}

remove_symlink_if_matches() {
  local link=$1 expected=$2 expected_alt=${3:-}
  local actual
  [ -L "$link" ] || return 0
  actual=$(readlink "$link")
  if [ "$actual" = "$expected" ] || { [ -n "$expected_alt" ] && [ "$actual" = "$expected_alt" ]; }; then
    if [ "$DRY_RUN" -eq 1 ]; then
      info "[dry-run] rm $(quote_path "$link")"
    else
      rm "$link"
    fi
  else
    warn "skip symlink with unexpected target: $link -> $actual"
  fi
}

write_managed_block() {
  local file=$1 block_file=$2 tmp_file
  tmp_file=$(mktemp "${TMPDIR:-/tmp}/${INSTALL_NAME}.XXXXXX")
  if [ -f "$file" ]; then
    awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v block_file="$block_file" '
      BEGIN {
        while ((getline line < block_file) > 0) {
          block = block line ORS
        }
        close(block_file)
      }
      $0 == begin {
        printf "%s", block
        in_block = 1
        replaced = 1
        next
      }
      $0 == end {
        in_block = 0
        next
      }
      !in_block { print }
      END {
        if (!replaced) {
          if (NR > 0) {
            print ""
          }
          printf "%s", block
        }
      }
    ' "$file" >"$tmp_file"
  else
    awk '{ print }' "$block_file" >"$tmp_file"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] write managed block in $(quote_path "$file")"
    rm -f "$tmp_file"
  elif [ -f "$file" ] && cmp -s "$file" "$tmp_file"; then
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$file"
  fi
}

remove_managed_block() {
  local file=$1 tmp_file
  [ -f "$file" ] || return 0
  tmp_file=$(mktemp "${TMPDIR:-/tmp}/${INSTALL_NAME}.XXXXXX")
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { in_block = 1; removed = 1; next }
    $0 == end { in_block = 0; next }
    !in_block { print }
    END {
      if (!removed) {
        exit 2
      }
    }
  ' "$file" >"$tmp_file" || {
    local status=$?
    rm -f "$tmp_file"
    [ "$status" -eq 2 ] && return 0
    return "$status"
  }
  if [ "$DRY_RUN" -eq 1 ]; then
    info "[dry-run] remove managed block from $(quote_path "$file")"
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$file"
  fi
}

build_claude_block() {
  local mode=$1 ws=$2 block_file
  block_file=$(mktemp "${TMPDIR:-/tmp}/${INSTALL_NAME}.block.XXXXXX")
  {
    printf '%s\n' "$BEGIN_MARKER"
    printf '<!-- Managed by workspace-oss install.sh. AGENTS.md is the source of truth; refresh this block by rerunning install.sh. -->\n'
    if [ "$mode" = "include" ]; then
      printf '@AGENTS.md\n'
    else
      printf '<!-- Generated from %s/AGENTS.md for workspace %s. -->\n\n' "$REPO_ROOT" "$ws"
      sed -n '1,$p' "$REPO_ROOT/AGENTS.md"
    fi
    printf '%s\n' "$END_MARKER"
  } >"$block_file"
  printf '%s\n' "$block_file"
}

install_claude_project() {
  local claude_dir link_target block_file
  claude_dir="$WORKSPACE_ROOT/.claude"
  ensure_dir "$claude_dir"
  # Self-contained workspaces keep .agents and AGENTS.md in the workspace root,
  # so Claude can use an include block plus a relative skills symlink.
  if [ "$SELF_CONTAINED" -eq 1 ]; then
    link_target="../.agents/skills"
    block_file=$(build_claude_block include "$WORKSPACE_ROOT")
  else
    link_target="$SKILLS_SRC"
    block_file=$(build_claude_block copy "$WORKSPACE_ROOT")
  fi
  link_force "$link_target" "$claude_dir/skills"
  write_managed_block "$WORKSPACE_ROOT/CLAUDE.md" "$block_file"
  rm -f "$block_file"
}

uninstall_claude_project() {
  local expected
  if [ "$SELF_CONTAINED" -eq 1 ]; then
    expected="../.agents/skills"
  else
    expected="$SKILLS_SRC"
  fi
  remove_symlink_if_matches "$WORKSPACE_ROOT/.claude/skills" "$expected" "$SKILLS_SRC"
  remove_managed_block "$WORKSPACE_ROOT/CLAUDE.md"
}

install_claude_system() {
  local skill name block_file
  ensure_dir "$HOME/.claude/skills"
  # System scope links each skill back to the repo so __file__.resolve() can
  # still find the sibling .agents/lib in the source checkout.
  for skill in "$SKILLS_SRC"/*; do
    [ -d "$skill" ] || continue
    name=${skill##*/}
    link_force "$skill" "$HOME/.claude/skills/$name"
  done
  block_file=$(build_claude_block copy "$HOME/.claude")
  write_managed_block "$HOME/.claude/CLAUDE.md" "$block_file"
  rm -f "$block_file"
  info "Set RESEARCH_SKILLS_HOME=$REPO_ROOT when running skills outside this repo."
  info "Use RESEARCH_PROJECT_ROOT=<kb-workspace> or kb --root <kb-workspace> for the target KB."
}

uninstall_claude_system() {
  local skill name
  for skill in "$SKILLS_SRC"/*; do
    [ -d "$skill" ] || continue
    name=${skill##*/}
    remove_symlink_if_matches "$HOME/.claude/skills/$name" "$skill"
  done
  remove_managed_block "$HOME/.claude/CLAUDE.md"
}

install_codex_project() {
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
    info "Codex project scope: AGENTS.md and .agents/ are already present in $REPO_ROOT."
    return 0
  fi
  # External project scope is self-contained: the shared copy step installed the
  # full .agents tree plus AGENTS.md, preserving sibling imports under DIR.
  info "Codex project scope: .agents/ and AGENTS.md are managed copies in $WORKSPACE_ROOT."
}

uninstall_codex_project() {
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
    return 0
  fi
  if [ -L "$WORKSPACE_ROOT/.agents" ]; then
    remove_symlink_if_matches "$WORKSPACE_ROOT/.agents" "$REPO_ROOT/.agents"
  elif [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -f "$MANIFEST_PATH" ]; then
    warn "foreign .agents directory has no workspace-oss manifest; preserving it"
  fi
  remove_symlink_if_matches "$WORKSPACE_ROOT/AGENTS.md" "$REPO_ROOT/AGENTS.md"
}

install_codex_system() {
  local global_dir skill name
  global_dir="$HOME/.codex/$INSTALL_NAME"
  ensure_dir "$global_dir"
  link_force "$REPO_ROOT/.agents" "$global_dir/.agents"
  link_force "$REPO_ROOT/AGENTS.md" "$global_dir/AGENTS.md"
  if [ -d "$HOME/.codex/skills" ]; then
    for skill in "$SKILLS_SRC"/*; do
      [ -d "$skill" ] || continue
      name=${skill##*/}
      link_force "$skill" "$HOME/.codex/skills/$name"
    done
  else
    warn "Codex has no documented ~/.codex/skills system-scope directory; not creating one."
  fi
  info "Codex system-scope is best-effort: use RESEARCH_SKILLS_HOME=$REPO_ROOT plus a workspace-local AGENTS.md."
}

uninstall_codex_system() {
  local global_dir skill name
  global_dir="$HOME/.codex/$INSTALL_NAME"
  remove_symlink_if_matches "$global_dir/.agents" "$REPO_ROOT/.agents"
  remove_symlink_if_matches "$global_dir/AGENTS.md" "$REPO_ROOT/AGENTS.md"
  rmdir "$global_dir" >/dev/null 2>&1 || true
  if [ -d "$HOME/.codex/skills" ]; then
    for skill in "$SKILLS_SRC"/*; do
      [ -d "$skill" ] || continue
      name=${skill##*/}
      remove_symlink_if_matches "$HOME/.codex/skills/$name" "$skill"
    done
  fi
}

install_kb_on_path() {
  local dir link
  if [ "$SCOPE" = "system" ]; then
    dir="$HOME/.local/bin"
    WS_KB_SCRIPT="$KB_SCRIPT"
  else
    dir="$WORKSPACE_ROOT/bin"
  fi
  link="$dir/kb"
  ensure_dir "$dir"
  link_force "$WS_KB_SCRIPT" "$link"
  if ! path_on_path "$dir"; then
    warn "$dir is not on PATH; add it before running kb by name."
  fi
}

uninstall_kb_on_path() {
  local dir
  if [ "$SCOPE" = "system" ]; then
    dir="$HOME/.local/bin"
  else
    dir="$WORKSPACE_ROOT/bin"
  fi
  remove_symlink_if_matches "$dir/kb" "$WS_KB_SCRIPT" "$KB_SCRIPT"
}

run_smoke() {
  if [ "$DRY_RUN" -eq 1 ] || [ "$ACTION" != "install" ]; then
    return 0
  fi
  info "Smoke: kb help"
  "$WS_KB_SCRIPT" help >/dev/null
  info "Smoke: kb --root $(quote_path "$WORKSPACE_ROOT") doctor"
  if [ "$COPY_PROJECT" -eq 1 ]; then
    "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor >/dev/null
  else
    RESEARCH_SKILLS_HOME="$REPO_ROOT" "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor >/dev/null
  fi
}

if [ "$ACTION" != "uninstall" ]; then
  preflight_yaml
fi

case "$ACTION" in
  install)
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ]; then
      sync_workspace_copy
    fi
    if [ "$CONFIG_CLAUDE" -eq 1 ]; then
      if [ "$SCOPE" = "system" ]; then
        install_claude_system
      else
        install_claude_project
      fi
    fi
    if [ "$CONFIG_CODEX" -eq 1 ]; then
      if [ "$SCOPE" = "system" ]; then
        install_codex_system
      else
        install_codex_project
      fi
    fi
    [ "$KB_ON_PATH" -eq 1 ] && install_kb_on_path
    run_smoke
    info "Install complete."
    ;;
  update)
    UPDATE_CONFIG_CLAUDE=0
    UPDATE_CONFIG_CODEX=0
    update_workspace_copy
    UPDATE_CONFIG_CLAUDE=$(manifest_agent_enabled "$MANIFEST_PATH" claude 2>/dev/null || printf '1')
    UPDATE_CONFIG_CODEX=$(manifest_agent_enabled "$MANIFEST_PATH" codex 2>/dev/null || printf '0')
    if [ "$UPDATE_CONFIG_CLAUDE" = "1" ]; then
      install_claude_project
    fi
    if [ "$UPDATE_CONFIG_CODEX" = "1" ]; then
      install_codex_project
    fi
    [ "$KB_ON_PATH" -eq 1 ] && install_kb_on_path
    info "Update complete."
    ;;
  uninstall)
    CORRUPT_MANIFEST_UNINSTALL=0
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ] && [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] && manifest_is_ours "$MANIFEST_PATH"; then
      uninstall_workspace_copy
      info "Uninstall complete."
      exit 0
    fi
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ] && [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] && [ -f "$MANIFEST_PATH" ]; then
      warn "uninstall found invalid or damaged workspace-oss manifest: $MANIFEST_PATH"
      warn "preserving $WORKSPACE_ROOT/.agents because the manifest cannot be trusted"
      CORRUPT_MANIFEST_UNINSTALL=1
    fi
    if [ "$CONFIG_CLAUDE" -eq 1 ]; then
      if [ "$SCOPE" = "system" ]; then
        uninstall_claude_system
      else
        uninstall_claude_project
      fi
    fi
    if [ "$CONFIG_CODEX" -eq 1 ]; then
      if [ "$SCOPE" = "system" ]; then
        uninstall_codex_system
      else
        uninstall_codex_project
      fi
    fi
    [ "$KB_ON_PATH" -eq 1 ] && uninstall_kb_on_path
    if [ "$CORRUPT_MANIFEST_UNINSTALL" -eq 1 ]; then
      warn "manifest was invalid; .agents was retained for manual inspection, and kb/.venv were not touched"
    fi
    info "Uninstall complete."
    ;;
  *)
    die "unknown action: $ACTION"
    ;;
esac
