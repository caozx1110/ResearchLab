# Research Navigator

Repository-only maintainer/development projection tool. It is not installed,
discoverable, routable, or represented in the runtime preference registry.

> 协议参考：`runtime/lib/research/SCHEMAS.md#program-files` · `#evidence-first-outputs` · `#ownership` · `#runtime`

This is an optional maintainer/development helper for rebuilding derived pages or a local browser snapshot. Normal users start from `kb init`, `kb status`, `kb next`, and `kb obsidian`; generic navigation requests must not route here automatically. Nothing generated here is canonical or a formal selling point.

## Scope

- Refresh durable human-facing pages under `kb/user/`.
- Build a local browser snapshot from `kb/units/`, `kb/programs/`, `kb/synthesis/`, `kb/user/`, and `kb/config/`.
- Program browser cards target the core program-root `state.yaml` / `README.md` layout.
- Keep source records canonical; browser output is generated under `kb/user/kb/`.
- The browser supports a Workbench, Markdown preview/edit for `.md`/`.txt`, and portrait-friendly narrow-window adaptation. Terminal and system-terminal surfaces are disabled by default and are maintainer-only when explicitly enabled.
- The browser editor is intentionally limited to `.md`/`.txt`; it can update markdown/text notes and trigger a configured checkpoint. Do not mutate raw sources or canonical YAML through the browser.
- 在 current state、reading list 或 browser 中呈现 survey 前，纯读复算它的 `consumer_binding`。相同 selection 新增 unit、已有 unit 的 content/confirmation/evidence 变化或删除都标为 stale，并给出重新 prepare/fill/verify 的自然语言建议；不得为更新状态而改写 survey。

## Maintainer/private commands

The following implementation commands are for Agent execution, maintenance, and isolated tests only. Never copy them into user-visible guidance or stdout.

```bash
python3 tools/research-navigator/scripts/navigate.py refresh
python3 tools/research-navigator/scripts/navigate.py current-state
python3 tools/research-navigator/scripts/navigate.py reading-list

python3 tools/research-navigator/scripts/build_kb_browser.py
python3 tools/research-navigator/scripts/open_kb_browser.py
python3 tools/research-navigator/scripts/open_user_hub.py   # compatibility alias
python3 tools/research-navigator/scripts/status_kb_browser.py
python3 tools/research-navigator/scripts/stop_kb_browser.py
python3 tools/research-navigator/scripts/serve_kb_browser.py
```

## 启动澄清（Agent 用）

- 刷新哪个投影：`kb/user/` 页面还是本地浏览器快照？默认仅 user 页面。
- 确认这是维护/开发场景；普通导航默认回 `kb status` / `kb next`，不路由到此。
