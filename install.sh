#!/usr/bin/env bash
set -euo pipefail

BEGIN_MARKER="# >>> workspace-oss managed >>>"
END_MARKER="# <<< workspace-oss managed <<<"
INSTALL_NAME="workspace-oss"

usage() {
  cat <<'EOF'
Usage: bash install.sh [options]

Configure Open Research Workspace Skills for Claude Code and/or Codex.

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
  --uninstall           Remove managed blocks and symlinks created by this script.
  -h, --help            Show this help.

Examples:
  bash install.sh --claude --project .
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

DRY_RUN=0
UNINSTALL=0
CONFIG_CLAUDE=0
CONFIG_CODEX=0
AGENT_FLAG_SET=0
SCOPE=""
PROJECT_DIR=""
KB_ON_PATH=0

REPO_ROOT=$(script_dir)
[ -d "$REPO_ROOT/.agents/lib" ] || die "could not find .agents/lib next to install.sh"
[ -d "$REPO_ROOT/.agents/skills" ] || die "could not find .agents/skills next to install.sh"
[ -f "$REPO_ROOT/AGENTS.md" ] || die "could not find AGENTS.md next to install.sh"

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
      UNINSTALL=1
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

if [ -z "$PROJECT_DIR" ]; then
  PROJECT_DIR=$(pwd)
fi
WORKSPACE_ROOT=$(abs_dir "$PROJECT_DIR")
SKILLS_SRC="$REPO_ROOT/.agents/skills"
KB_SCRIPT="$REPO_ROOT/.agents/skills/kb-cli/scripts/kb"

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
  prompt_agent_selection
fi
[ "$CONFIG_CLAUDE" -eq 1 ] || [ "$CONFIG_CODEX" -eq 1 ] || die "no agents selected"

if [ -z "$SCOPE" ]; then
  prompt_scope
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
  # Hard invariant: skill directories are symlinked, never copied. The scripts
  # resolve __file__ through symlinks and walk back to the real .agents/lib.
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
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
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
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
  # Hard invariant: each system-scope skill is a symlink to the repo skill dir,
  # never a copy, so __file__.resolve() can still find the sibling .agents/lib.
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
  # External workspaces get symlinks back to this repo. Do not copy .agents:
  # copied skill dirs break the walk-up import path for .agents/lib.
  link_force "$REPO_ROOT/.agents" "$WORKSPACE_ROOT/.agents"
  if [ -e "$WORKSPACE_ROOT/AGENTS.md" ] && [ ! -L "$WORKSPACE_ROOT/AGENTS.md" ]; then
    warn "AGENTS.md already exists in $WORKSPACE_ROOT; leaving it unchanged."
    warn "Add workspace-oss rules manually or run Codex from $REPO_ROOT."
  else
    link_force "$REPO_ROOT/AGENTS.md" "$WORKSPACE_ROOT/AGENTS.md"
  fi
  info "For external Codex workspaces, set RESEARCH_SKILLS_HOME=$REPO_ROOT."
}

uninstall_codex_project() {
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
    return 0
  fi
  remove_symlink_if_matches "$WORKSPACE_ROOT/.agents" "$REPO_ROOT/.agents"
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
  else
    dir="$WORKSPACE_ROOT/bin"
  fi
  link="$dir/kb"
  ensure_dir "$dir"
  link_force "$KB_SCRIPT" "$link"
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
  remove_symlink_if_matches "$dir/kb" "$KB_SCRIPT"
}

run_smoke() {
  if [ "$DRY_RUN" -eq 1 ] || [ "$UNINSTALL" -eq 1 ]; then
    return 0
  fi
  info "Smoke: kb help"
  "$KB_SCRIPT" help >/dev/null
  info "Smoke: kb --root $(quote_path "$WORKSPACE_ROOT") status"
  RESEARCH_SKILLS_HOME="$REPO_ROOT" "$KB_SCRIPT" --root "$WORKSPACE_ROOT" status >/dev/null
}

if [ "$UNINSTALL" -eq 0 ]; then
  preflight_yaml
fi

if [ "$UNINSTALL" -eq 1 ]; then
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
  info "Uninstall complete."
  exit 0
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
