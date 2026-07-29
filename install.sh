#!/usr/bin/env bash
set -euo pipefail

BEGIN_MARKER="# >>> workspace-oss managed >>>"
END_MARKER="# <<< workspace-oss managed <<<"
INSTALL_NAME="workspace-oss"

is_command() {
  command -v "$1" >/dev/null 2>&1
}

C_RESET=""
C_BOLD=""
C_DIM=""
C_RED=""
C_GREEN=""
C_YELLOW=""
C_BLUE=""
C_CYAN=""

if [ -t 1 ] && [ -t 2 ] && [ "${TERM:-}" != "dumb" ] && [ -z "${NO_COLOR:-}" ] && is_command tput; then
  COLOR_COUNT=$(tput colors 2>/dev/null || printf '0')
  case $COLOR_COUNT in
    ''|*[!0-9]*) COLOR_COUNT=0 ;;
  esac
  if [ "$COLOR_COUNT" -ge 8 ]; then
    C_RESET=$(tput sgr0 2>/dev/null || printf '')
    C_BOLD=$(tput bold 2>/dev/null || printf '')
    C_DIM=$(tput dim 2>/dev/null || printf '')
    C_RED=$(tput setaf 1 2>/dev/null || printf '')
    C_GREEN=$(tput setaf 2 2>/dev/null || printf '')
    C_YELLOW=$(tput setaf 3 2>/dev/null || printf '')
    C_BLUE=$(tput setaf 4 2>/dev/null || printf '')
    C_CYAN=$(tput setaf 6 2>/dev/null || printf '')
  fi
fi
unset COLOR_COUNT

OK="✓"
ERR="✗"
DOT="•"
ARROW="→"
WARN="!"

hr() {
  local cols
  cols=64
  if [ -t 1 ] && is_command tput; then
    cols=$(tput cols 2>/dev/null || printf '64')
    case $cols in
      ''|*[!0-9]*) cols=64 ;;
    esac
  fi
  [ "$cols" -gt 72 ] && cols=72
  [ "$cols" -lt 12 ] && cols=12
  printf '%b' "$C_DIM"
  printf '%*s\n' "$cols" '' | tr ' ' '-'
  printf '%b' "$C_RESET"
}

title() {
  hr
  printf '%bResearch Workspace Skills%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
  if [ "$#" -gt 0 ]; then
    printf '%b%s%b\n' "$C_DIM" "$*" "$C_RESET"
  fi
  hr
}

section() {
  printf '\n%b%s%b\n' "$C_BOLD" "$*" "$C_RESET"
}

step() {
  printf '\n%b步骤 %s%b  %s\n' "$C_BOLD$C_CYAN" "$1" "$C_RESET" "$2"
}

ok() {
  printf '%b%s%b %s\n' "$C_GREEN" "$OK" "$C_RESET" "$*"
}

fail() {
  printf '%b%s%b %s\n' "$C_RED" "$ERR" "$C_RESET" "$*"
}

note() {
  printf '%b%s%b %s\n' "$C_YELLOW" "$WARN" "$C_RESET" "$*"
}

bullet() {
  printf '%b%s%b %s\n' "$C_DIM" "$DOT" "$C_RESET" "$*"
}

menu_option() {
  local number=$1 label=$2 hint=${3:-}
  printf '  %b%s)%b %s' "$C_CYAN" "$number" "$C_RESET" "$label"
  if [ -n "$hint" ]; then
    printf ' %b%s%b' "$C_DIM" "$hint" "$C_RESET"
  fi
  printf '\n'
}

ask() {
  printf '%b%s%b %s' "$C_CYAN" "$ARROW" "$C_RESET" "$*"
}

usage_option() {
  printf '  %-23s %s\n' "$1" "$2"
}

usage() {
  title "安装、更新、重装或卸载 Claude Code / Codex 研究技能"
  printf '%b第一次使用：%b直接运行 %bbash install.sh%b，按提示选择即可。\n' "$C_BOLD" "$C_RESET" "$C_CYAN" "$C_RESET"
  printf '用法：bash install.sh [install|update|reinstall|uninstall] [选项]\n'

  section "选择 AI 工具"
  usage_option "--claude" "仅配置 Claude Code"
  usage_option "--codex" "仅配置 Codex"
  usage_option "--all" "同时配置 Claude Code 和 Codex"

  section "选择安装范围"
  usage_option "--project [DIR]" "仅配置一个工作区；DIR 默认为当前目录"
  usage_option "--system" "为当前用户做系统级配置"

  section "其他选项"
  usage_option "--kb-on-path" "创建可在终端使用的 kb 快捷命令"
  usage_option "--dry-run" "只预览，不写入文件"
  usage_option "--agent-plan-json FILE" "供 Agent 审阅：零写预览，并把精确计划保存为 JSON"
  usage_option "--force" "更新时覆盖已修改的受管文件"
  usage_option "--from-snapshot" "源码不是 git 仓库时按快照清单打包（无法区分未跟踪文件）"
  usage_option "--source DIR" "从指定源码目录更新"
  usage_option "--expected-source-commit SHA" "应用 Agent 计划时锁定已审阅的源码版本"
  usage_option "--yes, --assume-yes" "交互运行时跳过执行前确认"
  usage_option "--uninstall" "兼容旧版的卸载选项"
  usage_option "-h, --help" "显示帮助"

  section "常用示例"
  bullet "首次安装：bash install.sh"
  bullet "预览安装：bash install.sh --dry-run --claude --project ."
  bullet "更新外部工作区：bash install.sh update --project /path/to/workspace"
  bullet "重装外部工作区：bash install.sh reinstall --project /path/to/workspace"
  bullet "卸载外部工作区：bash install.sh uninstall --project /path/to/workspace"

  printf '\n%b说明：%bCI 或非交互环境不会等待输入，请传入 AI 工具和安装范围。\n' "$C_BOLD" "$C_RESET"
  printf '设置 NO_COLOR=1 可关闭颜色。\n'
}

die() {
  printf '%b%s 错误：%b%s\n' "$C_RED" "$ERR" "$C_RESET" "$*" >&2
  exit 1
}

warn() {
  printf '%b%s%b %s\n' "$C_YELLOW" "$WARN" "$C_RESET" "$*" >&2
}

info() {
  printf '%s\n' "$*"
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
  [ -d "$1" ] || die "目录不存在：$1"
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

same_dir() {
  [ "$(abs_dir "$1")" = "$(abs_dir "$2")" ]
}

claude_links_to_workspace_agents() {
  local file=$1 actual candidate candidate_dir expected expected_dir
  [ -L "$file" ] || return 1
  actual=$(readlink "$file")
  case $actual in
    /*) candidate=$actual ;;
    *) candidate=$(dirname -- "$file")/$actual ;;
  esac
  candidate_dir=$(cd -P -- "$(dirname -- "$candidate")" >/dev/null 2>&1 && pwd) || return 1
  expected="$WORKSPACE_ROOT/AGENTS.md"
  expected_dir=$(cd -P -- "$(dirname -- "$expected")" >/dev/null 2>&1 && pwd) || return 1
  [ "$candidate_dir/$(basename -- "$candidate")" = "$expected_dir/$(basename -- "$expected")" ]
}

guard_claude_project_target() {
  local target="$WORKSPACE_ROOT/CLAUDE.md" effective_claude
  [ "$CONFIG_CLAUDE" -eq 1 ] || return 0
  [ "$SCOPE" != "system" ] || return 0
  effective_claude=$CONFIG_CLAUDE
  if [ "$ACTION" != "install" ] && manifest_is_ours "$MANIFEST_PATH"; then
    effective_claude=$(manifest_agent_enabled "$MANIFEST_PATH" claude 2>/dev/null || printf '1')
  fi
  [ "$effective_claude" = "1" ] || return 0
  [ -L "$target" ] || return 0
  claude_links_to_workspace_agents "$target" || \
    die "检测到指向其它位置的 Claude 配置链接；为避免跟随或替换链接，已停止"
}

ACTION=install
ACTION_FROM_SUBCOMMAND=0
ACTION_EXPLICIT=0
DRY_RUN=0
AGENT_PLAN=0
AGENT_PLAN_JSON=""
CONFIG_CLAUDE=0
CONFIG_CODEX=0
AGENT_FLAG_SET=0
SCOPE=""
PROJECT_DIR=""
PROJECT_FLAG_SET=0
KB_ON_PATH=0
KB_ON_PATH_FLAG_SET=0
FORCE=0
FROM_SNAPSHOT=0
SYNC_SOURCE=""
EXPECTED_SOURCE_COMMIT=""
APPLY_AGENT_PLAN=""
EXPECTED_PLAN_DIGEST=""
EXPECTED_PLAN_BYTE_SHA256=""
EXPECTED_SOURCE_TREE_DIGEST=""
VERIFIED_MANIFEST_STATE=""
AGENT_PLAN_MANIFEST_STATE=""
OPERATION_TIME=""
ASSUME_YES=0
WIZARD_MODE=0
WIZARD_STEP=0
INSTALL_INCOMPLETE=0
KB_SHORTCUT_CREATED=0
KB_SHORTCUT_AVAILABLE=0
UPDATE_NO_CHANGES=0
DRY_RUN_CHANGE_COUNT=0
RUNTIME_BOOTSTRAP_NEEDED=0
DISCOVERED_RUNTIME_PYTHON=""
SELECTED_RUNTIME_PYTHON=""
SELECTED_RUNTIME_SOURCE=""
SELECTED_RUNTIME_ISOLATED=0
AGENT_PLAN_TARGET_ARGS=()
AGENT_PLAN_TARGET_JSON=()
AGENT_PLAN_TARGET_SEQUENCE=()
AGENT_PLAN_CONFLICTS=()

REPO_ROOT=$(script_dir)
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
  esac
done

[ -d "$REPO_ROOT/.agents/lib" ] || die "安装包不完整：缺少 .agents/lib"
[ -d "$REPO_ROOT/.agents/skills" ] || die "安装包不完整：缺少 .agents/skills"
[ -f "$REPO_ROOT/.agents/AGENTS.md" ] || die "安装包不完整：缺少 .agents/AGENTS.md"
[ -f "$REPO_ROOT/.agents/AGENT_GUIDE.md" ] || die "安装包不完整：缺少 .agents/AGENT_GUIDE.md"
[ -f "$REPO_ROOT/install-lib/ws_sync.py" ] || die "安装包不完整：缺少 install-lib/ws_sync.py"
is_command python3 || die "需要 Python 3，请安装后重试"

if [ "$#" -gt 0 ]; then
  case "$1" in
    install|update|reinstall|uninstall)
      ACTION=$1
      ACTION_FROM_SUBCOMMAND=1
      ACTION_EXPLICIT=1
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
    --agent-plan)
      DRY_RUN=1
      AGENT_PLAN=1
      shift
      ;;
    --agent-plan-json)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--agent-plan-json 需要一个输出文件"
      DRY_RUN=1
      AGENT_PLAN=1
      AGENT_PLAN_JSON=$2
      shift 2
      ;;
    --agent-plan-json=*)
      DRY_RUN=1
      AGENT_PLAN=1
      AGENT_PLAN_JSON=${1#--agent-plan-json=}
      [ -n "$AGENT_PLAN_JSON" ] || die "--agent-plan-json 需要一个输出文件"
      shift
      ;;
    --uninstall)
      ACTION=uninstall
      ACTION_EXPLICIT=1
      shift
      ;;
    --yes|--assume-yes)
      ASSUME_YES=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --from-snapshot)
      FROM_SNAPSHOT=1
      shift
      ;;
    --source)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--source 需要一个目录"
      SYNC_SOURCE=$2
      shift 2
      ;;
    --source=*)
      SYNC_SOURCE=${1#--source=}
      shift
      ;;
    --expected-source-commit)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--expected-source-commit 需要一个 commit"
      EXPECTED_SOURCE_COMMIT=$2
      shift 2
      ;;
    --expected-source-commit=*)
      EXPECTED_SOURCE_COMMIT=${1#--expected-source-commit=}
      [ -n "$EXPECTED_SOURCE_COMMIT" ] || die "--expected-source-commit 需要一个 commit"
      shift
      ;;
    --apply-agent-plan)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--apply-agent-plan 需要一个计划文件"
      APPLY_AGENT_PLAN=$2
      shift 2
      ;;
    --apply-agent-plan=*)
      APPLY_AGENT_PLAN=${1#--apply-agent-plan=}
      [ -n "$APPLY_AGENT_PLAN" ] || die "--apply-agent-plan 需要一个计划文件"
      shift
      ;;
    --expected-plan-digest)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--expected-plan-digest 需要一个 digest"
      EXPECTED_PLAN_DIGEST=$2
      shift 2
      ;;
    --expected-plan-digest=*)
      EXPECTED_PLAN_DIGEST=${1#--expected-plan-digest=}
      [ -n "$EXPECTED_PLAN_DIGEST" ] || die "--expected-plan-digest 需要一个 digest"
      shift
      ;;
    --expected-plan-byte-sha256)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--expected-plan-byte-sha256 需要一个 digest"
      EXPECTED_PLAN_BYTE_SHA256=$2
      shift 2
      ;;
    --expected-plan-byte-sha256=*)
      EXPECTED_PLAN_BYTE_SHA256=${1#--expected-plan-byte-sha256=}
      [ -n "$EXPECTED_PLAN_BYTE_SHA256" ] || die "--expected-plan-byte-sha256 需要一个 digest"
      shift
      ;;
    --expected-source-tree-digest)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--expected-source-tree-digest 需要一个 digest"
      EXPECTED_SOURCE_TREE_DIGEST=$2
      shift 2
      ;;
    --expected-source-tree-digest=*)
      EXPECTED_SOURCE_TREE_DIGEST=${1#--expected-source-tree-digest=}
      [ -n "$EXPECTED_SOURCE_TREE_DIGEST" ] || die "--expected-source-tree-digest 需要一个 digest"
      shift
      ;;
    --operation-time)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--operation-time 需要一个 UTC 时间"
      OPERATION_TIME=$2
      shift 2
      ;;
    --operation-time=*)
      OPERATION_TIME=${1#--operation-time=}
      [ -n "$OPERATION_TIME" ] || die "--operation-time 需要一个 UTC 时间"
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
      PROJECT_FLAG_SET=1
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
      PROJECT_FLAG_SET=1
      PROJECT_DIR=${1#--project=}
      shift
      ;;
    --system)
      SCOPE=system
      shift
      ;;
    --kb-on-path)
      KB_ON_PATH=1
      KB_ON_PATH_FLAG_SET=1
      shift
      ;;
    *)
      die "无法识别的选项：$1（可用 --help 查看帮助）"
      ;;
  esac
done

if [ "$AGENT_PLAN" -eq 1 ] && [ -z "$AGENT_PLAN_JSON" ]; then
  die "--agent-plan 需要配合 --agent-plan-json FILE，以免把大量内部路径输出到终端"
fi
if [ -n "$APPLY_AGENT_PLAN$EXPECTED_PLAN_DIGEST$EXPECTED_PLAN_BYTE_SHA256$EXPECTED_SOURCE_TREE_DIGEST" ]; then
  [ -n "$APPLY_AGENT_PLAN" ] && [ -n "$EXPECTED_PLAN_DIGEST" ] && [ -n "$EXPECTED_PLAN_BYTE_SHA256" ] && [ -n "$EXPECTED_SOURCE_TREE_DIGEST" ] && [ -n "$EXPECTED_SOURCE_COMMIT" ] || \
    die "应用 Agent 计划时必须同时提供已审阅计划及其绑定信息"
  [ "$AGENT_PLAN" -eq 0 ] || die "不能同时生成并应用 Agent 计划"
fi
if [ "$AGENT_PLAN" -eq 1 ] && [ -z "$OPERATION_TIME" ]; then
  OPERATION_TIME=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
fi

# Installer preflight and smoke imports are implementation details, not durable
# workspace targets.  Suppress them for both planning and the matching apply so
# an Agent plan does not omit a dynamic __pycache__ tree.
export PYTHONDONTWRITEBYTECODE=1

is_interactive_input() {
  [ -t 0 ] && [ -z "${CI:-}" ]
}

wizard_step() {
  WIZARD_STEP=$((WIZARD_STEP + 1))
  step "$WIZARD_STEP" "$1"
}

agent_label() {
  if [ "$CONFIG_CLAUDE" -eq 1 ] && [ "$CONFIG_CODEX" -eq 1 ]; then
    printf 'Claude Code 和 Codex'
  elif [ "$CONFIG_CLAUDE" -eq 1 ]; then
    printf 'Claude Code'
  elif [ "$CONFIG_CODEX" -eq 1 ]; then
    printf 'Codex'
  else
    printf '未选择'
  fi
}

action_label() {
  case "$ACTION" in
    install) printf '安装' ;;
    update) printf '更新' ;;
    reinstall) printf '重装或修复' ;;
    uninstall) printf '卸载' ;;
  esac
}

scope_label() {
  if [ "$SCOPE" = "system" ]; then
    printf '当前用户的所有工作区'
  else
    printf '仅这个工作区'
  fi
}

mode_label() {
  if [ "$SCOPE" = "system" ]; then
    printf '系统级配置'
  elif [ "$COPY_PROJECT" -eq 1 ]; then
    printf '独立工作区'
  else
    printf '使用本仓库'
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

restore_manifest_agent_selection() {
  local manifest=$1
  CONFIG_CLAUDE=$(manifest_agent_enabled "$manifest" claude 2>/dev/null || printf '1')
  CONFIG_CODEX=$(manifest_agent_enabled "$manifest" codex 2>/dev/null || printf '0')
}

prompt_action() {
  local choice
  is_interactive_input || return 0
  wizard_step "你想做什么？"
  menu_option 1 "首次安装" "（推荐）"
  menu_option 2 "更新已安装的外部工作区"
  menu_option 3 "重装或修复已安装的外部工作区"
  menu_option 4 "卸载 skills 接入" "（保留研究资料）"
  while true; do
    ask "请选择 [1]："
    read -r choice || choice=""
    choice=${choice:-1}
    case "$choice" in
      1|install)
        ACTION=install
        return 0
        ;;
      2|update)
        ACTION=update
        ACTION_FROM_SUBCOMMAND=1
        return 0
        ;;
      3|reinstall)
        ACTION=reinstall
        ACTION_FROM_SUBCOMMAND=1
        return 0
        ;;
      4|uninstall)
        ACTION=uninstall
        return 0
        ;;
      *)
        note "请输入 1、2、3 或 4。"
        ;;
    esac
  done
}

prompt_agent_selection() {
  local default choice detected=()
  if agent_detected claude; then
    detected+=("claude")
  fi
  if agent_detected codex; then
    detected+=("codex")
  fi
  if [ "${#detected[@]}" -eq 2 ]; then
    default=3
  elif [ "${#detected[@]}" -eq 1 ]; then
    if [ "${detected[0]}" = "claude" ]; then
      default=1
    else
      default=2
    fi
  else
    default=3
  fi
  if ! is_interactive_input; then
    die "非交互运行时，请指定 --claude、--codex 或 --all"
  fi
  wizard_step "你在哪个 AI 工具里使用？"
  if [ "${#detected[@]}" -eq 2 ]; then
    info "已检测到 Claude Code 和 Codex。"
  elif [ "${#detected[@]}" -eq 1 ]; then
    if [ "${detected[0]}" = "claude" ]; then
      info "已检测到 Claude Code。"
    else
      info "已检测到 Codex。"
    fi
  else
    info "暂未检测到这两个工具，也可以先完成配置。"
  fi
  menu_option 1 "Claude Code"
  menu_option 2 "Codex"
  menu_option 3 "两者都用"
  while true; do
    ask "请选择 [$default]："
    read -r choice || choice=""
    choice=${choice:-$default}
    case "$choice" in
      1|claude)
        CONFIG_CLAUDE=1
        return 0
        ;;
      2|codex)
        CONFIG_CODEX=1
        return 0
        ;;
      3|all)
        CONFIG_CLAUDE=1
        CONFIG_CODEX=1
        return 0
        ;;
      *)
        note "请输入 1、2 或 3。"
        ;;
    esac
  done
}

prompt_scope() {
  local choice
  if [ "$ACTION" = "update" ] || [ "$ACTION" = "reinstall" ] || { [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 1 ]; }; then
    SCOPE=project
    return 0
  fi
  if ! is_interactive_input; then
    die "非交互运行时，请指定 --project [目录] 或 --system"
  fi
  wizard_step "你希望在哪里使用？"
  menu_option 1 "仅当前或指定工作区" "（推荐，项目之间互不影响）"
  menu_option 2 "当前用户的所有工作区" "（系统级）"
  while true; do
    ask "请选择 [1]："
    read -r choice || choice=""
    choice=${choice:-1}
    case "$choice" in
      1|project)
        SCOPE=project
        return 0
        ;;
      2|system)
        SCOPE=system
        return 0
        ;;
      *)
        note "请输入 1 或 2。"
        ;;
    esac
  done
}

prompt_project_dir() {
  local choice default_dir terminal_state=""
  if ! is_interactive_input; then
    return 0
  fi
  default_dir=$(pwd)
  wizard_step "研究工作区放在哪里？"
  info "知识库和运行环境会以这个目录为中心。"
  while true; do
    if terminal_state=$(stty -g <&0 2>/dev/null); then
      stty -echo <&0
      trap 'stty "$terminal_state" <&0 2>/dev/null || true; exit 130' INT
      trap 'stty "$terminal_state" <&0 2>/dev/null || true; exit 129' HUP
      trap 'stty "$terminal_state" <&0 2>/dev/null || true; exit 143' TERM
    else
      terminal_state=""
    fi
    ask "目录 [按回车使用当前目录]："
    read -r choice || choice=""
    if [ -n "$terminal_state" ]; then
      stty "$terminal_state" <&0
      trap - INT HUP TERM
    fi
    printf '\n'
    choice=${choice:-$default_dir}
    if [ -d "$choice" ]; then
      PROJECT_DIR=$(abs_dir "$choice")
      break
    fi
    note "目录不存在，请输入已有目录。"
  done
  if same_dir "$PROJECT_DIR" "$REPO_ROOT"; then
    info "将直接使用本仓库中的 skills。"
  else
    info "将为这个工作区复制一份独立的 skills 配置。"
  fi
}

prompt_existing_copy_install() {
  local choice project_root manifest
  [ "$ACTION" = "install" ] || return 0
  [ "$SCOPE" = "project" ] || return 0
  [ -n "$PROJECT_DIR" ] || return 0
  is_interactive_input || return 0

  project_root=$(abs_dir "$PROJECT_DIR")
  same_dir "$project_root" "$REPO_ROOT" && return 0
  [ -d "$project_root/.agents" ] && [ ! -L "$project_root/.agents" ] || return 0
  manifest="$project_root/.agents/.install-manifest.json"
  manifest_is_ours "$manifest" || return 0

  wizard_step "这个工作区已经安装过"
  info "请选择如何继续："
  menu_option 1 "更新" "（推荐，只同步版本变化）"
  menu_option 2 "重装或修复" "（重新铺设受管文件）"
  menu_option 3 "取消"
  while true; do
    ask "请选择 [1]："
    read -r choice || choice=""
    choice=${choice:-1}
    case "$choice" in
      1|update)
        ACTION=update
        ACTION_FROM_SUBCOMMAND=1
        break
        ;;
      2|reinstall)
        ACTION=reinstall
        ACTION_FROM_SUBCOMMAND=1
        break
        ;;
      3|cancel)
        note "已取消，没有写入任何文件。"
        exit 0
        ;;
      *)
        note "请输入 1、2 或 3。"
        ;;
    esac
  done
  restore_manifest_agent_selection "$manifest"
}

prompt_kb_on_path() {
  local choice
  if ! is_interactive_input; then
    return 0
  fi
  wizard_step "是否创建终端快捷命令？"
  info "这只影响终端；在 AI 对话中始终可以使用 kb。"
  menu_option 1 "暂不创建" "（推荐）"
  menu_option 2 "创建 kb 快捷命令"
  while true; do
    ask "请选择 [1]："
    read -r choice || choice=""
    choice=${choice:-1}
    case "$choice" in
      1|n|N|no|NO)
        KB_ON_PATH=0
        return 0
        ;;
      2|y|Y|yes|YES)
        KB_ON_PATH=1
        info "如果安装成功，终端中先运行 kb help，再运行 kb init。"
        return 0
        ;;
      *)
        note "请输入 1 或 2。"
        ;;
    esac
  done
}

if is_interactive_input; then
  if [ "$ACTION_EXPLICIT" -eq 0 ] \
    || { [ "$AGENT_FLAG_SET" -eq 0 ] && { [ "$ACTION" = "install" ] || { [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 0 ]; }; }; } \
    || [ -z "$SCOPE" ] \
    || { [ "$ACTION" = "install" ] && [ "$KB_ON_PATH_FLAG_SET" -eq 0 ]; }; then
    WIZARD_MODE=1
  fi
fi

if [ "$WIZARD_MODE" -eq 1 ]; then
  title "安装向导 · 第一次使用也能直接完成"
  info "按回车使用推荐选项。"
fi

if [ "$ACTION_EXPLICIT" -eq 0 ]; then
  prompt_action
elif [ "$WIZARD_MODE" -eq 1 ]; then
  info "操作：$(action_label)"
fi

if [ "$AGENT_FLAG_SET" -eq 0 ]; then
  if [ "$ACTION" = "install" ] || { [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 0 ]; }; then
    prompt_agent_selection
  else
    CONFIG_CLAUDE=1
    CONFIG_CODEX=1
  fi
fi
[ "$CONFIG_CLAUDE" -eq 1 ] || [ "$CONFIG_CODEX" -eq 1 ] || { [ "$ACTION" != "install" ] || die "至少选择一个 AI 工具"; }

if [ -z "$SCOPE" ]; then
  prompt_scope
fi

if [ "$SCOPE" = "project" ] && [ -z "$PROJECT_DIR" ] && [ "$PROJECT_FLAG_SET" -eq 0 ]; then
  prompt_project_dir
fi

prompt_existing_copy_install

if [ "$ACTION" = "install" ] && [ "$KB_ON_PATH_FLAG_SET" -eq 0 ] && [ "$WIZARD_MODE" -eq 1 ]; then
  prompt_kb_on_path
fi

if [ -z "$PROJECT_DIR" ]; then
  if [ "$SCOPE" = "project" ]; then
    case "$ACTION" in
      update|reinstall|uninstall)
        [ -f "$(pwd)/.agents/.install-manifest.json" ] || die "未指定 --project，且当前目录不是可识别的已安装工作区；为避免写入错误位置已停止"
        PROJECT_DIR=$(pwd)
        ;;
      *)
        die "未明确安装目标；请指定 --project [目录]，或在交互向导中选择工作区"
        ;;
    esac
  else
    PROJECT_DIR=$(pwd)
  fi
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

if [ "$ACTION" = "update" ] || [ "$ACTION" = "reinstall" ]; then
  [ "$SCOPE" = "project" ] || die "update 只适用于外部工作区；系统级配置请重新运行 install"
  [ "$COPY_PROJECT" -eq 1 ] || die "当前就是源码仓库，请用 git pull 更新"
  if manifest_is_ours "$MANIFEST_PATH"; then
    restore_manifest_agent_selection "$MANIFEST_PATH"
  fi
fi

if [ "$ACTION" = "uninstall" ] && [ "$ACTION_FROM_SUBCOMMAND" -eq 1 ]; then
  [ "$SCOPE" = "project" ] || die "uninstall 子命令只适用于外部工作区；系统级卸载请配合 --system --uninstall"
  [ "$COPY_PROJECT" -eq 1 ] || die "当前就是源码仓库，由 git 管理，无需卸载"
fi

print_plan() {
  [ "$WIZARD_MODE" -eq 1 ] || [ "$DRY_RUN" -eq 1 ] || is_interactive_input || return 0

  if [ "$DRY_RUN" -eq 1 ]; then
    section "安装预览"
  else
    section "请确认"
  fi
  bullet "操作：$(action_label)"
  bullet "AI 工具：$(agent_label)"
  bullet "使用范围：$(scope_label)"
  if [ "$SCOPE" = "project" ]; then
    bullet "工作区：$(mode_label)"
  fi
  if [ "$ACTION" = "install" ]; then
    if [ "$KB_ON_PATH" -eq 1 ]; then
      bullet "终端快捷命令：创建 kb"
    else
      bullet "终端快捷命令：暂不创建"
    fi
  fi

  case "$ACTION" in
    install)
      if [ "$COPY_PROJECT" -eq 1 ]; then
        bullet "将复制运行所需的 skills 和使用规则。"
      fi
      bullet "将让 $(agent_label) 识别这套研究工作流。"
      ;;
    update)
      bullet "将更新安装器管理的 skills 和 AI 工具配置。"
      ;;
    reinstall)
      bullet "将原子替换安装器管理的文件，并保留用户文件和研究资料。"
      ;;
    uninstall)
      bullet "将移除安装器创建的 skills 接入。"
      ;;
  esac

  if [ "$ACTION" = "install" ]; then
    note "不会删除已有研究资料。"
  else
    note "研究资料和本地运行环境会保留。"
  fi
}

confirm_plan() {
  local answer
  print_plan
  is_interactive_input || return 0
  [ "$DRY_RUN" -eq 0 ] || return 0
  [ "$ASSUME_YES" -eq 0 ] || return 0

  while true; do
    ask "确认执行？[Y/n]："
    if ! read -r answer; then
      printf '\n'
      note "输入已结束，安装已取消。"
      exit 0
    fi
    case "$answer" in
      ''|y|Y|yes|YES)
        return 0
        ;;
      n|N|no|NO)
        note "已取消，没有写入任何文件。"
        exit 0
        ;;
      *)
        note "请输入 y 或 n。"
        ;;
    esac
  done
}

print_next_steps() {
  section "开始使用"
  info "打开 $(agent_label)，在对话中输入："
  printf '  %bkb init%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
  info "初始化完成后，可以输入："
  printf '  %bkb status%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
  info "也可以直接告诉 AI：帮我建立研究知识库，并说明下一步。"
}

print_done() {
  if [ "$DRY_RUN" -eq 1 ]; then
    section "预览完成"
    if [ "$AGENT_PLAN" -eq 1 ]; then
      write_agent_plan_json
      bullet "预计受管目标：$DRY_RUN_CHANGE_COUNT 项（含条件目标；精确清单保存在 JSON 计划中）"
      ok "没有写入工作区、HOME 或运行环境。"
      info "请核对计划摘要和 JSON 后，再按其中的应用合同执行正式操作。"
    else
      bullet "预计文件变更：$DRY_RUN_CHANGE_COUNT 项（详细路径已折叠）"
      ok "没有写入任何文件。"
      info "以上是计划内容；确认无误后再执行正式操作。"
    fi
    return 0
  fi

  case "$1" in
    Install)
      section "安装完成"
      if [ "$INSTALL_INCOMPLETE" -eq 1 ]; then
        note "安装已执行，但有配置因文件冲突被跳过，请查看上方提示。"
      else
        ok "已为 $(agent_label) 完成配置。"
      fi
      if [ "$SCOPE" = "project" ]; then
        bullet "工作区：$(mode_label)"
      else
        bullet "使用范围：当前用户的所有工作区"
      fi
      if [ "$INSTALL_INCOMPLETE" -eq 0 ]; then
        if [ "$KB_SHORTCUT_AVAILABLE" -eq 1 ]; then
          ok "终端可直接运行："
          printf '  %bkb help%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
          printf '  %bkb init%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
        elif [ "$KB_SHORTCUT_CREATED" -eq 1 ]; then
          note "已创建 kb 快捷入口，但它所在的目录还不在 PATH 中。"
          info "请让 Agent 将快捷入口目录加入 PATH，重新打开终端后运行："
          printf '  %bkb help%b\n' "$C_BOLD$C_CYAN" "$C_RESET"
          info "安装器不会自动修改 shell 配置。"
        fi
      fi
      if [ "$INSTALL_INCOMPLETE" -eq 1 ]; then
        section "需要处理"
        info "请先处理上方文件冲突，再重新运行安装。"
      else
        print_next_steps
      fi
      ;;
    Update)
      section "更新完成"
      if [ "$INSTALL_INCOMPLETE" -eq 1 ]; then
        note "更新已执行，但有配置因文件冲突被保留，请查看上方提示。"
      elif [ "$UPDATE_NO_CHANGES" -eq 1 ]; then
        ok "skills 已是最新版本，AI 工具配置已检查。"
      else
        ok "skills 和 AI 工具配置已更新。"
      fi
      ok "研究资料和本地运行环境未被改动。"
      ;;
    Reinstall)
      section "重装完成"
      ok "安装器管理的 skills 和 AI 工具配置已重新安装。"
      ok "研究资料、本地运行环境和用户文件未被改动。"
      ;;
    Uninstall)
      section "卸载完成"
      if [ "$INSTALL_INCOMPLETE" -eq 1 ]; then
        note "可安全移除的配置已卸载；有冲突或已修改的文件被保留。"
      else
        ok "安装器管理的配置已移除。"
      fi
      ok "研究资料和本地运行环境已保留。"
      ;;
  esac
}

preflight_yaml() {
  local py managed_python
  py=${RESEARCH_PYTHON:-python3}
  if python_has_core_runtime "$py"; then
    SELECTED_RUNTIME_PYTHON=$(canonical_runtime_python "$py") || \
      die "所选 Python 无法稳定解析；请让 Agent 检查后重试"
    if [ -n "${RESEARCH_PYTHON:-}" ]; then
      SELECTED_RUNTIME_SOURCE="explicit-override"
    else
      SELECTED_RUNTIME_SOURCE="current-python"
    fi
    # 与 runtime bootstrap 的判定保持一致：核心依赖可用但缺少论文 PDF 深读
    # 后端时，首次使用会自动准备受管运行环境，这里如实预告。显式指定的
    # RESEARCH_PYTHON 不会触发自动准备，因此保持原有绑定。Agent 计划
    # （schema 3）要求“就绪运行环境”与“resolver 管理的 .venv 条件目标”
    # 二选一，所以这种情况下不再签署当前解释器，改为暴露条件目标。
    if [ -z "${RESEARCH_PYTHON:-}" ] && [ "${RESEARCH_NO_MANAGED_VENV:-}" != "1" ] \
      && [ "${RESEARCH_NO_PDF_BACKEND:-}" != "1" ] \
      && ! python_has_pdf_backend "$SELECTED_RUNTIME_PYTHON"; then
      RUNTIME_BOOTSTRAP_NEEDED=1
      SELECTED_RUNTIME_PYTHON=""
      SELECTED_RUNTIME_SOURCE=""
      note "论文 PDF 解析依赖尚未就绪；首次使用时会自动准备，无需手动处理。" >&2
    fi
    return 0
  fi
  if [ -z "${RESEARCH_VENV:-}" ]; then
    managed_python=$(managed_workspace_venv_has_core_runtime || true)
    if [ -n "$managed_python" ]; then
      # The current safe probe proves readiness, but Agent plan schema 3 does
      # not yet serialize the complete managed invocation chain. Keep the
      # resolver-owned tree conservative instead of signing the external base
      # executable as though installed kb would invoke it directly.
      [ "$AGENT_PLAN" -eq 0 ] || RUNTIME_BOOTSTRAP_NEEDED=1
      return 0
    fi
  fi
  if [ -z "${RESEARCH_PYTHON:-}" ]; then
    DISCOVERED_RUNTIME_PYTHON=$(path_python_with_core_runtime || true)
    if [ -n "$DISCOVERED_RUNTIME_PYTHON" ]; then
      SELECTED_RUNTIME_PYTHON=$DISCOVERED_RUNTIME_PYTHON
      SELECTED_RUNTIME_SOURCE="path-discovery"
      SELECTED_RUNTIME_ISOLATED=1
      return 0
    fi
  fi
  if [ "${RESEARCH_NO_MANAGED_VENV:-}" = "1" ]; then
    die "已关闭自动运行环境，但所选 Python 缺少完整核心依赖；请先让 Agent 按安装说明准备完整运行环境"
  fi
  RUNTIME_BOOTSTRAP_NEEDED=1
  note "Python 依赖尚未就绪；安装检查会尝试准备，离线失败时将保留文件并给出恢复提示。" >&2
}

canonical_runtime_python() {
  python3 - "$1" <<'PY' 2>/dev/null
import shutil
import sys
from pathlib import Path

value = sys.argv[1]
candidate = Path(value).expanduser()
if not candidate.is_absolute() and len(candidate.parts) == 1:
    located = shutil.which(value)
    if not located:
        raise SystemExit(1)
    candidate = Path(located)
print(candidate.resolve(strict=True))
PY
}

path_python_with_core_runtime() {
  python3 - "$WORKSPACE_ROOT" <<'PY' 2>/dev/null
import os
import stat
import subprocess
import sys
from pathlib import Path

workspace = Path(sys.argv[1]).resolve()
seen = set()
for raw_directory in os.environ.get("PATH", "").split(os.pathsep):
    if not raw_directory:
        continue
    directory = Path(raw_directory).expanduser()
    if not directory.is_absolute():
        continue
    for name in ("python3", "python"):
        candidate = directory / name
        try:
            resolved = candidate.resolve(strict=True)
            before = resolved.stat()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o111 == 0:
            continue
        try:
            resolved.relative_to(workspace)
        except ValueError:
            pass
        else:
            continue
        identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        try:
            completed = subprocess.run(
                [str(resolved), "-I", "-c", "import yaml, markdownify, bs4"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            after = resolved.stat()
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode != 0 or identity != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            continue
        print(resolved)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

python_has_core_runtime() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import subprocess
import sys

candidate = sys.argv[1]
try:
    completed = subprocess.run(
        [candidate, "-c", "import yaml, markdownify, bs4"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
except (OSError, subprocess.SubprocessError):
    raise SystemExit(1)
raise SystemExit(0 if completed.returncode == 0 else 1)
PY
}

python_has_pdf_backend() {
  python3 - "$1" <<'PY' >/dev/null 2>&1
import subprocess
import sys

candidate = sys.argv[1]
try:
    completed = subprocess.run(
        [candidate, "-c", "import pymupdf4llm, fitz"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=15,
    )
except (OSError, subprocess.SubprocessError):
    raise SystemExit(1)
raise SystemExit(0 if completed.returncode == 0 else 1)
PY
}

managed_workspace_venv_has_core_runtime() {
  python3 - "$WORKSPACE_ROOT" <<'PY' 2>/dev/null
import os
import stat
import subprocess
import sys
from pathlib import Path


def identity(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
    )


def is_within(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


root = Path(sys.argv[1])
directory_flags = (
    os.O_RDONLY
    | os.O_DIRECTORY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
descriptors = []
try:
    root_metadata = os.lstat(root)
    if not stat.S_ISDIR(root_metadata.st_mode) or root_metadata.st_uid != os.getuid():
        raise OSError("uncontrolled workspace root")
    root_fd = os.open(root, directory_flags)
    descriptors.append(root_fd)
    if identity(os.fstat(root_fd)) != identity(root_metadata):
        raise OSError("workspace root changed")

    parent_fd = root_fd
    directory_bindings = []
    for component in (".venv", "bin"):
        metadata = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise OSError("managed runtime ancestor is unsafe")
        child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
        descriptors.append(child_fd)
        if identity(os.fstat(child_fd)) != identity(metadata):
            raise OSError("managed runtime ancestor changed")
        directory_bindings.append((parent_fd, component, identity(metadata)))
        parent_fd = child_fd

    bin_fd = parent_fd
    bin_path = root / ".venv" / "bin"
    link_name = "python"
    link_bindings = []
    target_path = None
    for _ in range(16):
        link_metadata = os.stat(link_name, dir_fd=bin_fd, follow_symlinks=False)
        if not stat.S_ISLNK(link_metadata.st_mode):
            raise OSError("managed runtime interpreter must be a standard symlink chain")
        link_target = os.readlink(link_name, dir_fd=bin_fd)
        link_bindings.append((link_name, link_target, identity(link_metadata)))
        candidate = Path(link_target)
        if not candidate.is_absolute() and len(candidate.parts) == 1 and candidate.name not in {"", ".", ".."}:
            link_name = candidate.name
            continue
        if not candidate.is_absolute():
            candidate = Path(os.path.abspath(os.fspath(bin_path / candidate)))
        resolved = candidate.resolve(strict=True)
        if is_within(resolved, root):
            raise OSError("managed runtime interpreter resolves inside the workspace")
        target_path = resolved
        break
    if target_path is None:
        raise OSError("managed runtime interpreter symlink chain is too deep")
    target = target_path.stat()
    if not stat.S_ISREG(target.st_mode) or target.st_mode & 0o111 == 0:
        raise OSError("managed runtime interpreter target is unsafe")

    completed = subprocess.run(
        [str(target_path), "-c", "import yaml, markdownify, bs4"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        raise OSError("managed runtime imports are incomplete")
    if identity(os.lstat(root)) != identity(root_metadata):
        raise OSError("workspace root changed during runtime probe")
    for parent, component, expected in directory_bindings:
        current = os.stat(component, dir_fd=parent, follow_symlinks=False)
        if identity(current) != expected:
            raise OSError("managed runtime ancestor changed during probe")
    for name, expected_target, expected_identity in link_bindings:
        current_link = os.stat(name, dir_fd=bin_fd, follow_symlinks=False)
        if (
            identity(current_link) != expected_identity
            or not stat.S_ISLNK(current_link.st_mode)
            or os.readlink(name, dir_fd=bin_fd) != expected_target
        ):
            raise OSError("managed runtime interpreter changed during probe")
    if identity(target_path.stat()) != identity(target):
        raise OSError("managed runtime interpreter target changed during probe")
except (OSError, subprocess.SubprocessError):
    raise SystemExit(1)
finally:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass
print(target_path)
raise SystemExit(0)
PY
}

managed_runtime_root() {
  python3 - "$WORKSPACE_ROOT" "${RESEARCH_VENV:-}" <<'PY'
import os
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
configured = sys.argv[2].strip()
root = Path(configured).expanduser() if configured else workspace / ".venv"
print(os.path.abspath(os.fspath(root)))
PY
}

record_agent_runtime_target() {
  [ "$AGENT_PLAN" -eq 1 ] || return 0
  [ "$RUNTIME_BOOTSTRAP_NEEDED" -eq 1 ] || return 0
  record_agent_plan_target \
    "conditional-runtime-tree" \
    "$(managed_runtime_root)" \
    "research.bootstrap.CORE_RUNTIME_MODULES / managed dependency resolver" \
    "only when managed runtime is enabled and the selected Python lacks yaml, markdownify, bs4, or the pymupdf4llm PDF backend"
}

source_commit() {
  git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf ''
}

source_origin() {
  git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || printf 'local'
}

source_branch() {
  git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null || printf ''
}

verify_agent_apply_contract() {
  local distribution_root verified_state args=()
  [ -n "$APPLY_AGENT_PLAN" ] || return 0
  distribution_root=${SYNC_SOURCE:-$REPO_ROOT}
  args=(
    "--verify-plan" "$APPLY_AGENT_PLAN"
    "--expected-plan-digest" "$EXPECTED_PLAN_DIGEST"
    "--expected-plan-byte-sha256" "$EXPECTED_PLAN_BYTE_SHA256"
    "--expected-source-tree-digest" "$EXPECTED_SOURCE_TREE_DIGEST"
    "--expected-source-commit" "$EXPECTED_SOURCE_COMMIT"
    "--current-action" "$ACTION"
    "--current-scope" "$SCOPE"
    "--current-workspace" "$WORKSPACE_ROOT"
    "--current-home" "$HOME"
    "--current-distributable-root" "$distribution_root"
    "--current-runtime-root" "$(managed_runtime_root)"
    "--current-operation-time" "$OPERATION_TIME"
    "--current-source-strategy" "local-checkout"
    "--current-source-checkout" "$REPO_ROOT"
    "--current-source-origin" "$(source_origin)"
    "--current-source-branch" "$(source_branch)"
  )
  [ "$CONFIG_CLAUDE" -eq 0 ] || args+=("--current-tool" "claude")
  [ "$CONFIG_CODEX" -eq 0 ] || args+=("--current-tool" "codex")
  [ "$FORCE" -eq 0 ] || args+=("--current-force")
  [ "$KB_ON_PATH" -eq 0 ] || args+=("--current-kb-on-path")
  if [ -n "$SELECTED_RUNTIME_PYTHON" ]; then
    args+=(
      "--current-runtime-interpreter" "$SELECTED_RUNTIME_PYTHON"
      "--current-runtime-selection-source" "$SELECTED_RUNTIME_SOURCE"
    )
    if [ -n "${RESEARCH_PYTHON:-}" ]; then
      args+=("--current-runtime-explicit-override" "$RESEARCH_PYTHON")
    fi
    [ "$SELECTED_RUNTIME_ISOLATED" -eq 0 ] || args+=("--current-runtime-isolated-probe")
  fi
  if ! verified_state=$(python3 "$REPO_ROOT/install-lib/agent_plan.py" "${args[@]}" 2>/dev/null); then
    die "Agent 安装计划、源码或目标状态已变化；未写入任何内容，请重新生成并审阅计划"
  fi
  [ -n "$verified_state" ] || \
    die "Agent 安装计划缺少安装记录前置条件；未写入任何内容，请重新生成并审阅计划"
  VERIFIED_MANIFEST_STATE=$(python3 -c \
    'import json,sys; payload=json.loads(sys.argv[1]); print(json.dumps(payload["manifest_precondition"], sort_keys=True, separators=(",", ":")))' \
    "$verified_state") || \
    die "Agent 安装计划验证结果无效；未写入任何内容，请重新生成并审阅计划"
}

record_agent_plan_target() {
  [ "$AGENT_PLAN" -eq 1 ] || return 0
  AGENT_PLAN_TARGET_SEQUENCE+=("args:${#AGENT_PLAN_TARGET_ARGS[@]}")
  AGENT_PLAN_TARGET_ARGS+=("$1" "$2" "${3:-}" "${4:-}" "${5:-}")
  DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
}

record_agent_plan_conflict() {
  [ "$AGENT_PLAN" -eq 1 ] || return 0
  AGENT_PLAN_CONFLICTS+=("$1")
}

validate_agent_plan_output() {
  [ "$AGENT_PLAN" -eq 1 ] || return 0
  AGENT_PLAN_JSON=$(python3 - "$AGENT_PLAN_JSON" "$WORKSPACE_ROOT" "$HOME" <<'PY'
import os
import sys
from pathlib import Path

output = Path(sys.argv[1]).expanduser().resolve(strict=False)
workspace = Path(sys.argv[2]).resolve(strict=False)
home = Path(sys.argv[3]).resolve(strict=False)
if output == workspace or workspace in output.parents:
    raise SystemExit("Agent plan JSON must be outside the target workspace")
if output == home or home in output.parents:
    raise SystemExit("Agent plan JSON must be outside HOME")
if output.exists() and (output.is_symlink() or not output.is_file()):
    raise SystemExit("Agent plan JSON target must be a regular file or a new path")
print(output)
PY
  ) || die "计划文件必须位于目标工作区和 HOME 之外，且不能是符号链接"
}

write_agent_plan_json() {
  local digest commit origin branch distribution_root index sequence target_index args=() apply_args=()
  [ "$AGENT_PLAN" -eq 1 ] || return 0
  commit=$(source_commit)
  [ -n "$commit" ] || die "Agent 安装计划需要可验证的 Git commit"
  origin=$(source_origin)
  branch=$(source_branch)
  distribution_root=${SYNC_SOURCE:-$REPO_ROOT}
  args=(
    "--output" "$AGENT_PLAN_JSON"
    "--action" "$ACTION"
    "--scope" "$SCOPE"
    "--workspace" "$WORKSPACE_ROOT"
    "--home" "$HOME"
    "--source-strategy" "local-checkout"
    "--source-checkout" "$REPO_ROOT"
    "--source-origin" "$origin"
    "--source-branch" "$branch"
    "--source-commit" "$commit"
    "--distributable-root" "$distribution_root"
    "--operation-time" "$OPERATION_TIME"
  )
  if [ "$COPY_PROJECT" -eq 1 ]; then
    [ -n "$AGENT_PLAN_MANIFEST_STATE" ] || \
      die "Agent 安装计划缺少同步器提供的安装记录快照；未生成计划"
    args+=("--manifest-precondition-json" "$AGENT_PLAN_MANIFEST_STATE")
  fi
  if [ -n "$SELECTED_RUNTIME_PYTHON" ]; then
    args+=(
      "--runtime-interpreter" "$SELECTED_RUNTIME_PYTHON"
      "--runtime-selection-source" "$SELECTED_RUNTIME_SOURCE"
    )
    if [ -n "${RESEARCH_PYTHON:-}" ]; then
      args+=("--runtime-explicit-override" "$RESEARCH_PYTHON")
    fi
    [ "$SELECTED_RUNTIME_ISOLATED" -eq 0 ] || args+=("--runtime-isolated-probe")
  fi
  [ "$CONFIG_CLAUDE" -eq 0 ] || args+=("--tool" "claude")
  [ "$CONFIG_CODEX" -eq 0 ] || args+=("--tool" "codex")
  if [ "${#AGENT_PLAN_TARGET_SEQUENCE[@]}" -gt 0 ]; then
    for sequence in "${AGENT_PLAN_TARGET_SEQUENCE[@]}"; do
      target_index=${sequence#*:}
      case "$sequence" in
        args:*)
          args+=(
            "--target-record"
            "fields"
            "${AGENT_PLAN_TARGET_ARGS[target_index]}"
            "${AGENT_PLAN_TARGET_ARGS[target_index + 1]}"
            "${AGENT_PLAN_TARGET_ARGS[target_index + 2]}"
            "${AGENT_PLAN_TARGET_ARGS[target_index + 3]}"
            "${AGENT_PLAN_TARGET_ARGS[target_index + 4]}"
          )
          ;;
        json:*)
          args+=("--target-record" "json" "${AGENT_PLAN_TARGET_JSON[target_index]}" "" "" "" "")
          ;;
      esac
    done
  fi
  if [ "${#AGENT_PLAN_CONFLICTS[@]}" -gt 0 ]; then
    for index in "${!AGENT_PLAN_CONFLICTS[@]}"; do
      args+=("--conflict" "${AGENT_PLAN_CONFLICTS[index]}")
    done
  fi

  apply_args=("$REPO_ROOT/install.sh")
  [ "$ACTION" = "install" ] || apply_args+=("$ACTION")
  if [ "$SCOPE" = "project" ]; then
    apply_args+=("--project" "$WORKSPACE_ROOT")
  else
    apply_args+=("--system")
  fi
  if [ "$ACTION" = "install" ]; then
    if [ "$CONFIG_CLAUDE" -eq 1 ] && [ "$CONFIG_CODEX" -eq 1 ]; then
      apply_args+=("--all")
    elif [ "$CONFIG_CLAUDE" -eq 1 ]; then
      apply_args+=("--claude")
    else
      apply_args+=("--codex")
    fi
  fi
  [ "$KB_ON_PATH" -eq 0 ] || apply_args+=("--kb-on-path")
  [ "$FORCE" -eq 0 ] || apply_args+=("--force")
  [ -z "$SYNC_SOURCE" ] || apply_args+=("--source" "$SYNC_SOURCE")
  [ -z "$OPERATION_TIME" ] || apply_args+=("--operation-time" "$OPERATION_TIME")
  apply_args+=("--expected-source-commit" "$commit")
  apply_args+=("--yes")
  for index in "${!apply_args[@]}"; do
    args+=("--apply-arg=${apply_args[index]}")
  done

  digest=$(python3 "$REPO_ROOT/install-lib/agent_plan.py" "${args[@]}") || die "无法写入 Agent 安装计划"
  bullet "精确 JSON 计划已保存到你指定的位置。"
  bullet "计划摘要：$DRY_RUN_CHANGE_COUNT 个目标 · ${#AGENT_PLAN_CONFLICTS[@]} 个冲突"
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

guard_copy_install_target() {
  if [ -L "$WORKSPACE_ROOT/.agents" ]; then
    die "检测到旧版安装；请先卸载旧版，再重新安装"
  fi
  if [ -d "$WORKSPACE_ROOT/.agents" ]; then
    if manifest_is_ours "$MANIFEST_PATH"; then
      die "这个工作区已经安装过；请选择“更新”或“重装”，不要重复安装"
    fi
    return 0
  fi
  if [ -e "$WORKSPACE_ROOT/.agents" ]; then
    die "目标工作区已有同名配置，为避免覆盖已停止安装"
  fi
}

ws_sync() {
  local action=$1 commit origin branch agent_csv output status change_count args=()
  shift || true
  commit=$(source_commit)
  origin=$(source_origin)
  branch=$(source_branch)
  args=(
    "$action"
    "--repo" "$REPO_ROOT"
    "--dir" "$WORKSPACE_ROOT"
    "--source-commit" "$commit"
    "--source-origin" "$origin"
    "--source-checkout" "$REPO_ROOT"
    "--source-branch" "$branch"
  )
  if [ "$origin" != "local" ] && [ -z "$branch" ]; then
    note "当前源码处于 detached 状态；本次安装绑定当前 commit，之后更新前需要选择分支。" >&2
  fi
  if [ "$action" = "install" ]; then
    args+=("--source-strategy" "local-checkout")
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
  if [ -n "$OPERATION_TIME" ]; then
    args+=("--operation-time" "$OPERATION_TIME")
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    args+=("--dry-run")
  fi
  if [ "$AGENT_PLAN" -eq 1 ]; then
    args+=("--plan-jsonl")
  fi
  if [ "$FORCE" -eq 1 ]; then
    args+=("--force")
  fi
  if [ "$FROM_SNAPSHOT" -eq 1 ]; then
    args+=("--allow-snapshot-source")
  fi
  if [ -n "$VERIFIED_MANIFEST_STATE" ]; then
    args+=("--expected-manifest-state" "$VERIFIED_MANIFEST_STATE")
  fi
  if output=$(python3 "$REPO_ROOT/install-lib/ws_sync.py" "${args[@]}" "$@" 2>&1); then
    if [ "$action" = "update" ]; then
      case "$output" in
        *"clean-sync: no changes; manifest unchanged"*) UPDATE_NO_CHANGES=1 ;;
      esac
    fi
    case "$output" in
      *"snapshot-source:"*)
        note "快照模式：源码目录没有 git 版本信息，无法区分未跟踪文件；已按确定性文件清单打包（排除 .git/.venv/__pycache__/.DS_Store 等）。" >&2
        ;;
    esac
    case "$output" in
      *"warn:"*)
        warn "检测到用户修改并按安全策略保留，请让 Agent 检查。"
        record_agent_plan_conflict "检测到受管文件漂移；按安全策略保留"
        INSTALL_INCOMPLETE=1
        ;;
    esac
    if [ "$DRY_RUN" -eq 1 ]; then
      if [ "$AGENT_PLAN" -eq 1 ]; then
        change_count=0
        while IFS= read -r plan_line; do
          case "$plan_line" in
            *'"operation": "manifest-expectation"'*)
              [ -z "$AGENT_PLAN_MANIFEST_STATE" ] || \
                die "同步器返回了重复的安装记录快照；未生成计划"
              AGENT_PLAN_MANIFEST_STATE=$(python3 -c \
                'import json,sys; payload=json.loads(sys.argv[1]); print(json.dumps(payload["state"], sort_keys=True, separators=(",", ":")))' \
                "$plan_line") || die "同步器返回了无效的安装记录快照；未生成计划"
              ;;
            \{*)
              AGENT_PLAN_TARGET_SEQUENCE+=("json:${#AGENT_PLAN_TARGET_JSON[@]}")
              AGENT_PLAN_TARGET_JSON+=("$plan_line")
              change_count=$((change_count + 1))
              ;;
          esac
        done <<< "$output"
        DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + change_count))
      else
        change_count=$(printf '%s\n' "$output" | awk '/^\[dry-run\]/ { count += 1 } END { print count + 0 }')
        DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + change_count))
      fi
    else
      case "$action" in
        install) info "工作区文件已准备。" ;;
        reinstall) info "工作区文件已重新安装。" ;;
        uninstall) info "安装器管理的工作区文件已移除。" ;;
      esac
    fi
    return 0
  else
    status=$?
    fail "工作区文件操作失败。" >&2
    ws_sync_error_tail "$output" >&2 || true
    return "$status"
  fi
}

ws_sync_error_tail() {
  # 子进程原文只用于进程内分类，绝不投影到公开面。未知错误也使用
  # fail-closed 的稳定类别，不猜测、更不回显路径、token 或 traceback。
  case "$1" in
    *"source-not-git-worktree"*|*"source must be a git worktree"*)
      printf '%s\n' "  原因：安装源码缺少可验证的版本信息。"
      printf '%s\n' "  处理：请让 Agent 取得完整的版本化源码后重试；若只能使用快照，请先确认接受其来源边界。"
      ;;
    *"collides with local files"*)
      printf '%s\n' "  原因：目标工作区存在文件冲突。"
      printf '%s\n' "  处理：请先备份冲突文件，再让 Agent 检查并重试。"
      ;;
    *"managed drift"*|*"local modifications inside managed"*)
      printf '%s\n' "  原因：检测到受管文件已被本地修改。"
      printf '%s\n' "  处理：请先让 Agent 检查并备份本地修改，再决定是否替换。"
      ;;
    *"manifest"*"changed"*|*"manifest"*"expect"*|*"stale"*|*"lease"*)
      printf '%s\n' "  原因：安装状态已变化，当前操作已安全停止。"
      printf '%s\n' "  处理：请让 Agent 重新检查当前状态后再试。"
      ;;
    *"Permission denied"*|*"permission denied"*|*"Operation not permitted"*)
      printf '%s\n' "  原因：当前权限不足，未能完成工作区文件操作。"
      printf '%s\n' "  处理：请检查工作区权限后重试。"
      ;;
    *)
      printf '%s\n' "  原因：同步过程遇到未分类错误，已安全停止。"
      printf '%s\n' "  处理：请让 Agent 检查私有诊断后重试。"
      ;;
  esac
}

sync_workspace_copy() {
  [ "$COPY_PROJECT" -eq 1 ] || return 0
  guard_copy_install_target
  ws_sync install
}

update_workspace_copy() {
  [ "$COPY_PROJECT" -eq 1 ] || die "更新只适用于外部工作区"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "这个工作区没有可更新的安装"
  manifest_is_ours "$MANIFEST_PATH" || die "无法确认安装记录；新工作区请选择安装，已有工作区请先修复安装记录"
  ws_sync update
}

reinstall_workspace_copy() {
  [ "$COPY_PROJECT" -eq 1 ] || die "重装只适用于外部工作区"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "这个工作区没有可重装的安装"
  manifest_is_ours "$MANIFEST_PATH" || die "无法确认安装记录；为避免覆盖用户文件已停止重装"
  ws_sync reinstall
}

remove_agents_md_if_managed() {
  local mode sha actual
  [ -f "$MANIFEST_PATH" ] || return 0
  mode=$(manifest_field "$MANIFEST_PATH" agents_md)
  sha=$(manifest_field "$MANIFEST_PATH" agents_md_sha)
  [ "$mode" = "managed" ] || {
    warn "AGENTS.md 已由用户管理，予以保留"
    record_agent_plan_conflict "保留用户管理的 AGENTS.md"
    INSTALL_INCOMPLETE=1
    return 0
  }
  [ -f "$WORKSPACE_ROOT/AGENTS.md" ] || return 0
  actual=$(file_sha256 "$WORKSPACE_ROOT/AGENTS.md")
  if [ -n "$sha" ] && [ "$actual" = "$sha" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      if [ "$AGENT_PLAN" -eq 1 ]; then
        record_agent_plan_target "delete" "$WORKSPACE_ROOT/AGENTS.md"
      else
        DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
      fi
    else
      rm "$WORKSPACE_ROOT/AGENTS.md"
    fi
  else
    warn "AGENTS.md 已被修改，予以保留"
    record_agent_plan_conflict "保留已修改的 AGENTS.md"
    INSTALL_INCOMPLETE=1
  fi
}

uninstall_workspace_copy() {
  local had_manifest=0
  [ "$COPY_PROJECT" -eq 1 ] || die "卸载只适用于外部工作区"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "这个工作区没有可卸载的受管配置"
  manifest_is_ours "$MANIFEST_PATH" || die "无法确认安装记录，为避免误删已停止卸载"
  had_manifest=1
  ws_sync uninstall
  uninstall_kb_on_path
  if [ "$had_manifest" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
    info "研究资料和本地运行环境已保留；这个工作区现在不再由安装器管理。"
  fi
}

guard_managed_directory_chain() {
  local target=$1 base
  case "$target" in
    "$WORKSPACE_ROOT"|"$WORKSPACE_ROOT"/*) base=$WORKSPACE_ROOT ;;
    "$HOME"|"$HOME"/*) base=$HOME ;;
    *) die "受管目录超出安装边界，已停止" ;;
  esac
  python3 - "$base" "$target" <<'PY' >/dev/null 2>&1 || \
    die "检测到受管目录路径包含符号链接或非目录组件，已停止"
import os
import stat
import sys
from pathlib import Path

base = Path(sys.argv[1])
target = Path(sys.argv[2])
try:
    relative = target.relative_to(base)
except ValueError:
    raise SystemExit(1)
current = base
for part in relative.parts:
    current = current / part
    try:
        mode = os.lstat(current).st_mode
    except FileNotFoundError:
        continue
    except OSError:
        raise SystemExit(1)
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise SystemExit(1)
PY
}

guard_selected_managed_parents() {
  # Validate every selected integration directory before ws_sync performs the
  # first copy. A later ensure_dir() check cannot prevent a half-install.
  if [ "$CONFIG_CLAUDE" -eq 1 ] && [ "$COPY_PROJECT" -eq 0 ]; then
    if [ "$SCOPE" = "system" ]; then
      guard_managed_directory_chain "$HOME/.claude/skills"
    else
      guard_managed_directory_chain "$WORKSPACE_ROOT/.claude"
    fi
  fi
  if [ "$CONFIG_CODEX" -eq 1 ] && [ "$SCOPE" = "system" ]; then
    guard_managed_directory_chain "$HOME/.codex/$INSTALL_NAME"
    if [ -e "$HOME/.codex/skills" ] || [ -L "$HOME/.codex/skills" ]; then
      guard_managed_directory_chain "$HOME/.codex/skills"
    fi
  fi
  if [ "$KB_ON_PATH" -eq 1 ]; then
    if [ "$SCOPE" = "system" ]; then
      guard_managed_directory_chain "$HOME/.local/bin"
    else
      guard_managed_directory_chain "$WORKSPACE_ROOT/bin"
    fi
  fi
}

ensure_dir() {
  local base missing_dir
  guard_managed_directory_chain "$1"
  if [ -d "$1" ] && [ ! -L "$1" ]; then
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    case "$1" in
      "$WORKSPACE_ROOT"|"$WORKSPACE_ROOT"/*) base=$WORKSPACE_ROOT ;;
      "$HOME"|"$HOME"/*) base=$HOME ;;
      *) die "受管目录超出安装边界，已停止" ;;
    esac
    while IFS= read -r missing_dir; do
      [ -n "$missing_dir" ] || continue
      if [ "$AGENT_PLAN" -eq 1 ]; then
        record_agent_plan_target "mkdir" "$missing_dir"
      else
        DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
      fi
    done < <(python3 - "$base" "$1" <<'PY'
import os
import sys
from pathlib import Path

base = Path(sys.argv[1])
target = Path(sys.argv[2])
current = base
for part in target.relative_to(base).parts:
    current = current / part
    try:
        os.lstat(current)
    except FileNotFoundError:
        print(current)
PY
)
  else
    mkdir -p "$1"
  fi
}

link_force() {
  local target=$1 link=$2 actual
  guard_managed_directory_chain "$(dirname -- "$link")"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    warn "检测到已有文件，未覆盖。"
    record_agent_plan_conflict "已有普通文件，保留：$link"
    INSTALL_INCOMPLETE=1
    return 0
  fi
  if [ -L "$link" ]; then
    actual=$(readlink "$link")
    if [ "$actual" = "$target" ]; then
      return 0
    fi
    warn "检测到已有链接指向其他位置，已保留。"
    record_agent_plan_conflict "已有链接指向其他位置，保留：$link"
    INSTALL_INCOMPLETE=1
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$AGENT_PLAN" -eq 1 ]; then
      record_agent_plan_target "symlink" "$link" "$target"
    else
      DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
    fi
  else
    ln -sfn "$target" "$link"
  fi
}

remove_symlink_if_matches() {
  local link=$1 expected=$2 expected_alt=${3:-}
  local actual
  guard_managed_directory_chain "$(dirname -- "$link")"
  [ -L "$link" ] || return 0
  actual=$(readlink "$link")
  if [ "$actual" = "$expected" ] || { [ -n "$expected_alt" ] && [ "$actual" = "$expected_alt" ]; }; then
    if [ "$DRY_RUN" -eq 1 ]; then
      if [ "$AGENT_PLAN" -eq 1 ]; then
        record_agent_plan_target "remove-symlink" "$link" "$actual"
      else
        DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
      fi
    else
      rm "$link"
    fi
  else
    warn "链接目标与安装记录不一致，已保留。"
    record_agent_plan_conflict "链接目标与安装记录不一致，保留：$link"
    INSTALL_INCOMPLETE=1
  fi
}

write_managed_block() {
  local file=$1 block_file=$2 planned_content_digest=${3:-} tmp_file
  guard_managed_directory_chain "$(dirname -- "$file")"
  [ ! -L "$file" ] || die "检测到符号链接形式的 Claude 配置；为避免跟随或替换链接，已停止"
  if [ "$AGENT_PLAN" -eq 1 ]; then
    [ -n "$planned_content_digest" ] || die "Agent 计划缺少 managed block 内容 digest"
    record_agent_plan_target "write-managed-block" "$file" "$REPO_ROOT/.agents/AGENTS.md" "" "$planned_content_digest"
    return 0
  fi
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
    DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
    rm -f "$tmp_file"
  elif [ -f "$file" ] && cmp -s "$file" "$tmp_file"; then
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$file"
  fi
}

remove_managed_block() {
  local file=$1 tmp_file
  guard_managed_directory_chain "$(dirname -- "$file")"
  [ ! -L "$file" ] || die "检测到符号链接形式的 Claude 配置；为避免跟随或替换链接，已停止"
  [ -f "$file" ] || return 0
  if [ "$AGENT_PLAN" -eq 1 ]; then
    if awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
      $0 == begin { in_block = 1; removed = 1; next }
      $0 == end { in_block = 0; next }
      END { exit removed ? 0 : 2 }
    ' "$file" >/dev/null; then
      record_agent_plan_target "remove-managed-block" "$file"
    else
      local plan_status=$?
      [ "$plan_status" -eq 2 ] && return 0
      return "$plan_status"
    fi
    return 0
  fi
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
    DRY_RUN_CHANGE_COUNT=$((DRY_RUN_CHANGE_COUNT + 1))
    rm -f "$tmp_file"
  else
    mv "$tmp_file" "$file"
  fi
}

render_claude_block() {
  local mode=$1 ws=$2
  printf '%s\n' "$BEGIN_MARKER"
  printf '<!-- Managed by workspace-oss install.sh. AGENTS.md is the source of truth; refresh this block by rerunning install.sh. -->\n'
  if [ "$mode" = "include" ]; then
    printf '@AGENTS.md\n'
  else
    printf '<!-- Generated from %s/.agents/AGENTS.md for workspace %s. -->\n\n' "$REPO_ROOT" "$ws"
    sed -n '1,$p' "$REPO_ROOT/.agents/AGENTS.md"
  fi
  printf '%s\n' "$END_MARKER"
}

claude_block_digest() {
  render_claude_block "$1" "$2" | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

build_claude_block() {
  local mode=$1 ws=$2 block_file
  block_file=$(mktemp "${TMPDIR:-/tmp}/${INSTALL_NAME}.block.XXXXXX")
  render_claude_block "$mode" "$ws" >"$block_file"
  printf '%s\n' "$block_file"
}

install_claude_project() {
  local claude_dir link_target block_file block_digest
  claude_dir="$WORKSPACE_ROOT/.claude"
  ensure_dir "$claude_dir"
  # Self-contained workspaces keep .agents and AGENTS.md in the workspace root,
  # so Claude can use an include block plus a relative skills symlink.
  if [ "$SELF_CONTAINED" -eq 1 ]; then
    link_target="../.agents/skills"
    if [ "$AGENT_PLAN" -eq 1 ]; then
      block_digest=$(claude_block_digest include "$WORKSPACE_ROOT")
    else
      block_file=$(build_claude_block include "$WORKSPACE_ROOT")
    fi
  else
    link_target="$SKILLS_SRC"
    if [ "$AGENT_PLAN" -eq 1 ]; then
      block_digest=$(claude_block_digest copy "$WORKSPACE_ROOT")
    else
      block_file=$(build_claude_block copy "$WORKSPACE_ROOT")
    fi
  fi
  link_force "$link_target" "$claude_dir/skills"
  if claude_links_to_workspace_agents "$WORKSPACE_ROOT/CLAUDE.md"; then
    : # The link already exposes AGENTS.md to Claude; adding @AGENTS.md would self-reference.
  else
    write_managed_block "$WORKSPACE_ROOT/CLAUDE.md" "${block_file:-}" "${block_digest:-}"
  fi
  [ -z "${block_file:-}" ] || rm -f "$block_file"
}

uninstall_claude_project() {
  local expected
  if [ "$SELF_CONTAINED" -eq 1 ]; then
    expected="../.agents/skills"
  else
    expected="$SKILLS_SRC"
  fi
  remove_symlink_if_matches "$WORKSPACE_ROOT/.claude/skills" "$expected" "$SKILLS_SRC"
  if claude_links_to_workspace_agents "$WORKSPACE_ROOT/CLAUDE.md"; then
    :
  else
    remove_managed_block "$WORKSPACE_ROOT/CLAUDE.md"
  fi
}

install_claude_system() {
  local skill name block_file block_digest
  ensure_dir "$HOME/.claude/skills"
  # System scope links each skill back to the repo so __file__.resolve() can
  # still find the sibling .agents/lib in the source checkout.
  for skill in "$SKILLS_SRC"/*; do
    [ -d "$skill" ] || continue
    name=${skill##*/}
    link_force "$skill" "$HOME/.claude/skills/$name"
  done
  if [ "$AGENT_PLAN" -eq 1 ]; then
    block_digest=$(claude_block_digest copy "$HOME/.claude")
  else
    block_file=$(build_claude_block copy "$HOME/.claude")
  fi
  write_managed_block "$HOME/.claude/CLAUDE.md" "${block_file:-}" "${block_digest:-}"
  [ -z "${block_file:-}" ] || rm -f "$block_file"
  note "系统级配置完成后，每个项目仍需选择自己的研究工作区；详见安装指南。"
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
    return 0
  fi
  # External project scope is self-contained: the shared copy step installed the
  # full .agents tree plus AGENTS.md, preserving sibling imports under DIR.
  return 0
}

uninstall_codex_project() {
  if same_dir "$WORKSPACE_ROOT" "$REPO_ROOT"; then
    return 0
  fi
  if [ -L "$WORKSPACE_ROOT/.agents" ]; then
    remove_symlink_if_matches "$WORKSPACE_ROOT/.agents" "$REPO_ROOT/.agents"
  elif [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -f "$MANIFEST_PATH" ]; then
    warn ".agents 不属于本安装器，已保留"
    INSTALL_INCOMPLETE=1
  fi
  remove_symlink_if_matches "$WORKSPACE_ROOT/AGENTS.md" "$REPO_ROOT/.agents/AGENTS.md"
}

install_codex_system() {
  local global_dir skill name
  global_dir="$HOME/.codex/$INSTALL_NAME"
  ensure_dir "$global_dir"
  link_force "$REPO_ROOT/.agents" "$global_dir/.agents"
  link_force "$REPO_ROOT/.agents/AGENTS.md" "$global_dir/AGENTS.md"
  if [ -d "$HOME/.codex/skills" ]; then
    for skill in "$SKILLS_SRC"/*; do
      [ -d "$skill" ] || continue
      name=${skill##*/}
      link_force "$skill" "$HOME/.codex/skills/$name"
    done
  else
    warn "未找到 Codex 的系统级 skills 目录，已跳过这部分配置。"
    record_agent_plan_conflict "未找到 Codex 系统级 skills 目录，跳过 skill 链接"
    INSTALL_INCOMPLETE=1
  fi
  note "Codex 的系统级接入能力有限，优先推荐按工作区安装。"
}

uninstall_codex_system() {
  local global_dir skill name
  global_dir="$HOME/.codex/$INSTALL_NAME"
  remove_symlink_if_matches "$global_dir/.agents" "$REPO_ROOT/.agents"
  remove_symlink_if_matches "$global_dir/AGENTS.md" "$REPO_ROOT/.agents/AGENTS.md"
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
  if [ "$DRY_RUN" -eq 0 ] && [ -L "$link" ] && [ "$(readlink "$link")" = "$WS_KB_SCRIPT" ]; then
    KB_SHORTCUT_CREATED=1
  fi
  if [ "$KB_SHORTCUT_CREATED" -eq 1 ] && path_on_path "$dir"; then
    KB_SHORTCUT_AVAILABLE=1
  elif [ "$KB_SHORTCUT_CREATED" -eq 1 ]; then
    warn "kb 快捷入口已创建，但终端尚未搜索它所在的目录。"
  fi
}

uninstall_kb_on_path() {
  local dir link
  if [ "$SCOPE" = "system" ]; then
    dir="$HOME/.local/bin"
  else
    dir="$WORKSPACE_ROOT/bin"
  fi
  link="$dir/kb"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    warn "kb 快捷入口不是安装器创建的链接，已保留。"
    record_agent_plan_conflict "kb 快捷入口是普通文件，保留：$link"
    INSTALL_INCOMPLETE=1
    return 0
  fi
  remove_symlink_if_matches "$link" "$WS_KB_SCRIPT" "$KB_SCRIPT"
}

run_smoke() {
  local smoke_output
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  if [ "$ACTION" != "install" ] && [ "$ACTION" != "reinstall" ]; then
    return 0
  fi
  section "安装检查"
  info "正在检查 kb 基础功能..."
  if [ -n "$DISCOVERED_RUNTIME_PYTHON" ] && [ -z "${RESEARCH_PYTHON:-}" ]; then
    export RESEARCH_PYTHON="$DISCOVERED_RUNTIME_PYTHON"
  fi
  # Child diagnostics can contain tracebacks and internal paths; keep them private.
  if ! smoke_output=$(_RESEARCH_BOOTSTRAP_ALLOW_PROVISION=1 "$WS_KB_SCRIPT" help 2>&1); then
    warn "kb 安装检查未通过，请让 Agent 检查后重试。"
    return 1
  fi
  case "$smoke_output" in
    *"核心运行环境尚未就绪"*)
      warn "工作区文件已安装，但核心运行环境尚未就绪；请让 Agent 按安装说明准备依赖后再使用 kb doctor 复查。"
      return 0
      ;;
  esac
  if [ "$COPY_PROJECT" -eq 1 ]; then
    if ! smoke_output=$(_RESEARCH_BOOTSTRAP_ALLOW_PROVISION=1 "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor 2>&1); then
      warn "kb 安装检查未通过，请让 Agent 检查后重试。"
      return 1
    fi
  else
    if ! smoke_output=$(RESEARCH_SKILLS_HOME="$REPO_ROOT" _RESEARCH_BOOTSTRAP_ALLOW_PROVISION=1 "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor 2>&1); then
      warn "kb 安装检查未通过，请让 Agent 检查后重试。"
      return 1
    fi
  fi
  case "$smoke_output" in
    *"核心运行环境尚未就绪"*)
      warn "工作区文件已安装，但核心运行环境尚未就绪；请让 Agent 按安装说明准备依赖后再使用 kb doctor 复查。"
      return 0
      ;;
  esac
  ok "kb 基础入口可用。"
}

if [ "$ACTION" != "uninstall" ]; then
  if [ "$ACTION" = "install" ] && [ "$COPY_PROJECT" -eq 1 ]; then
    guard_copy_install_target
  fi
fi

validate_agent_plan_output

if [ -n "$EXPECTED_SOURCE_COMMIT" ] && [ "$(source_commit)" != "$EXPECTED_SOURCE_COMMIT" ]; then
  die "源码版本已不同于审阅过的 Agent 计划；请重新生成计划"
fi
if [ "$ACTION" != "uninstall" ]; then
  preflight_yaml
fi
verify_agent_apply_contract
confirm_plan

if [ "$ACTION" != "uninstall" ]; then
  if [ "$COPY_PROJECT" -eq 0 ]; then
    guard_claude_project_target
  fi
  guard_selected_managed_parents
fi

# A plan exposes the resolver-owned runtime tree only when this run may need it.
record_agent_runtime_target

case "$ACTION" in
  install)
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ]; then
      sync_workspace_copy
    fi
    if [ "$CONFIG_CLAUDE" -eq 1 ]; then
      if [ "$SCOPE" = "system" ]; then
        install_claude_system
      elif [ "$COPY_PROJECT" -eq 0 ]; then
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
    print_done Install
    ;;
  update)
    UPDATE_CONFIG_CLAUDE=0
    UPDATE_CONFIG_CODEX=0
    update_workspace_copy
    UPDATE_CONFIG_CLAUDE=$(manifest_agent_enabled "$MANIFEST_PATH" claude 2>/dev/null || printf '1')
    UPDATE_CONFIG_CODEX=$(manifest_agent_enabled "$MANIFEST_PATH" codex 2>/dev/null || printf '0')
    if [ "$UPDATE_CONFIG_CODEX" = "1" ]; then
      install_codex_project
    fi
    [ "$KB_ON_PATH" -eq 1 ] && install_kb_on_path
    print_done Update
    ;;
  reinstall)
    UPDATE_CONFIG_CLAUDE=0
    UPDATE_CONFIG_CODEX=0
    reinstall_workspace_copy
    UPDATE_CONFIG_CLAUDE=$(manifest_agent_enabled "$MANIFEST_PATH" claude 2>/dev/null || printf '1')
    UPDATE_CONFIG_CODEX=$(manifest_agent_enabled "$MANIFEST_PATH" codex 2>/dev/null || printf '0')
    if [ "$UPDATE_CONFIG_CODEX" = "1" ]; then
      install_codex_project
    fi
    [ "$KB_ON_PATH" -eq 1 ] && install_kb_on_path
    run_smoke
    print_done Reinstall
    ;;
  uninstall)
    CORRUPT_MANIFEST_UNINSTALL=0
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ] && [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] && manifest_is_ours "$MANIFEST_PATH"; then
      uninstall_workspace_copy
      print_done Uninstall
      exit 0
    fi
    if [ "$SCOPE" = "project" ] && [ "$COPY_PROJECT" -eq 1 ] && [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] && [ -f "$MANIFEST_PATH" ]; then
      warn "安装记录无效或已损坏，无法安全删除 .agents"
      warn ".agents 已保留，便于手动检查"
      CORRUPT_MANIFEST_UNINSTALL=1
      INSTALL_INCOMPLETE=1
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
    uninstall_kb_on_path
    if [ "$CORRUPT_MANIFEST_UNINSTALL" -eq 1 ]; then
      warn "研究资料和本地运行环境未被改动"
    fi
    print_done Uninstall
    ;;
  *)
    die "无法识别的操作：$ACTION"
    ;;
esac
