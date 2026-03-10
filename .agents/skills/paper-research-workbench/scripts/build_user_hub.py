#!/usr/bin/env python3
"""Build a local HTML hub for human-readable paper workspace outputs."""

from __future__ import annotations

import argparse
import html
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from _paper_utils import (
    compact_text,
    ensure_dir,
    load_yaml,
    relative_to_project,
    slugify,
    utc_now_iso,
    write_json_if_changed,
    write_text_if_changed,
)


def project_root_from_script() -> Path:
    # <project>/skills/paper-research-workbench/scripts/build_user_hub.py
    return Path(__file__).resolve().parents[3]


def load_metadata_records(papers_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(papers_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict) and payload.get("paper_id"):
            records.append(payload)
    records.sort(key=lambda item: (item.get("year") or 0, item.get("paper_id") or ""), reverse=True)
    return records


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("\n---\n", 1)
    if len(parts) == 2:
        return parts[1]
    return text


def markdown_preview(path: Path, max_lines: int = 4) -> str:
    if not path.exists():
        return ""
    text = strip_frontmatter(path.read_text(encoding="utf-8"))
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        return ""
    return compact_text(" ".join(lines[:max_lines]), max_len=220)


def relative_path(from_dir: Path, target: Path) -> str:
    return os.path.relpath(target, start=from_dir)


def build_neighbor_map(relationships: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    neighbor_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in relationships.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_paper_id") or "")
        target = str(edge.get("target_paper_id") or "")
        if not source or not target:
            continue
        payload = {
            "paper_id": target,
            "score": float(edge.get("score") or 0.0),
            "shared_topics": edge.get("shared_topics") or [],
            "shared_tags": edge.get("shared_tags") or [],
        }
        reverse = dict(payload)
        reverse["paper_id"] = source
        neighbor_map[source].append(payload)
        neighbor_map[target].append(reverse)
    for values in neighbor_map.values():
        values.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("paper_id") or "")))
    return dict(neighbor_map)


def build_payload(
    *,
    project_root: Path,
    papers_root: Path,
    user_root: Path,
    ai_root: Path,
    relationships_path: Path,
    topics_index_path: Path,
    frontier_ideas_path: Path,
) -> dict[str, Any]:
    records = load_metadata_records(papers_root)
    relationships = load_yaml(relationships_path) or {}
    topics_index = load_yaml(topics_index_path) or {}
    frontier_ideas = load_yaml(frontier_ideas_path) or {}
    neighbor_map = build_neighbor_map(relationships if isinstance(relationships, dict) else {})
    title_lookup = {
        str(record.get("paper_id") or ""): str(record.get("title") or record.get("paper_id") or "")
        for record in records
    }

    papers: list[dict[str, Any]] = []
    for record in records:
        paper_id = str(record.get("paper_id") or "")
        if not paper_id:
            continue
        user_paper_dir = user_root / "papers" / paper_id
        note_path = user_paper_dir / "note.md"
        ideas_path = user_paper_dir / "ideas.md"
        feasibility_path = user_paper_dir / "feasibility.md"
        papers.append(
            {
                "paper_id": paper_id,
                "title": str(record.get("title") or paper_id),
                "year": record.get("year"),
                "authors": record.get("authors") or [],
                "tags": record.get("tags") or [],
                "topics": record.get("topics") or [],
                "abstract": record.get("abstract") or "",
                "abstract_brief": compact_text(str(record.get("abstract") or ""), max_len=220),
                "arxiv_id": record.get("arxiv_id"),
                "doi": record.get("doi"),
                "source_pdf": record.get("source", {}).get("pdf") if isinstance(record.get("source"), dict) else None,
                "source_pdf_link": relative_path(user_root, project_root / str((record.get("source") or {}).get("pdf") or "")) if (record.get("source") or {}).get("pdf") else "",
                "metadata_path": relative_to_project(papers_root / paper_id / "metadata.yaml", project_root),
                "note_path": relative_path(user_root, note_path),
                "ideas_path": relative_path(user_root, ideas_path),
                "feasibility_path": relative_path(user_root, feasibility_path),
                "ai_node_path": relative_path(user_root, ai_root / "papers" / paper_id / "node.yaml"),
                "note_preview": markdown_preview(note_path),
                "idea_preview": markdown_preview(ideas_path),
                "feasibility_preview": markdown_preview(feasibility_path),
                "neighbors": [
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "title": title_lookup.get(str(item.get("paper_id") or ""), str(item.get("paper_id") or "")),
                        "score": item.get("score"),
                        "shared_topics": item.get("shared_topics") or [],
                        "shared_tags": item.get("shared_tags") or [],
                    }
                    for item in neighbor_map.get(paper_id, [])[:6]
                ],
            }
        )

    payload = {
        "generated_at": utc_now_iso(),
        "paper_count": len(papers),
        "edge_count": int((relationships or {}).get("edge_count") or len((relationships or {}).get("edges") or [])),
        "topic_count": int((topics_index or {}).get("count") or len((topics_index or {}).get("topics") or [])),
        "idea_count": len((frontier_ideas or {}).get("ideas") or []),
        "papers": papers,
        "edges": (relationships or {}).get("edges") or [],
        "topics": [
            {
                **topic,
                "file_name": f"{slugify(str(topic.get('topic') or ''), max_words=8)}.md",
            }
            for topic in ((topics_index or {}).get("topics") or [])
            if isinstance(topic, dict)
        ],
        "frontier_ideas": (frontier_ideas or {}).get("ideas") or [],
    }
    return payload


def render_html(payload: dict[str, Any], *, default_tab: str) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    title_text = "Paper Research Hub"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title_text)}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: rgba(255, 250, 242, 0.92);
      --panel-strong: #fffaf2;
      --ink: #1f2a2e;
      --muted: #6b746f;
      --line: rgba(31, 42, 46, 0.12);
      --accent: #0f766e;
      --accent-soft: rgba(15, 118, 110, 0.12);
      --accent-warm: #c26b3f;
      --shadow: 0 16px 48px rgba(27, 39, 38, 0.12);
      --radius: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(194, 107, 63, 0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(15, 118, 110, 0.14), transparent 32%),
        linear-gradient(180deg, #f8f3eb 0%, var(--bg) 100%);
      font-family: "Avenir Next", "Helvetica Neue", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    .shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: 320px 1fr;
    }}
    .sidebar {{
      padding: 28px 22px;
      border-right: 1px solid var(--line);
      background: rgba(255, 248, 239, 0.88);
      backdrop-filter: blur(18px);
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }}
    .brand {{
      margin-bottom: 22px;
      padding: 18px;
      border-radius: var(--radius);
      background: linear-gradient(135deg, rgba(15,118,110,.15), rgba(194,107,63,.08));
      box-shadow: var(--shadow);
    }}
    .brand h1 {{
      margin: 0 0 8px;
      font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-size: 28px;
      line-height: 1.05;
    }}
    .brand p {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .search {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.82);
      font-size: 14px;
      margin-bottom: 14px;
    }}
    .chipbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
    }}
    .chip {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.7);
      border-radius: 999px;
      padding: 7px 11px;
      font-size: 12px;
      cursor: pointer;
    }}
    .chip.active {{
      background: var(--accent);
      color: white;
      border-color: transparent;
    }}
    .paper-list {{
      display: grid;
      gap: 10px;
    }}
    .paper-item {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.72);
      border-radius: 16px;
      padding: 12px 13px;
      cursor: pointer;
      transition: transform .16s ease, box-shadow .16s ease;
    }}
    .paper-item:hover {{
      transform: translateY(-1px);
      box-shadow: 0 8px 24px rgba(27,39,38,.08);
    }}
    .paper-item.active {{
      border-color: rgba(15,118,110,.38);
      background: rgba(15,118,110,.1);
    }}
    .paper-item h3 {{
      margin: 0 0 6px;
      font-size: 14px;
      line-height: 1.35;
    }}
    .paper-item p {{
      margin: 0;
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .main {{
      padding: 26px;
      display: grid;
      gap: 18px;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: end;
    }}
    .topbar h2 {{
      margin: 0;
      font-family: "Palatino Linotype", "Book Antiqua", Georgia, serif;
      font-size: 34px;
      line-height: 1.05;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }}
    .card {{
      padding: 16px 18px;
      border-radius: var(--radius);
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .card .value {{
      font-size: 30px;
      font-weight: 700;
      margin-top: 4px;
    }}
    .tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tab {{
      border: none;
      background: rgba(255,255,255,.68);
      border-radius: 999px;
      padding: 10px 14px;
      cursor: pointer;
      font-size: 14px;
      border: 1px solid var(--line);
    }}
    .tab.active {{
      background: var(--ink);
      color: white;
      border-color: transparent;
    }}
    .panel {{
      display: none;
      padding: 18px;
      border-radius: 22px;
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .panel.active {{ display: block; }}
    .overview-grid {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 18px;
    }}
    .stack {{
      display: grid;
      gap: 12px;
    }}
    .paper-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,.74);
      padding: 16px;
    }}
    .paper-card h3, .detail h3 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.3;
    }}
    .subtle {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .tagline {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .tag {{
      padding: 4px 9px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: 1fr 320px;
      gap: 18px;
    }}
    .linklist {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
    }}
    .linkbtn {{
      display: block;
      padding: 11px 12px;
      border-radius: 14px;
      background: rgba(15,118,110,.08);
      border: 1px solid rgba(15,118,110,.12);
      color: var(--ink);
    }}
    .ideas {{
      display: grid;
      gap: 14px;
    }}
    .idea-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,.72);
    }}
    .idea-card h3 {{
      margin: 0 0 10px;
      font-size: 18px;
    }}
    .graph-wrap {{
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 18px;
      min-height: 640px;
    }}
    .graph-card {{
      position: relative;
      min-height: 640px;
      border-radius: 20px;
      overflow: hidden;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.84), rgba(249,243,235,.95));
    }}
    canvas {{
      width: 100%;
      height: 640px;
      display: block;
    }}
    .legend {{
      position: absolute;
      left: 16px;
      top: 16px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .legend span {{
      font-size: 12px;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(255,255,255,.86);
      border: 1px solid var(--line);
    }}
    .topic-list {{
      display: grid;
      gap: 10px;
    }}
    .topic-row {{
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      background: rgba(255,255,255,.72);
    }}
    @media (max-width: 1100px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--line);
      }}
      .cards, .overview-grid, .detail-grid, .graph-wrap {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body data-default-tab="{html.escape(default_tab)}">
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <h1>Paper Research Hub</h1>
        <p>用户阅读区入口。这里聚合论文列表、关系图、主题索引和综合 idea，同时保留到可编辑 `ideas.md` 的直达入口。</p>
      </div>
      <input id="searchInput" class="search" type="search" placeholder="搜索论文标题、tag、topic">
      <div id="chipbar" class="chipbar"></div>
      <div id="paperList" class="paper-list"></div>
    </aside>
    <main class="main">
      <div class="topbar">
        <div>
          <h2>本地论文工作台</h2>
          <div class="meta">生成时间：<span id="generatedAt"></span></div>
        </div>
        <div class="meta">建议入口：先看综合 idea，再看关系图，最后进入单篇可编辑文件。</div>
      </div>
      <section class="cards">
        <div class="card"><div>论文数量</div><div id="paperCount" class="value">0</div></div>
        <div class="card"><div>关系边数量</div><div id="edgeCount" class="value">0</div></div>
        <div class="card"><div>主题数量</div><div id="topicCount" class="value">0</div></div>
        <div class="card"><div>综合 Idea</div><div id="ideaCount" class="value">0</div></div>
      </section>
      <section class="tabs">
        <button class="tab" data-tab="overview">总览</button>
        <button class="tab" data-tab="graph">关系图</button>
        <button class="tab" data-tab="ideas">综合 Idea</button>
        <button class="tab" data-tab="detail">论文详情</button>
      </section>
      <section id="panel-overview" class="panel">
        <div class="overview-grid">
          <div class="stack" id="overviewPapers"></div>
          <div class="stack">
            <div class="paper-card">
              <h3>主题入口</h3>
              <div id="topicList" class="topic-list"></div>
            </div>
            <div class="paper-card">
              <h3>用户文件入口</h3>
              <div class="linklist">
                <a class="linkbtn" href="graph.html">打开可视化关系图</a>
                <a class="linkbtn" href="topic-maps/index.md">打开主题图谱总览</a>
                <a class="linkbtn" href="syntheses/frontier-ideas.md">打开综合 Idea Markdown</a>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section id="panel-graph" class="panel">
        <div class="graph-wrap">
          <div class="graph-card">
            <div class="legend">
              <span>点击节点查看详情</span>
              <span>线越多越说明库内关系更密</span>
            </div>
            <canvas id="graphCanvas" width="1200" height="800"></canvas>
          </div>
          <div class="paper-card detail" id="graphDetail"></div>
        </div>
      </section>
      <section id="panel-ideas" class="panel">
        <div id="ideaList" class="ideas"></div>
      </section>
      <section id="panel-detail" class="panel">
        <div id="detailPanel" class="detail-grid"></div>
      </section>
    </main>
  </div>
  <script id="app-data" type="application/json">{html.escape(data_json)}</script>
  <script>
    const data = JSON.parse(document.getElementById("app-data").textContent);
    const state = {{
      query: "",
      topic: "",
      selectedPaperId: data.papers[0] ? data.papers[0].paper_id : null,
      activeTab: document.body.dataset.defaultTab || "overview"
    }};
    const paperMap = new Map(data.papers.map((paper) => [paper.paper_id, paper]));

    const searchInput = document.getElementById("searchInput");
    const chipbar = document.getElementById("chipbar");
    const paperList = document.getElementById("paperList");
    const overviewPapers = document.getElementById("overviewPapers");
    const topicList = document.getElementById("topicList");
    const ideaList = document.getElementById("ideaList");
    const detailPanel = document.getElementById("detailPanel");
    const graphDetail = document.getElementById("graphDetail");
    const generatedAt = document.getElementById("generatedAt");
    const paperCount = document.getElementById("paperCount");
    const edgeCount = document.getElementById("edgeCount");
    const topicCount = document.getElementById("topicCount");
    const ideaCount = document.getElementById("ideaCount");
    const tabs = Array.from(document.querySelectorAll(".tab"));
    const panels = Array.from(document.querySelectorAll(".panel"));

    generatedAt.textContent = data.generated_at;
    paperCount.textContent = data.paper_count;
    edgeCount.textContent = data.edge_count;
    topicCount.textContent = data.topic_count;
    ideaCount.textContent = data.idea_count;

    function escapeHtml(value) {{
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }}

    function filteredPapers() {{
      const query = state.query.trim().toLowerCase();
      return data.papers.filter((paper) => {{
        const haystack = [
          paper.title,
          ...(paper.tags || []),
          ...(paper.topics || []),
          ...(paper.authors || [])
        ].join(" ").toLowerCase();
        if (query && !haystack.includes(query)) {{
          return false;
        }}
        if (state.topic && !(paper.topics || []).includes(state.topic)) {{
          return false;
        }}
        return true;
      }});
    }}

    function selectPaper(paperId, tab) {{
      state.selectedPaperId = paperId;
      if (tab) {{
        state.activeTab = tab;
      }}
      render();
    }}

    function renderTabs() {{
      tabs.forEach((tab) => {{
        tab.classList.toggle("active", tab.dataset.tab === state.activeTab);
      }});
      panels.forEach((panel) => {{
        panel.classList.toggle("active", panel.id === `panel-${{state.activeTab}}`);
      }});
    }}

    function renderSidebar() {{
      const topics = data.topics.slice(0, 8);
      chipbar.innerHTML = [
        `<button class="chip ${{state.topic === "" ? "active" : ""}}" data-topic="">全部</button>`,
        ...topics.map((topic) => `<button class="chip ${{state.topic === topic.topic ? "active" : ""}}" data-topic="${{escapeHtml(topic.topic)}}">${{escapeHtml(topic.topic)}} (${{topic.count}})</button>`)
      ].join("");
      chipbar.querySelectorAll(".chip").forEach((button) => {{
        button.addEventListener("click", () => {{
          state.topic = button.dataset.topic || "";
          render();
        }});
      }});

      const papers = filteredPapers();
      paperList.innerHTML = papers.map((paper) => `
        <div class="paper-item ${{state.selectedPaperId === paper.paper_id ? "active" : ""}}" data-paper-id="${{paper.paper_id}}">
          <h3>${{escapeHtml(paper.title)}}</h3>
          <p>${{escapeHtml((paper.topics || []).join(" / "))}}</p>
        </div>
      `).join("");
      paperList.querySelectorAll(".paper-item").forEach((item) => {{
        item.addEventListener("click", () => selectPaper(item.dataset.paperId, "detail"));
      }});
    }}

    function renderOverview() {{
      const papers = filteredPapers().slice(0, 6);
      overviewPapers.innerHTML = papers.map((paper) => `
        <div class="paper-card">
          <h3>${{escapeHtml(paper.title)}}</h3>
          <div class="subtle">${{escapeHtml((paper.authors || []).slice(0, 4).join(", "))}}${{(paper.authors || []).length > 4 ? " ..." : ""}} | ${{paper.year || "n/a"}}</div>
          <p class="subtle">${{escapeHtml(paper.note_preview || paper.abstract_brief || "暂无摘要预览")}}</p>
          <div class="tagline">${{(paper.tags || []).slice(0, 5).map((tag) => `<span class="tag">${{escapeHtml(tag)}}</span>`).join("")}}</div>
          <div class="linklist">
            <a class="linkbtn" href="${{escapeHtml(paper.note_path)}}">打开笔记</a>
            <a class="linkbtn" href="${{escapeHtml(paper.ideas_path)}}">编辑 Idea</a>
          </div>
        </div>
      `).join("");

      topicList.innerHTML = data.topics.map((topic) => `
        <div class="topic-row">
          <strong>${{escapeHtml(topic.topic)}}</strong>
          <div class="subtle">${{topic.count}} 篇论文</div>
          <div class="subtle"><a href="topic-maps/${{escapeHtml(topic.file_name || "")}}">打开主题图谱</a></div>
        </div>
      `).join("");
    }}

    function renderIdeaList() {{
      ideaList.innerHTML = (data.frontier_ideas || []).map((idea, index) => `
        <div class="idea-card">
          <h3>Idea ${{index + 1}}：${{escapeHtml(idea.title)}}</h3>
          <div class="subtle">主题锚点：${{escapeHtml(idea.topic_anchor || "")}}</div>
          <p><strong>为什么值得做：</strong>${{escapeHtml(idea.why_now || "")}}</p>
          <p><strong>最小可执行实验：</strong>${{escapeHtml(idea.minimum_viable_experiment || "")}}</p>
          <p><strong>预期收益：</strong>${{escapeHtml(idea.expected_gain || "")}}</p>
          <p><strong>主要风险：</strong>${{escapeHtml(idea.main_risk || "")}}</p>
          <div class="tagline">
            <span class="tag">priority: ${{escapeHtml(idea.priority || "")}}</span>
            <span class="tag">difficulty: ${{escapeHtml(idea.execution_difficulty || "")}}</span>
          </div>
        </div>
      `).join("");
    }}

    function renderPaperDetail(target, paper) {{
      if (!paper) {{
        target.innerHTML = `<div class="paper-card"><h3>暂无论文</h3></div>`;
        return;
      }}
      const neighbors = (paper.neighbors || []).map((item) => `
        <div class="topic-row">
          <strong>${{escapeHtml(item.title)}}</strong>
          <div class="subtle">score=${{item.score}} | topic=${{escapeHtml((item.shared_topics || []).join(" / "))}}</div>
        </div>
      `).join("");
      target.innerHTML = `
        <div class="paper-card detail">
          <h3>${{escapeHtml(paper.title)}}</h3>
          <div class="subtle">${{escapeHtml((paper.authors || []).join(", "))}}</div>
          <div class="subtle">paper_id: ${{escapeHtml(paper.paper_id)}} | year: ${{paper.year || "n/a"}}</div>
          <p>${{escapeHtml(paper.abstract_brief || "暂无摘要")}}</p>
          <div class="tagline">${{(paper.topics || []).map((topic) => `<span class="tag">${{escapeHtml(topic)}}</span>`).join("")}}</div>
          <div class="tagline">${{(paper.tags || []).map((tag) => `<span class="tag">${{escapeHtml(tag)}}</span>`).join("")}}</div>
          <div class="linklist">
            <a class="linkbtn" href="${{escapeHtml(paper.note_path)}}">打开 note.md</a>
            <a class="linkbtn" href="${{escapeHtml(paper.ideas_path)}}">打开 ideas.md</a>
            <a class="linkbtn" href="${{escapeHtml(paper.feasibility_path)}}">打开 feasibility.md</a>
            <a class="linkbtn" href="${{escapeHtml(paper.ai_node_path)}}">打开 AI node</a>
            ${{paper.source_pdf_link ? `<a class="linkbtn" href="${{escapeHtml(paper.source_pdf_link)}}">打开原始 PDF</a>` : ""}}
          </div>
        </div>
        <div class="paper-card">
          <h3>联读与编辑提示</h3>
          <div class="subtle">${{escapeHtml(paper.idea_preview || paper.feasibility_preview || "建议先看综合 Idea，再编辑这篇论文的 ideas.md。")}}</div>
          <h3 style="margin-top:18px;">近邻论文</h3>
          <div class="topic-list">${{neighbors || "<div class='subtle'>暂无近邻论文。</div>"}}</div>
        </div>
      `;
    }}

    const graphCanvas = document.getElementById("graphCanvas");
    const ctx = graphCanvas.getContext("2d");
    let graphNodes = [];
    let graphEdges = [];

    function initGraph() {{
      const width = graphCanvas.width;
      const height = graphCanvas.height;
      graphNodes = data.papers.map((paper, index) => {{
        const angle = (Math.PI * 2 * index) / Math.max(data.papers.length, 1);
        return {{
          id: paper.paper_id,
          label: paper.title,
          degree: (paper.neighbors || []).length || 1,
          x: width / 2 + Math.cos(angle) * 180 + (index % 3) * 15,
          y: height / 2 + Math.sin(angle) * 180 + (index % 4) * 18,
          vx: 0,
          vy: 0
        }};
      }});
      graphEdges = (data.edges || []).map((edge) => ({{
        source: graphNodes.find((node) => node.id === edge.source_paper_id),
        target: graphNodes.find((node) => node.id === edge.target_paper_id),
        score: Number(edge.score || 0)
      }})).filter((edge) => edge.source && edge.target);
      for (let step = 0; step < 220; step += 1) {{
        simulateGraph();
      }}
      drawGraph();
    }}

    function simulateGraph() {{
      const width = graphCanvas.width;
      const height = graphCanvas.height;
      for (const node of graphNodes) {{
        let fx = (width / 2 - node.x) * 0.0009;
        let fy = (height / 2 - node.y) * 0.0009;
        for (const other of graphNodes) {{
          if (node === other) continue;
          const dx = node.x - other.x;
          const dy = node.y - other.y;
          const dist2 = Math.max(dx * dx + dy * dy, 90);
          fx += (dx / dist2) * 45;
          fy += (dy / dist2) * 45;
        }}
        node.vx = (node.vx + fx) * 0.9;
        node.vy = (node.vy + fy) * 0.9;
      }}
      for (const edge of graphEdges) {{
        const dx = edge.target.x - edge.source.x;
        const dy = edge.target.y - edge.source.y;
        const dist = Math.max(Math.hypot(dx, dy), 1);
        const desired = 170 - Math.min(edge.score * 4, 55);
        const force = (dist - desired) * 0.0025;
        const fx = dx * force;
        const fy = dy * force;
        edge.source.vx += fx;
        edge.source.vy += fy;
        edge.target.vx -= fx;
        edge.target.vy -= fy;
      }}
      for (const node of graphNodes) {{
        node.x = Math.min(width - 30, Math.max(30, node.x + node.vx));
        node.y = Math.min(height - 30, Math.max(30, node.y + node.vy));
      }}
    }}

    function drawGraph() {{
      const width = graphCanvas.width;
      const height = graphCanvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "rgba(244,239,230,1)";
      ctx.fillRect(0, 0, width, height);
      for (const edge of graphEdges) {{
        ctx.strokeStyle = "rgba(31,42,46,0.14)";
        ctx.lineWidth = 1 + Math.min(edge.score / 8, 2.8);
        ctx.beginPath();
        ctx.moveTo(edge.source.x, edge.source.y);
        ctx.lineTo(edge.target.x, edge.target.y);
        ctx.stroke();
      }}
      for (const node of graphNodes) {{
        const selected = node.id === state.selectedPaperId;
        ctx.beginPath();
        ctx.fillStyle = selected ? "#c26b3f" : "#0f766e";
        ctx.globalAlpha = selected ? 0.95 : 0.8;
        ctx.arc(node.x, node.y, 10 + Math.min(node.degree * 1.4, 10), 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.fillStyle = "#1f2a2e";
        ctx.font = selected ? "600 13px Avenir Next" : "12px Avenir Next";
        ctx.fillText(node.label.slice(0, 28), node.x + 14, node.y + 4);
      }}
      renderPaperDetail(graphDetail, paperMap.get(state.selectedPaperId));
    }}

    graphCanvas.addEventListener("click", (event) => {{
      const rect = graphCanvas.getBoundingClientRect();
      const scaleX = graphCanvas.width / rect.width;
      const scaleY = graphCanvas.height / rect.height;
      const x = (event.clientX - rect.left) * scaleX;
      const y = (event.clientY - rect.top) * scaleY;
      let best = null;
      let bestDist = Infinity;
      for (const node of graphNodes) {{
        const dist = Math.hypot(node.x - x, node.y - y);
        if (dist < bestDist) {{
          best = node;
          bestDist = dist;
        }}
      }}
      if (best && bestDist < 34) {{
        selectPaper(best.id, "graph");
      }}
    }});

    function render() {{
      renderTabs();
      renderSidebar();
      renderOverview();
      renderIdeaList();
      renderPaperDetail(detailPanel, paperMap.get(state.selectedPaperId));
      drawGraph();
    }}

    tabs.forEach((tab) => {{
      tab.addEventListener("click", () => {{
        state.activeTab = tab.dataset.tab;
        render();
      }});
    }});

    searchInput.addEventListener("input", () => {{
      state.query = searchInput.value;
      render();
    }});

    initGraph();
    render();
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a self-contained local HTML hub for user-readable paper outputs.",
    )
    parser.add_argument(
        "--papers-root",
        default="doc/papers/papers",
        help="Internal paper data root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--user-root",
        default="doc/papers/user",
        help="User-readable output root (default: doc/papers/user)",
    )
    parser.add_argument(
        "--ai-root",
        default="doc/papers/ai",
        help="AI-readable output root (default: doc/papers/ai)",
    )
    parser.add_argument(
        "--relationships-path",
        default="doc/papers/index/relationships.yaml",
        help="Relationship index path",
    )
    parser.add_argument(
        "--topics-index",
        default="doc/papers/index/topics.yaml",
        help="Topics index path",
    )
    parser.add_argument(
        "--frontier-ideas-path",
        default="doc/papers/ai/frontier-ideas.yaml",
        help="Structured frontier ideas path",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    papers_root = (project_root / args.papers_root).resolve()
    user_root = (project_root / args.user_root).resolve()
    ai_root = (project_root / args.ai_root).resolve()
    relationships_path = (project_root / args.relationships_path).resolve()
    topics_index_path = (project_root / args.topics_index).resolve()
    frontier_ideas_path = (project_root / args.frontier_ideas_path).resolve()

    ensure_dir(user_root)
    ensure_dir(user_root / "data")

    payload = build_payload(
        project_root=project_root,
        papers_root=papers_root,
        user_root=user_root,
        ai_root=ai_root,
        relationships_path=relationships_path,
        topics_index_path=topics_index_path,
        frontier_ideas_path=frontier_ideas_path,
    )

    write_json_if_changed(user_root / "data" / "hub.json", payload)
    write_json_if_changed(user_root / "data" / "papers.json", {"papers": payload["papers"]})
    write_json_if_changed(user_root / "data" / "graph.json", {"edges": payload["edges"]})
    write_json_if_changed(user_root / "data" / "frontier-ideas.json", {"ideas": payload["frontier_ideas"]})
    write_json_if_changed(user_root / "data" / "topics.json", {"topics": payload["topics"]})
    write_text_if_changed(user_root / "index.html", render_html(payload, default_tab="overview"))
    write_text_if_changed(user_root / "graph.html", render_html(payload, default_tab="graph"))
    print(f"[OK] user hub built: papers={payload['paper_count']}")


if __name__ == "__main__":
    main()
