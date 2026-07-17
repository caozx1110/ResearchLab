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
  usage_option "--force" "更新时覆盖已修改的受管文件"
  usage_option "--source DIR" "从指定源码目录更新"
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

quote_path() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

same_dir() {
  [ "$(abs_dir "$1")" = "$(abs_dir "$2")" ]
}

ACTION=install
ACTION_FROM_SUBCOMMAND=0
ACTION_EXPLICIT=0
DRY_RUN=0
CONFIG_CLAUDE=0
CONFIG_CODEX=0
AGENT_FLAG_SET=0
SCOPE=""
PROJECT_DIR=""
PROJECT_FLAG_SET=0
KB_ON_PATH=0
KB_ON_PATH_FLAG_SET=0
FORCE=0
SYNC_SOURCE=""
ASSUME_YES=0
WIZARD_MODE=0
WIZARD_STEP=0
INSTALL_INCOMPLETE=0
KB_SHORTCUT_CREATED=0
KB_SHORTCUT_AVAILABLE=0
UPDATE_NO_CHANGES=0

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
    --source)
      [ "${2:-}" != "" ] && [[ ${2:-} != --* ]] || die "--source 需要一个目录"
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
    reinstall) printf '重装' ;;
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

prompt_action() {
  local choice
  is_interactive_input || return 0
  wizard_step "你想做什么？"
  menu_option 1 "安装或重新配置" "（推荐）"
  menu_option 2 "更新外部工作区中的 skills"
  menu_option 3 "卸载 skills 接入" "（保留研究资料）"
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
      3|uninstall)
        ACTION=uninstall
        return 0
        ;;
      *)
        note "请输入 1、2 或 3。"
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
  local choice default_dir
  if ! is_interactive_input; then
    return 0
  fi
  default_dir=$(pwd)
  wizard_step "研究工作区放在哪里？"
  info "知识库和运行环境会以这个目录为中心。"
  while true; do
    ask "目录 [$default_dir]："
    read -r choice || choice=""
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
  if [ "$ACTION" = "install" ] || [ "$ACTION" = "uninstall" ]; then
    bullet "AI 工具：$(agent_label)"
  fi
  bullet "使用范围：$(scope_label)"
  if [ "$SCOPE" = "project" ]; then
    bullet "工作区：$WORKSPACE_ROOT"
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
    ok "没有写入任何文件。"
    info "以上是计划内容；确认无误后再执行正式安装。"
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
        bullet "工作区：${WORKSPACE_ROOT}（$(mode_label)）"
      else
        bullet "使用范围：当前用户的所有工作区"
      fi
      if [ "$KB_SHORTCUT_AVAILABLE" -eq 1 ]; then
        ok "终端可直接使用 kb。"
      elif [ "$KB_SHORTCUT_CREATED" -eq 1 ]; then
        note "已创建 kb 快捷入口，但它所在的目录还不在 PATH 中。"
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
  local py
  py=${RESEARCH_PYTHON:-python3}
  if "$py" -c 'import yaml' >/dev/null 2>&1; then
    return 0
  fi
  if [ "${RESEARCH_NO_MANAGED_VENV:-}" = "1" ]; then
    die "已关闭自动运行环境，但所选 Python 缺少 PyYAML；请先安装 requirements.txt 中的依赖"
  fi
  note "Python 依赖尚未就绪；首次使用时会自动准备，无需手动处理。" >&2
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
  expected="$REPO_ROOT/.agents/AGENTS.md"
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
    die "$WORKSPACE_ROOT 中已有其他 AGENTS.md；请先移动或合并后再安装"
  fi
  die "$WORKSPACE_ROOT 中已有 AGENTS.md；请先移动或合并后再安装"
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
    die "$WORKSPACE_ROOT/.agents 已存在，为避免覆盖已停止安装"
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
    "--source-branch" "$branch"
  )
  if [ "$origin" != "local" ] && [ -z "$branch" ]; then
    note "当前源码处于 detached 状态；本次安装绑定当前 commit，之后更新前需要选择分支。" >&2
  fi
  if [ "$origin" = "local" ]; then
    args+=("--source-checkout" "$REPO_ROOT")
  fi
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
  if output=$(python3 "$REPO_ROOT/install-lib/ws_sync.py" "${args[@]}" "$@"); then
    if [ "$action" = "update" ]; then
      case "$output" in
        *"clean-sync: no changes; manifest unchanged"*) UPDATE_NO_CHANGES=1 ;;
      esac
    fi
    if [ "$WIZARD_MODE" -eq 1 ] || { is_interactive_input && [ "$DRY_RUN" -eq 0 ] && [ "$action" != "update" ]; }; then
      if [ "$DRY_RUN" -eq 1 ]; then
        change_count=$(printf '%s\n' "$output" | awk '/^\[dry-run\]/ { count += 1 } END { print count + 0 }')
        bullet "底层文件操作：$change_count 项（详细路径已折叠）"
      else
        case "$action" in
          install) info "工作区文件已准备。" ;;
          reinstall) info "工作区文件已重新安装。" ;;
          uninstall) info "安装器管理的工作区文件已移除。" ;;
        esac
      fi
      return 0
    fi
    [ -z "$output" ] || printf '%s\n' "$output"
    return 0
  else
    status=$?
    [ -z "$output" ] || printf '%s\n' "$output"
    return "$status"
  fi
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
    INSTALL_INCOMPLETE=1
    return 0
  }
  [ -f "$WORKSPACE_ROOT/AGENTS.md" ] || return 0
  actual=$(file_sha256 "$WORKSPACE_ROOT/AGENTS.md")
  if [ -n "$sha" ] && [ "$actual" = "$sha" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] rm $(quote_path "$WORKSPACE_ROOT/AGENTS.md")"
    else
      rm "$WORKSPACE_ROOT/AGENTS.md"
    fi
  else
    warn "AGENTS.md 已被修改，予以保留"
    INSTALL_INCOMPLETE=1
  fi
}

uninstall_workspace_copy() {
  local had_manifest=0
  [ "$COPY_PROJECT" -eq 1 ] || die "卸载只适用于外部工作区"
  [ -d "$WORKSPACE_ROOT/.agents" ] && [ ! -L "$WORKSPACE_ROOT/.agents" ] || die "这个工作区没有可卸载的受管配置"
  manifest_is_ours "$MANIFEST_PATH" || die "无法确认安装记录，为避免误删已停止卸载"
  had_manifest=1
  remove_symlink_if_matches "$WORKSPACE_ROOT/.claude/skills" "../.agents/skills" "$SKILLS_SRC"
  remove_managed_block "$WORKSPACE_ROOT/CLAUDE.md"
  ws_sync uninstall
  uninstall_kb_on_path
  [ "$had_manifest" -eq 1 ] && info "研究资料和本地运行环境已保留；这个工作区现在不再由安装器管理。"
}

ensure_dir() {
  if [ "$DRY_RUN" -eq 1 ]; then
    [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] mkdir -p $(quote_path "$1")"
  else
    mkdir -p "$1"
  fi
}

link_force() {
  local target=$1 link=$2 actual
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    warn "已有文件未覆盖：$link"
    INSTALL_INCOMPLETE=1
    return 0
  fi
  if [ -L "$link" ]; then
    actual=$(readlink "$link")
    if [ "$actual" = "$target" ]; then
      return 0
    fi
    warn "已有链接指向其他位置，已保留：$link"
    INSTALL_INCOMPLETE=1
    return 0
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] ln -sfn $(quote_path "$target") $(quote_path "$link")"
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
      [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] rm $(quote_path "$link")"
    else
      rm "$link"
    fi
  else
    warn "链接目标与安装记录不一致，已保留：$link"
    INSTALL_INCOMPLETE=1
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
    [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] write managed block in $(quote_path "$file")"
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
    [ "$WIZARD_MODE" -eq 1 ] || info "[dry-run] remove managed block from $(quote_path "$file")"
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
      printf '<!-- Generated from %s/.agents/AGENTS.md for workspace %s. -->\n\n' "$REPO_ROOT" "$ws"
      sed -n '1,$p' "$REPO_ROOT/.agents/AGENTS.md"
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
    warn "kb 快捷入口已创建，但终端尚未搜索该目录：$dir"
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
  local smoke_output
  if [ "$DRY_RUN" -eq 1 ] || { [ "$ACTION" != "install" ] && [ "$ACTION" != "reinstall" ]; }; then
    return 0
  fi
  section "安装检查"
  info "正在检查 kb 基础功能..."
  if ! smoke_output=$("$WS_KB_SCRIPT" help 2>&1); then
    warn "kb 基础检查未通过，详细信息如下："
    printf '%s\n' "$smoke_output" >&2
    return 1
  fi
  if [ "$COPY_PROJECT" -eq 1 ]; then
    if ! smoke_output=$("$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor 2>&1); then
      warn "kb 工作区检查未通过，详细信息如下："
      printf '%s\n' "$smoke_output" >&2
      return 1
    fi
  else
    if ! smoke_output=$(RESEARCH_SKILLS_HOME="$REPO_ROOT" "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor 2>&1); then
      warn "kb 工作区检查未通过，详细信息如下："
      printf '%s\n' "$smoke_output" >&2
      return 1
    fi
  fi
  ok "kb 基础入口可用。"
}

if [ "$ACTION" != "uninstall" ]; then
  if [ "$ACTION" = "install" ] && [ "$COPY_PROJECT" -eq 1 ]; then
    guard_copy_install_target
  fi
fi

confirm_plan

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
    print_done Install
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
    print_done Update
    ;;
  reinstall)
    UPDATE_CONFIG_CLAUDE=0
    UPDATE_CONFIG_CODEX=0
    reinstall_workspace_copy
    UPDATE_CONFIG_CLAUDE=$(manifest_agent_enabled "$MANIFEST_PATH" claude 2>/dev/null || printf '1')
    UPDATE_CONFIG_CODEX=$(manifest_agent_enabled "$MANIFEST_PATH" codex 2>/dev/null || printf '0')
    if [ "$UPDATE_CONFIG_CLAUDE" = "1" ]; then
      install_claude_project
    fi
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
    [ "$KB_ON_PATH" -eq 1 ] && uninstall_kb_on_path
    if [ "$CORRUPT_MANIFEST_UNINSTALL" -eq 1 ]; then
      warn "研究资料和本地运行环境未被改动"
    fi
    print_done Uninstall
    ;;
  *)
    die "无法识别的操作：$ACTION"
    ;;
esac
