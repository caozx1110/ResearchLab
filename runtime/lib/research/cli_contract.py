"""Dependency-free public kb command contract used during cold bootstrap."""

from __future__ import annotations

import re


HELP_MENU: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "kb 动词（16 个）",
        (
            ("打印能力菜单。", "kb help"),
            ("初始化知识库布局、索引和基础偏好。", "kb init"),
            ("检查运行环境、配置读写与论文解析能力，并检查材料 Markdown 转换能力。", "kb doctor"),
            ("检查并在确认后更新研究能力包。", "kb update"),
            ("生成或检查可由 Obsidian 直接浏览的知识网络视图。", "kb obsidian update / kb obsidian status"),
            ("刷新并查看当前知识库和研究计划的状态摘要。", "kb status"),
            ("查看下一步实验或研究计划推进建议。", "kb next"),
            ("按关键词检索已入库知识单元。", "kb find <关键词>"),
            ("把论文、代码仓、博客或本地文件轻量入库。", "kb add <链接或路径>"),
            ("一条命令把资料来源加入知识库并备好待填骨架，随后 Agent 自动填写有逐字证据支持的笔记。", "kb ingest <链接或路径>"),
            ("查看待确认的 AI 判断，并用自然语言确认或拒绝。", "kb review"),
            ("把误建或不采纳的知识单元标记为已拒绝。", "kb reject <单元编号>"),
            ("回忆已确认习惯、已知坑和待审能力问题。", "kb recall"),
            ("恢复崩溃后未完成的知识库操作。", "kb resume"),
            ("撤销最近一次已提交的知识库操作。", "kb undo"),
            ("恢复到指定操作之前的状态；不带编号时先列出最近可恢复的操作。", "kb restore <操作编号>"),
        ),
    ),
    (
        "纯自然语言（无 kb 动词）",
        (
            ("执行有界文献检索，说明检索范围、筛选依据、遗漏风险和停止理由。", "帮我检索近两年的相关论文，并给出有证据的候选清单"),
            ("完成从检索、筛选、入库分析到可确认综合结论的完整 survey 路线。", "围绕这个研究问题完成一轮完整 survey，证据不足时明确停下来"),
            ("建立定期研究监控；没有宿主自动化时在下次继续研究时检查到期项。", "每两周关注这个方向的新论文，并记录每次结果"),
            ("维护总偏好，并只把当前任务相关的偏好交给对应研究能力。", "记住我的研究偏好，并只在相关任务中使用"),
            ("在 Obsidian 查看待确认批次；勾选后回到对话复述并一次处理这些选择。", "把待确认项导出到 Obsidian，等我勾选后再一起确认"),
            ("围绕当前知识库推进候选 idea 的生成、分析和选择。", "请基于当前知识库给我 3 个候选 idea"),
            ("汇总研究计划事件，生成周报、PPT 素材或阶段总结。", "为这个研究计划生成周报材料"),
        ),
    ),
)


def _help_verb_label(ai_phrase: str) -> str:
    """Derive the verb's own name (for example ``kb init``) from an example."""
    tokens = ai_phrase.split()
    if len(tokens) >= 2 and tokens[0] == "kb" and re.fullmatch(r"[a-z][a-z-]*", tokens[1]):
        return f"kb {tokens[1]}"
    return ""


def render_help_menu() -> str:
    lines = ["# kb 快捷命令", ""]
    for group, items in HELP_MENU:
        lines.append(f"## {group}")
        for sentence, ai_phrase in items:
            verb = _help_verb_label(ai_phrase)
            if verb:
                lines.append(f'- {verb} — {sentence} 也可以直接对 AI 说："{ai_phrase}"。')
            else:
                lines.append(f'- {sentence} 也可以直接对 AI 说："{ai_phrase}"。')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["HELP_MENU", "render_help_menu"]
