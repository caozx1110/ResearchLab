(function () {
  const config = window.RESEARCH_KB_BROWSER || {};
  const snapshotUrl = config.snapshotUrl || "./snapshot.json";
  const versionUrl = config.versionUrl || "/api/version";
  const pollMs = Number(config.pollMs || 3000);

  const TAB_CONFIG = [
    { id: "overview", label: "总览", countKey: "", unit: "视图" },
    { id: "literature", label: "论文", countKey: "literature_count", unit: "篇" },
    { id: "repos", label: "仓库", countKey: "repo_count", unit: "个" },
    { id: "tags", label: "标签", countKey: "tag_count", unit: "个" },
    { id: "landscapes", label: "趋势", countKey: "landscape_count", unit: "个" },
    { id: "programs", label: "Program", countKey: "program_count", unit: "个" },
  ];

  const PROGRAM_STAGES = [
    { id: "problem-framing", label: "问题定义" },
    { id: "literature-analysis", label: "文献分析" },
    { id: "idea-generation", label: "想法生成" },
    { id: "idea-review", label: "方案评审" },
    { id: "method-design", label: "方法设计" },
    { id: "implementation-planning", label: "实现规划" },
  ];

  const stageIndexMap = PROGRAM_STAGES.reduce((acc, stage, index) => {
    acc[stage.id] = index;
    return acc;
  }, {});

  const state = {
    snapshot: null,
    version: "",
    tab: "overview",
    query: "",
    selected: {
      overview: "",
      literature: "",
      repos: "",
      tags: "",
      landscapes: "",
      programs: "",
    },
    filters: {
      literatureTag: "all",
      literatureTopic: "all",
      literatureYear: "all",
      repoTag: "all",
      repoFramework: "all",
      tagStatus: "all",
      landscapeScope: "all",
      programStage: "all",
    },
    programStageView: {},
    live: {
      buildStatus: "loading",
      generatedAt: "",
      lastError: "",
    },
  };

  const elements = {
    search: document.getElementById("globalSearch"),
    tabNav: document.getElementById("tabNav"),
    filterBar: document.getElementById("filterBar"),
    listTitle: document.getElementById("listTitle"),
    listMeta: document.getElementById("listMeta"),
    listContainer: document.getElementById("listContainer"),
    detailTitle: document.getElementById("detailTitle"),
    detailMeta: document.getElementById("detailMeta"),
    detailBody: document.getElementById("detailBody"),
    liveStatus: document.getElementById("liveStatus"),
    updatedAt: document.getElementById("updatedAt"),
  };

  function norm(value) {
    return String(value || "").trim().toLowerCase();
  }

  function compactText(text, limit = 180) {
    const normalized = String(text || "").replace(/\s+/g, " ").trim();
    if (normalized.length <= limit) return normalized;
    return `${normalized.slice(0, Math.max(0, limit - 3)).trim()}...`;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtList(items, empty = "暂无") {
    return Array.isArray(items) && items.length ? items.join("、") : empty;
  }

  function fmtTime(value) {
    if (!value) return "未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function badge(text, klass = "") {
    if (!text) return "";
    return `<span class="badge ${klass}">${escapeHtml(text)}</span>`;
  }

  function linkChip(link, label) {
    if (!link) return "";
    const href = typeof link === "string" ? link : link.href;
    if (!href) return "";
    return `<a class="link-chip" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
  }

  function getSnapshot() {
    return state.snapshot || {
      service: "",
      project_name: "",
      generated_at: "",
      snapshot_version: "",
      last_updated: "",
      global_stats: {},
      workspace_profile: {},
      literature_items: [],
      repo_items: [],
      tag_items: [],
      landscape_items: [],
      program_items: [],
    };
  }

  function snapshotCount(key) {
    const stats = getSnapshot().global_stats || {};
    return Number(stats[key] || 0);
  }

  function uniqueValues(items, key) {
    const seen = new Set();
    const values = [];
    (items || []).forEach((item) => {
      const raw = item ? item[key] : null;
      if (Array.isArray(raw)) {
        raw.forEach((entry) => {
          const normalized = String(entry || "").trim();
          if (normalized && !seen.has(normalized)) {
            seen.add(normalized);
            values.push(normalized);
          }
        });
      } else {
        const normalized = String(raw || "").trim();
        if (normalized && !seen.has(normalized)) {
          seen.add(normalized);
          values.push(normalized);
        }
      }
    });
    return values.sort((a, b) => a.localeCompare(b));
  }

  function renderTabNav() {
    elements.tabNav.innerHTML = TAB_CONFIG.map((tab) => {
      const selected = state.tab === tab.id ? "active" : "";
      const countText = tab.countKey ? `${snapshotCount(tab.countKey)} ${tab.unit}` : "工作区快照";
      return `
        <button class="tab-button ${selected}" data-tab="${tab.id}">
          <span class="tab-label">${escapeHtml(tab.label)}</span>
          <span class="tab-count">${escapeHtml(countText)}</span>
        </button>
      `;
    }).join("");
  }

  function filterSpecsForCurrentTab() {
    const snapshot = getSnapshot();
    if (state.tab === "literature") {
      return [
        { key: "literatureTag", label: "标签", options: uniqueValues(snapshot.literature_items || [], "tags") },
        { key: "literatureTopic", label: "主题", options: uniqueValues(snapshot.literature_items || [], "topics") },
        {
          key: "literatureYear",
          label: "年份",
          options: uniqueValues(snapshot.literature_items || [], "year").sort((a, b) => Number(b) - Number(a)),
        },
      ];
    }
    if (state.tab === "repos") {
      return [
        { key: "repoTag", label: "标签", options: uniqueValues(snapshot.repo_items || [], "tags") },
        { key: "repoFramework", label: "框架", options: uniqueValues(snapshot.repo_items || [], "frameworks") },
      ];
    }
    if (state.tab === "tags") {
      return [{ key: "tagStatus", label: "状态", options: uniqueValues(snapshot.tag_items || [], "status") }];
    }
    if (state.tab === "landscapes") {
      return [{ key: "landscapeScope", label: "范围", options: uniqueValues(snapshot.landscape_items || [], "scope") }];
    }
    if (state.tab === "programs") {
      return [{ key: "programStage", label: "阶段", options: uniqueValues(snapshot.program_items || [], "stage") }];
    }
    return [];
  }

  function renderFilterBar() {
    const specs = filterSpecsForCurrentTab();
    if (!specs.length) {
      elements.filterBar.innerHTML = '<span class="inline-hint">当前视图无额外筛选，直接搜索即可。</span>';
      return;
    }
    elements.filterBar.innerHTML = specs
      .map((spec) => {
        const current = state.filters[spec.key] || "all";
        const options = ['<option value="all">全部</option>']
          .concat(
            (spec.options || []).map((opt) => {
              const selected = current === opt ? "selected" : "";
              return `<option value="${escapeHtml(opt)}" ${selected}>${escapeHtml(opt)}</option>`;
            })
          )
          .join("");
        return `
          <label class="inline-filter">
            <span>${escapeHtml(spec.label)}</span>
            <select data-filter-key="${escapeHtml(spec.key)}">${options}</select>
          </label>
        `;
      })
      .join("");
  }

  function matchQuery(entity, query) {
    if (!query) return true;
    const haystack = [
      entity.title,
      entity.repo_name,
      entity.tag,
      entity.field,
      entity.program_id,
      entity.goal,
      entity.question,
      entity.short_summary,
      entity.summary_preview,
      entity.description,
      entity.selected_idea_title,
      ...(entity.authors || []),
      ...(entity.tags || []),
      ...(entity.topics || []),
      ...(entity.frameworks || []),
      ...(entity.aliases || []),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(query);
  }

  function filteredLiterature() {
    const query = norm(state.query);
    return (getSnapshot().literature_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      if (state.filters.literatureTag !== "all" && !(item.tags || []).includes(state.filters.literatureTag)) return false;
      if (state.filters.literatureTopic !== "all" && !(item.topics || []).includes(state.filters.literatureTopic)) return false;
      if (state.filters.literatureYear !== "all" && String(item.year || "") !== String(state.filters.literatureYear)) return false;
      return true;
    });
  }

  function filteredRepos() {
    const query = norm(state.query);
    return (getSnapshot().repo_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      if (state.filters.repoTag !== "all" && !(item.tags || []).includes(state.filters.repoTag)) return false;
      if (state.filters.repoFramework !== "all" && !(item.frameworks || []).includes(state.filters.repoFramework)) return false;
      return true;
    });
  }

  function filteredTags() {
    const query = norm(state.query);
    return (getSnapshot().tag_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      if (state.filters.tagStatus !== "all" && String(item.status || "") !== state.filters.tagStatus) return false;
      return true;
    });
  }

  function filteredLandscapes() {
    const query = norm(state.query);
    return (getSnapshot().landscape_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      if (state.filters.landscapeScope !== "all" && String(item.scope || "") !== state.filters.landscapeScope) return false;
      return true;
    });
  }

  function filteredPrograms() {
    const query = norm(state.query);
    return (getSnapshot().program_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      if (state.filters.programStage !== "all" && String(item.stage || "") !== state.filters.programStage) return false;
      return true;
    });
  }

  function overviewItems() {
    const snapshot = getSnapshot();
    const profile = snapshot.workspace_profile || {};
    const items = [
      {
        overview_id: "overview-workspace",
        title: "工作区总览",
        subtitle: `${snapshot.project_name || "workspace"} · ${fmtTime(snapshot.last_updated || snapshot.generated_at)}`,
        short_summary: `论文 ${snapshotCount("literature_count")} 篇，仓库 ${snapshotCount("repo_count")} 个，Program ${snapshotCount("program_count")} 个。`,
        tags: [],
        kind: "workspace",
      },
      {
        overview_id: "overview-literature",
        title: "查看论文库",
        subtitle: `${snapshotCount("literature_count")} 篇已入库论文`,
        short_summary: "按标题、作者、标签、主题快速检索，并查看摘要、claims 状态和来源链接。",
        tags: ["跳转到论文"],
        kind: "jump",
        jump_tab: "literature",
      },
      {
        overview_id: "overview-repos",
        title: "查看仓库库",
        subtitle: `${snapshotCount("repo_count")} 个可复用仓库`,
        short_summary: "聚合仓库摘要、框架、入口点和源码链接，便于设计阶段快速选型。",
        tags: ["跳转到仓库"],
        kind: "jump",
        jump_tab: "repos",
      },
      {
        overview_id: "overview-programs",
        title: "查看 Program",
        subtitle: `${snapshotCount("program_count")} 个研究 Program`,
        short_summary: "进入 Program 视图可通过阶段时间轴浏览问题定义、文献分析、想法评审到方法设计。",
        tags: ["跳转到 Program"],
        kind: "jump",
        jump_tab: "programs",
      },
      {
        overview_id: "overview-profile",
        title: "领域画像摘要",
        subtitle: profile.profile_name ? `profile: ${profile.profile_name}` : "尚未命名 profile",
        short_summary: `短词 ${profile.short_terms ? profile.short_terms.length : 0} 个，tag 规则 ${profile.tag_rule_count || 0} 条，repo role ${profile.repo_role_count || 0} 条。`,
        tags: normalizeArray(profile.short_terms).slice(0, 5),
        kind: "profile",
      },
    ];
    return items.filter((item) => matchQuery(item, norm(state.query)));
  }

  function normalizeArray(value) {
    return Array.isArray(value) ? value.filter(Boolean).map((entry) => String(entry)) : [];
  }

  function listForCurrentTab() {
    if (state.tab === "literature") return filteredLiterature();
    if (state.tab === "repos") return filteredRepos();
    if (state.tab === "tags") return filteredTags();
    if (state.tab === "landscapes") return filteredLandscapes();
    if (state.tab === "programs") return filteredPrograms();
    return overviewItems();
  }

  function selectedFieldForTab(tab) {
    if (tab === "literature") return "source_id";
    if (tab === "repos") return "repo_id";
    if (tab === "tags") return "tag";
    if (tab === "landscapes") return "survey_id";
    if (tab === "programs") return "program_id";
    return "overview_id";
  }

  function ensureSelection(items) {
    const tab = state.tab;
    const field = selectedFieldForTab(tab);
    const selected = state.selected[tab];
    if (selected && items.some((item) => String(item[field] || "") === String(selected))) {
      return;
    }
    state.selected[tab] = items.length ? String(items[0][field] || "") : "";
  }

  function listCardHtml(item) {
    if (state.tab === "literature") {
      const selected = state.selected.literature === item.source_id ? "selected" : "";
      const subtitle = `${item.year || "未知年份"} · ${fmtList((item.authors || []).slice(0, 3), "作者未知")}`;
      const summary = compactText(item.short_summary || item.note_preview || "暂无摘要", 120);
      return `
        <article class="list-card ${selected}" data-kind="literature" data-id="${escapeHtml(item.source_id)}">
          <h3 class="list-title">${escapeHtml(item.title || item.source_id)}</h3>
          <p class="list-subtitle">${escapeHtml(subtitle)}</p>
          <p class="list-summary">${escapeHtml(summary)}</p>
          <div class="badge-row">
            ${(item.tags || []).slice(0, 4).map((tag) => badge(tag)).join("")}
            ${item.claims_status ? badge(item.claims_status, item.claims_status.includes("placeholder") ? "warn" : "soft") : ""}
          </div>
        </article>
      `;
    }
    if (state.tab === "repos") {
      const selected = state.selected.repos === item.repo_id ? "selected" : "";
      const subtitle = `${item.import_type || "unknown import"} · ${item.owner_name || "unknown owner"}`;
      const summary = compactText(item.short_summary || "暂无仓库摘要", 120);
      return `
        <article class="list-card ${selected}" data-kind="repos" data-id="${escapeHtml(item.repo_id)}">
          <h3 class="list-title">${escapeHtml(item.repo_name || item.repo_id)}</h3>
          <p class="list-subtitle">${escapeHtml(subtitle)}</p>
          <p class="list-summary">${escapeHtml(summary)}</p>
          <div class="badge-row">
            ${(item.tags || []).slice(0, 3).map((tag) => badge(tag)).join("")}
            ${(item.frameworks || []).slice(0, 2).map((tag) => badge(tag, "soft")).join("")}
          </div>
        </article>
      `;
    }
    if (state.tab === "tags") {
      const selected = state.selected.tags === item.tag ? "selected" : "";
      const subtitle = `${item.literature_count || 0} 篇论文 · ${item.repo_count || 0} 个仓库`;
      return `
        <article class="list-card ${selected}" data-kind="tags" data-id="${escapeHtml(item.tag)}">
          <h3 class="list-title">${escapeHtml(item.tag)}</h3>
          <p class="list-subtitle">${escapeHtml(subtitle)}</p>
          <p class="list-summary">${escapeHtml(compactText(item.description || "暂无标签说明", 120))}</p>
          <div class="badge-row">
            ${badge(item.status || "active", item.status === "active" ? "ok" : "warn")}
          </div>
        </article>
      `;
    }
    if (state.tab === "landscapes") {
      const selected = state.selected.landscapes === item.survey_id ? "selected" : "";
      const subtitle = `${item.scope || "scope 未标注"} · 论文 ${item.matched_literature_count || 0} · 仓库 ${item.matched_repo_count || 0}`;
      return `
        <article class="list-card ${selected}" data-kind="landscapes" data-id="${escapeHtml(item.survey_id)}">
          <h3 class="list-title">${escapeHtml(item.field || item.survey_id)}</h3>
          <p class="list-subtitle">${escapeHtml(subtitle)}</p>
          <p class="list-summary">${escapeHtml(compactText(item.summary_preview || "暂无趋势总结", 120))}</p>
          <div class="badge-row">
            ${(item.query_tags || []).slice(0, 4).map((tag) => badge(tag)).join("")}
          </div>
        </article>
      `;
    }
    if (state.tab === "programs") {
      const selected = state.selected.programs === item.program_id ? "selected" : "";
      const subtitle = `${item.stage || "stage 未设置"} · idea ${item.idea_count || 0} 个`;
      return `
        <article class="list-card ${selected}" data-kind="programs" data-id="${escapeHtml(item.program_id)}">
          <h3 class="list-title">${escapeHtml(item.program_id)}</h3>
          <p class="list-subtitle">${escapeHtml(subtitle)}</p>
          <p class="list-summary">${escapeHtml(compactText(item.goal || item.question || "暂无 program 摘要", 120))}</p>
          <div class="badge-row">
            ${item.selected_idea_title ? badge(item.selected_idea_title, "soft") : badge("尚未选中 idea", "warn")}
          </div>
        </article>
      `;
    }
    const selected = state.selected.overview === item.overview_id ? "selected" : "";
    return `
      <article class="list-card ${selected}" data-kind="overview" data-id="${escapeHtml(item.overview_id)}">
        <h3 class="list-title">${escapeHtml(item.title)}</h3>
        <p class="list-subtitle">${escapeHtml(item.subtitle || "")}</p>
        <p class="list-summary">${escapeHtml(item.short_summary || "")}</p>
        <div class="badge-row">
          ${(item.tags || []).slice(0, 4).map((tag) => badge(tag, "soft")).join("")}
        </div>
      </article>
    `;
  }

  function renderList() {
    const items = listForCurrentTab();
    ensureSelection(items);
    const tabLabel = TAB_CONFIG.find((item) => item.id === state.tab)?.label || "总览";
    elements.listTitle.textContent = tabLabel;
    elements.listMeta.textContent = `${items.length} 条`;
    if (!items.length) {
      elements.listContainer.innerHTML = '<div class="empty-state">当前搜索和筛选条件下没有结果。</div>';
      return items;
    }
    elements.listContainer.innerHTML = items.map((item) => listCardHtml(item)).join("");
    return items;
  }

  function selectedItem(items) {
    const field = selectedFieldForTab(state.tab);
    const selectedId = state.selected[state.tab];
    return items.find((item) => String(item[field] || "") === String(selectedId)) || null;
  }

  function renderKeyValues(rows) {
    const html = rows
      .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${value}</dd>`)
      .join("");
    return `<dl class="kv-grid">${html}</dl>`;
  }

  function section(title, body) {
    return `<section class="detail-section"><h3>${escapeHtml(title)}</h3>${body}</section>`;
  }

  function detailLinks(links) {
    const valid = (links || []).filter(Boolean);
    if (!valid.length) return '<p class="detail-copy">暂无可打开文件。</p>';
    return `<div class="detail-links">${valid.join("")}</div>`;
  }

  function renderOverviewDetail(item) {
    elements.detailTitle.textContent = item.title || "总览";
    elements.detailMeta.textContent = item.subtitle || "工作区摘要";
    const snapshot = getSnapshot();
    const profile = snapshot.workspace_profile || {};
    const baseSections = [
      section(
        "摘要",
        `<p class="detail-copy">${escapeHtml(item.short_summary || "暂无摘要。")}</p>`
      ),
      section(
        "工作区统计",
        renderKeyValues([
          ["论文数", escapeHtml(String(snapshotCount("literature_count")))],
          ["仓库数", escapeHtml(String(snapshotCount("repo_count")))],
          ["标签数", escapeHtml(String(snapshotCount("tag_count")))],
          ["趋势图谱数", escapeHtml(String(snapshotCount("landscape_count")))],
          ["Program 数", escapeHtml(String(snapshotCount("program_count")))],
          ["最近更新", escapeHtml(fmtTime(snapshot.last_updated || snapshot.generated_at))],
        ])
      ),
      section(
        "领域画像",
        renderKeyValues([
          ["Profile 名称", escapeHtml(profile.profile_name || "未命名")],
          ["短词集合", escapeHtml(fmtList(profile.short_terms || []))],
          ["Tag 规则", escapeHtml(String(profile.tag_rule_count || 0))],
          ["Taxonomy Seed", escapeHtml(String(profile.taxonomy_seed_count || 0))],
          ["Repo Role", escapeHtml(String(profile.repo_role_count || 0))],
        ])
      ),
      section(
        "快捷入口",
        detailLinks([
          linkChip(profile.domain_profile_href, "查看 domain-profile.yaml"),
        ])
      ),
    ];
    elements.detailBody.innerHTML = baseSections.join("");
  }

  function renderLiteratureDetail(item) {
    elements.detailTitle.textContent = item.title || item.source_id;
    elements.detailMeta.textContent = `${item.year || "未知年份"} · ${item.source_kind || "source kind 未标注"}`;
    const claimWarn = item.claims_status && item.claims_status.includes("placeholder")
      ? '<p class="detail-copy">当前 claims 处于占位状态（placeholder），仅用于提醒后续补充，不应直接当作最终结论。</p>'
      : "";
    elements.detailBody.innerHTML = [
      section(
        "摘要",
        `
          <p class="detail-copy">${escapeHtml(item.short_summary || item.note_preview || "暂无摘要。")}</p>
          ${claimWarn}
          <div class="chip-row">
            ${(item.tags || []).map((tag) => badge(tag)).join("")}
            ${(item.topics || []).map((topic) => badge(topic, "soft")).join("")}
          </div>
        `
      ),
      section(
        "论文信息",
        renderKeyValues([
          ["年份", escapeHtml(String(item.year || "未知"))],
          ["作者", escapeHtml(fmtList(item.authors || [], "未知作者"))],
          [
            "Canonical URL",
            item.canonical_url
              ? `<a href="${escapeHtml(item.canonical_url)}" target="_blank" rel="noreferrer">${escapeHtml(item.canonical_url)}</a>`
              : "暂无",
          ],
          ["来源指纹", escapeHtml(item.site_fingerprint || "未知")],
          ["Claims 状态", escapeHtml(item.claims_status || "未标注")],
          ["Claims 使用说明", escapeHtml(item.claims_usage_guidance || "暂无")],
        ])
      ),
      section(
        "文件入口",
        detailLinks([
          linkChip(item.links.metadata, "元数据 metadata.yaml"),
          linkChip(item.links.note, "阅读笔记 note.md"),
          linkChip(item.links.claims, "claims.yaml"),
          linkChip(item.links.primary_pdf, "原始 PDF"),
          linkChip(item.links.landing_html, "页面快照"),
        ])
      ),
    ].join("");
  }

  function renderRepoDetail(item) {
    elements.detailTitle.textContent = item.repo_name || item.repo_id;
    elements.detailMeta.textContent = `${item.import_type || "unknown import"} · ${item.owner_name || "owner unknown"}`;
    const entrypoints = (item.entrypoints || []).length
      ? (item.entrypoints || []).slice(0, 12).map((entry) => `<li>${escapeHtml(entry)}</li>`).join("")
      : "<li>尚未提取入口点。</li>";
    elements.detailBody.innerHTML = [
      section(
        "摘要",
        `
          <p class="detail-copy">${escapeHtml(item.short_summary || "暂无仓库摘要。")}</p>
          <div class="chip-row">
            ${(item.tags || []).map((tag) => badge(tag)).join("")}
            ${(item.frameworks || []).map((fw) => badge(fw, "soft")).join("")}
          </div>
        `
      ),
      section(
        "仓库信息",
        renderKeyValues([
          ["仓库 ID", escapeHtml(item.repo_id || "")],
          ["导入方式", escapeHtml(item.import_type || "未知")],
          ["Owner", escapeHtml(item.owner_name || "未知")],
          [
            "远端地址",
            item.canonical_remote
              ? `<a href="${escapeHtml(item.canonical_remote)}" target="_blank" rel="noreferrer">${escapeHtml(item.canonical_remote)}</a>`
              : "暂无",
          ],
        ])
      ),
      section("主要入口点", `<ul class="detail-list">${entrypoints}</ul>`),
      section(
        "文件入口",
        detailLinks([
          linkChip(item.links.summary, "summary.yaml"),
          linkChip(item.links.notes, "repo-notes.md"),
          linkChip(item.links.source, "source 目录"),
        ])
      ),
    ].join("");
  }

  function renderTagDetail(item) {
    elements.detailTitle.textContent = item.tag;
    elements.detailMeta.textContent = `${item.literature_count || 0} 篇论文 · ${item.repo_count || 0} 个仓库`;
    const sampleLit = (item.sample_literature || []).length
      ? (item.sample_literature || []).map((lit) => `<li>${escapeHtml(lit.title || lit.source_id)}</li>`).join("")
      : "<li>暂无论文样本。</li>";
    const sampleRepos = (item.sample_repos || []).length
      ? (item.sample_repos || []).map((repo) => `<li>${escapeHtml(repo.repo_name || repo.repo_id)}</li>`).join("")
      : "<li>暂无仓库样本。</li>";
    elements.detailBody.innerHTML = [
      section(
        "标签定义",
        renderKeyValues([
          ["Canonical Tag", escapeHtml(item.canonical_tag || item.tag)],
          ["状态", escapeHtml(item.status || "active")],
          ["别名", escapeHtml(fmtList(item.aliases || [], "无"))],
          ["说明", escapeHtml(item.description || "暂无说明")],
          ["Topic Hint", escapeHtml(fmtList(item.topic_hints || [], "无"))],
        ])
      ),
      section("关联论文样本", `<ul class="detail-list">${sampleLit}</ul>`),
      section("关联仓库样本", `<ul class="detail-list">${sampleRepos}</ul>`),
      section("文件入口", detailLinks([linkChip(item.links.taxonomy, "tag-taxonomy.yaml")])),
    ].join("");
  }

  function renderLandscapeDetail(item) {
    elements.detailTitle.textContent = item.field || item.survey_id;
    elements.detailMeta.textContent = `${item.scope || "scope 未标注"} · 命中文献 ${item.matched_literature_count || 0} · 命中仓库 ${item.matched_repo_count || 0}`;
    const candidatePrograms = (item.candidate_programs || []).length
      ? (item.candidate_programs || [])
          .map(
            (program) => `
              <li>
                <strong>${escapeHtml(program.title || program.suggested_program_id || "未命名候选题")}</strong><br />
                ${escapeHtml(compactText(program.why_now || program.goal || program.question || "暂无说明", 220))}
              </li>
            `
          )
          .join("")
      : "<li>暂无候选 program。</li>";
    elements.detailBody.innerHTML = [
      section(
        "趋势摘要",
        `
          <p class="detail-copy">${escapeHtml(item.summary_preview || "暂无摘要。")}</p>
          <div class="chip-row">${(item.query_tags || []).map((tag) => badge(tag)).join("")}</div>
        `
      ),
      section("候选 Program", `<ul class="detail-list">${candidatePrograms}</ul>`),
      section(
        "文件入口",
        detailLinks([
          linkChip(item.links.report, "landscape-report.yaml"),
          linkChip(item.links.summary, "summary.md"),
        ])
      ),
    ].join("");
  }

  function stageStatus(stageId, currentStageId) {
    const currentIndex = Number.isInteger(stageIndexMap[currentStageId]) ? stageIndexMap[currentStageId] : -1;
    const index = Number.isInteger(stageIndexMap[stageId]) ? stageIndexMap[stageId] : -1;
    if (currentIndex < 0 || index < 0) return "pending";
    if (index < currentIndex) return "done";
    if (index === currentIndex) return "active";
    return "pending";
  }

  function programTimelineHtml(program) {
    const current = program.stage || "";
    const defaultStage = Number.isInteger(stageIndexMap[current]) ? current : PROGRAM_STAGES[0].id;
    const selectedStage = state.programStageView[program.program_id] || defaultStage;
    state.programStageView[program.program_id] = selectedStage;
    return `
      <div class="program-timeline">
        ${PROGRAM_STAGES.map((stage) => {
          const status = stageStatus(stage.id, current);
          const activeClass = stage.id === selectedStage ? "active" : "";
          return `
            <button class="stage-chip ${status} ${activeClass}" data-program-id="${escapeHtml(program.program_id)}" data-stage-id="${escapeHtml(stage.id)}">
              ${escapeHtml(stage.label)}
            </button>
          `;
        }).join("")}
      </div>
    `;
  }

  function stageSectionProgram(program, selectedStage) {
    const links = program.links || {};
    if (selectedStage === "problem-framing") {
      return section(
        "阶段内容：问题定义",
        `
          <p class="detail-copy">${escapeHtml(program.question || program.goal || "暂无问题定义内容。")}</p>
          ${renderKeyValues([
            ["研究问题", escapeHtml(program.question || "暂无")],
            ["研究目标", escapeHtml(program.goal || "暂无")],
            ["当前 stage", escapeHtml(program.stage || "未设置")],
          ])}
          ${detailLinks([linkChip(links.charter, "charter.yaml"), linkChip(links.state, "workflow/state.yaml"), linkChip(links.preferences, "workflow/preferences.yaml")])}
        `
      );
    }
    if (selectedStage === "literature-analysis") {
      const topSources = (program.top_sources || []).length
        ? (program.top_sources || [])
            .map(
              (source) => `
                <li>
                  <strong>${escapeHtml(source.title || source.source_id)}</strong><br />
                  ${escapeHtml(compactText(source.short_summary || "", 180))}
                </li>
              `
            )
            .join("")
        : "<li>暂无 literature map 选中来源。</li>";
      return section(
        "阶段内容：文献分析",
        `
          <ul class="detail-list">${topSources}</ul>
          ${detailLinks([linkChip(links.literature_map, "evidence/literature-map.yaml"), linkChip(links.evidence_requests, "workflow/evidence-requests.yaml")])}
        `
      );
    }
    if (selectedStage === "idea-generation") {
      const ideas = (program.ideas || []).length
        ? (program.ideas || [])
            .map(
              (idea) => `
                <li>
                  <strong>${escapeHtml(idea.title || idea.idea_id)}</strong><br />
                  ${escapeHtml(idea.status || "未标注")} · ${escapeHtml(compactText(idea.hypothesis || "", 120))}
                </li>
              `
            )
            .join("")
        : "<li>暂无 idea 条目。</li>";
      return section(
        "阶段内容：想法生成",
        `
          <p class="detail-copy">当前共 ${escapeHtml(String(program.idea_count || 0))} 个候选 idea。</p>
          <ul class="detail-list">${ideas}</ul>
          ${detailLinks([linkChip(links.ideas_index, "ideas/index.yaml")])}
        `
      );
    }
    if (selectedStage === "idea-review") {
      const selectedIdea = (program.ideas || []).find((idea) => idea.idea_id === program.selected_idea_id) || null;
      const shortlisted = (program.ideas || []).filter((idea) => String(idea.status || "").includes("shortlist")).length;
      return section(
        "阶段内容：方案评审",
        `
          ${renderKeyValues([
            ["选中 idea", escapeHtml(selectedIdea ? selectedIdea.title || selectedIdea.idea_id : "暂无")],
            ["候选数量", escapeHtml(String(program.idea_count || 0))],
            ["shortlisted 数量", escapeHtml(String(shortlisted))],
          ])}
          <div class="chip-row">
            ${(program.ideas || []).map((idea) => badge(`${idea.title || idea.idea_id}: ${idea.status || "unknown"}`, idea.status === "selected" ? "ok" : "soft")).join("")}
          </div>
          ${detailLinks([linkChip(links.ideas_index, "ideas/index.yaml"), linkChip(links.decision_log, "workflow/decision-log.md"), linkChip(links.open_questions, "workflow/open-questions.yaml")])}
        `
      );
    }
    if (selectedStage === "method-design") {
      return section(
        "阶段内容：方法设计",
        `
          ${renderKeyValues([
            ["选中 idea", escapeHtml(program.selected_idea_title || program.selected_idea_id || "暂无")],
            ["选中仓库", escapeHtml(program.selected_repo_id || "暂无")],
            ["仓库摘要", escapeHtml(program.selected_repo_summary || "暂无")],
          ])}
          <p class="detail-copy">${escapeHtml(program.design_preview || "暂无 system design 摘要。")}</p>
          ${detailLinks([
            linkChip(links.repo_choice, "design/repo-choice.yaml"),
            linkChip(links.selected_idea, "design/selected-idea.yaml"),
            linkChip(links.design_doc, "design/system-design.md"),
            linkChip(links.interfaces, "design/interfaces.yaml"),
          ])}
        `
      );
    }
    return section(
      "阶段内容：实现规划",
      `
        <p class="detail-copy">${escapeHtml(program.runbook_preview || "暂无 runbook 摘要。")}</p>
        ${renderKeyValues([
          ["Open Questions", escapeHtml(String(program.open_question_count || 0))],
          ["Evidence Requests", escapeHtml(String(program.evidence_request_count || 0))],
          ["实验条目", escapeHtml(String(program.experiment_count || 0))],
        ])}
        ${detailLinks([
          linkChip(links.runbook, "experiments/runbook.md"),
          linkChip(links.matrix, "experiments/matrix.yaml"),
          linkChip(links.decision_log, "workflow/decision-log.md"),
          linkChip(links.open_questions, "workflow/open-questions.yaml"),
        ])}
      `
    );
  }

  function renderProgramDetail(item) {
    elements.detailTitle.textContent = item.program_id;
    elements.detailMeta.textContent = `${item.stage || "stage 未设置"} · 更新于 ${fmtTime(item.generated_at)}`;
    const current = item.stage || "";
    const selectedStage = state.programStageView[item.program_id] || (Number.isInteger(stageIndexMap[current]) ? current : PROGRAM_STAGES[0].id);
    state.programStageView[item.program_id] = selectedStage;
    const stageBadges = PROGRAM_STAGES.map((stage) => {
      const status = stageStatus(stage.id, current);
      const badgeType = status === "done" ? "ok" : status === "active" ? "warn" : "soft";
      return badge(`${stage.label}：${status === "done" ? "完成" : status === "active" ? "进行中" : "待进行"}`, badgeType);
    }).join("");
    elements.detailBody.innerHTML = [
      section(
        "Program 摘要",
        `
          <p class="detail-copy">${escapeHtml(item.goal || item.question || "暂无 program 摘要。")}</p>
          ${renderKeyValues([
            ["研究问题", escapeHtml(item.question || "暂无")],
            ["研究目标", escapeHtml(item.goal || "暂无")],
            ["当前 stage", escapeHtml(item.stage || "未设置")],
            ["选中 idea", escapeHtml(item.selected_idea_title || item.selected_idea_id || "暂无")],
            ["选中仓库", escapeHtml(item.selected_repo_id || "暂无")],
          ])}
          <div class="chip-row">${stageBadges}</div>
        `
      ),
      section("阶段时间轴", programTimelineHtml(item)),
      stageSectionProgram(item, selectedStage),
      section(
        "全局文件入口",
        detailLinks([
          linkChip(item.links.charter, "charter.yaml"),
          linkChip(item.links.state, "workflow/state.yaml"),
          linkChip(item.links.literature_map, "evidence/literature-map.yaml"),
          linkChip(item.links.ideas_index, "ideas/index.yaml"),
          linkChip(item.links.repo_choice, "design/repo-choice.yaml"),
          linkChip(item.links.design_doc, "design/system-design.md"),
          linkChip(item.links.interfaces, "design/interfaces.yaml"),
          linkChip(item.links.runbook, "experiments/runbook.md"),
          linkChip(item.links.matrix, "experiments/matrix.yaml"),
        ])
      ),
    ].join("");
  }

  function renderDetail(items) {
    const selected = selectedItem(items);
    if (!selected) {
      elements.detailTitle.textContent = "请先选择条目";
      elements.detailMeta.textContent = "右侧将显示结构化详情";
      elements.detailBody.innerHTML = '<div class="empty-state">左侧列表暂无可展示条目，或需要先调整搜索条件。</div>';
      return;
    }

    if (state.tab === "literature") {
      renderLiteratureDetail(selected);
      return;
    }
    if (state.tab === "repos") {
      renderRepoDetail(selected);
      return;
    }
    if (state.tab === "tags") {
      renderTagDetail(selected);
      return;
    }
    if (state.tab === "landscapes") {
      renderLandscapeDetail(selected);
      return;
    }
    if (state.tab === "programs") {
      renderProgramDetail(selected);
      return;
    }
    renderOverviewDetail(selected);
  }

  function renderAll() {
    renderTabNav();
    renderFilterBar();
    const items = renderList();
    renderDetail(items);
  }

  function updateStatusPill() {
    const raw = state.live.buildStatus || "loading";
    const textMap = {
      loading: "加载中",
      ready: "已同步",
      stale: "快照过期",
      failed: "连接失败",
      missing: "尚无快照",
    };
    elements.liveStatus.textContent = textMap[raw] || raw;
    elements.liveStatus.className = `status-pill ${raw}`;
    if (state.live.lastError) {
      elements.updatedAt.textContent = `最近错误：${state.live.lastError}`;
      return;
    }
    elements.updatedAt.textContent = `更新于 ${fmtTime(state.live.generatedAt)}`;
  }

  function applySnapshot(snapshot, live) {
    state.snapshot = snapshot;
    state.version = String((live && live.snapshot_version) || snapshot.snapshot_version || "");
    state.live.buildStatus = String((live && live.build_status) || "ready");
    state.live.generatedAt = String((live && live.generated_at) || snapshot.generated_at || "");
    state.live.lastError = String((live && live.last_error) || "");
    updateStatusPill();
    renderAll();
  }

  async function fetchSnapshot(version) {
    const response = await fetch(`${snapshotUrl}?v=${encodeURIComponent(version || Date.now())}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`snapshot fetch failed: ${response.status}`);
    return response.json();
  }

  async function fetchVersion() {
    const response = await fetch(`${versionUrl}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`version fetch failed: ${response.status}`);
    return response.json();
  }

  async function refresh(force) {
    try {
      const live = await fetchVersion();
      const nextVersion = String(live.snapshot_version || "");
      if (force || !state.snapshot || (nextVersion && nextVersion !== state.version)) {
        const snapshot = await fetchSnapshot(nextVersion || Date.now());
        applySnapshot(snapshot, live);
      } else {
        state.live.buildStatus = String(live.build_status || state.live.buildStatus);
        state.live.generatedAt = String(live.generated_at || state.live.generatedAt);
        state.live.lastError = String(live.last_error || "");
        updateStatusPill();
      }
    } catch (error) {
      state.live.buildStatus = "failed";
      state.live.lastError = error instanceof Error ? error.message : String(error);
      updateStatusPill();
    }
  }

  function onClick(event) {
    const tabButton = event.target.closest("[data-tab]");
    if (tabButton) {
      const nextTab = tabButton.getAttribute("data-tab") || "overview";
      if (state.tab !== nextTab) {
        state.tab = nextTab;
        renderAll();
      }
      return;
    }

    const listCard = event.target.closest("[data-kind][data-id]");
    if (listCard) {
      const kind = listCard.getAttribute("data-kind");
      const id = listCard.getAttribute("data-id");
      if (kind && id && state.selected[kind] !== undefined) {
        state.selected[kind] = id;
        if (kind === "overview") {
          const item = (overviewItems() || []).find((entry) => entry.overview_id === id);
          if (item && item.kind === "jump" && item.jump_tab) {
            state.tab = item.jump_tab;
          }
        }
        renderAll();
      }
      return;
    }

    const stageButton = event.target.closest("[data-program-id][data-stage-id]");
    if (stageButton) {
      const programId = stageButton.getAttribute("data-program-id");
      const stageId = stageButton.getAttribute("data-stage-id");
      if (programId && stageId) {
        state.programStageView[programId] = stageId;
        const items = listForCurrentTab();
        renderDetail(items);
      }
    }
  }

  function onInput(event) {
    if (event.target === elements.search) {
      state.query = elements.search.value || "";
      renderAll();
    }
  }

  function onChange(event) {
    const key = event.target.getAttribute("data-filter-key");
    if (key && state.filters[key] !== undefined) {
      state.filters[key] = event.target.value || "all";
      renderAll();
    }
  }

  document.addEventListener("click", onClick);
  document.addEventListener("change", onChange);
  elements.search.addEventListener("input", onInput);

  refresh(true);
  setInterval(() => refresh(false), pollMs);
})();
