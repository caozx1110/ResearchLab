## [ERR-20260411-001] weekly-report-author-runtime

**Logged**: 2026-04-11T13:48:55Z
**Priority**: medium
**Status**: pending
**Area**: docs

### Summary
`weekly-report-author` 在当前 shell 默认 Python 下无法运行，因为缺少 `PyYAML`，需要改用仓库记忆的 `research-default` 解释器。

### Error
```text
research-conductor requires a stable research runtime, but the current interpreter is missing: PyYAML.
Current python: /Applications/Xcode.app/Contents/Developer/usr/bin/python3
Current version: 3.9.6
Current capabilities: yaml=False, pdf=False (missing)
Remembered preferred runtime: research-default at /Users/czx/miniconda3/bin/python3
Retry with the remembered interpreter or refresh it with `python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --python <path-to-python> --label research-default`.
```

### Context
- Command attempted: `python3 .agents/skills/weekly-report-author/scripts/write_weekly_report.py --program-id humanoid-vla-wholebody-control --days 9 --end-date 2026-04-11`
- Workspace: `/Users/czx/Documents/rl2lab/projects/vla/workspace`
- Runtime note: preferred interpreter already exists at `/Users/czx/miniconda3/bin/python3`

### Suggested Fix
在研究类技能脚本前优先使用记忆中的 `research-default` 解释器，避免落回系统自带 Python。

### Metadata
- Reproducible: yes
- Related Files: `.agents/skills/weekly-report-author/scripts/write_weekly_report.py`

---

## [ERR-20260412-001] research-note-author-pdf-surrogates

**Logged**: 2026-04-12T15:23:51Z
**Priority**: high
**Status**: pending
**Area**: docs

### Summary
批量生成论文 `note-context.md` 时，部分 PDF 提取文本包含非法 surrogate 字符，导致 `write_text_if_changed` 在 UTF-8 写盘阶段失败。

### Error
```text
UnicodeEncodeError: 'utf-8' codec can't encode characters in position 8181-8182: surrogates not allowed
```

### Context
- Command attempted: `/Users/czx/miniconda3/bin/python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --with-context --source-id ...`
- Workspace: `/Users/czx/Documents/rl2lab/projects/vla/workspace`
- Failure point: `.agents/skills/research-note-author/scripts/prepare_note_assets.py` writing literature note context

### Suggested Fix
在 `research-note-author` 写入 `note-context.md` 或脚手架笔记前统一做 UTF-8 安全清洗，剔除 PDF 解析器产生的 surrogate 字符。

### Metadata
- Reproducible: yes
- Related Files: `.agents/skills/research-note-author/scripts/prepare_note_assets.py`

---
