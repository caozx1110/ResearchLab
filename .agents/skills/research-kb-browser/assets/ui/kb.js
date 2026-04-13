(function () {
  const config = window.RESEARCH_KB_BROWSER || {};
  const snapshotUrl = config.snapshotUrl || "./snapshot.json";
  const versionUrl = config.versionUrl || "/api/version";
  const fileApiUrl = config.fileApiUrl || "/api/file";
  const terminalOpenUrl = config.terminalOpenUrl || "/api/terminal/open";
  const terminalPollUrl = config.terminalPollUrl || "/api/terminal/poll";
  const terminalInputUrl = config.terminalInputUrl || "/api/terminal/input";
  const terminalResizeUrl = config.terminalResizeUrl || "/api/terminal/resize";
  const systemTerminalOpenUrl = config.systemTerminalOpenUrl || "/api/system-terminal/open";
  const systemTerminalTargetsUrl = config.systemTerminalTargetsUrl || "/api/system-terminal/targets";
  const pollMs = Number(config.pollMs || 3000);

  const TAB_CONFIG = [
    { id: "overview", label: "总览", shortLabel: "总", countKey: "", unit: "视图" },
    { id: "literature", label: "论文", shortLabel: "文", countKey: "literature_count", unit: "篇" },
    { id: "repos", label: "仓库", shortLabel: "库", countKey: "repo_count", unit: "个" },
    { id: "tags", label: "标签", shortLabel: "标", countKey: "tag_count", unit: "个" },
    { id: "landscapes", label: "趋势", shortLabel: "势", countKey: "landscape_count", unit: "个" },
    { id: "programs", label: "Program", shortLabel: "程", countKey: "program_count", unit: "个" },
    { id: "wiki", label: "Wiki", shortLabel: "维", countKey: "wiki_item_count", unit: "项" },
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
    launch: {
      path: "",
      settings: false,
      consumed: false,
    },
    tab: "overview",
    query: "",
    selected: {
      overview: "",
      literature: "",
      repos: "",
      tags: "",
      landscapes: "",
      programs: "",
      wiki: "",
    },
    expanded: {
      overview: "",
      literature: "",
      repos: "",
      tags: "",
      landscapes: "",
      programs: "",
      wiki: "",
    },
    filters: {
      searchTarget: "all",
      literatureTag: "all",
      literatureTopic: "all",
      literatureYear: "all",
      literatureAuthor: "all",
      literatureSourceKind: "all",
      literatureClaims: "all",
      repoTag: "all",
      repoTopic: "all",
      repoFramework: "all",
      repoOwner: "all",
      repoImportType: "all",
      tagStatus: "all",
      landscapeScope: "all",
      landscapeTag: "all",
      programStage: "all",
      programRepo: "all",
      wikiKind: "all",
    },
    programStageView: {},
    live: {
      buildStatus: "loading",
      generatedAt: "",
      lastError: "",
    },
    settingsView: "appearance",
    layout: {
      sidebarCollapsed: false,
      detailCollapsed: false,
      searchMode: false,
      searchExpanded: false,
      theme: "dark",
    },
    preferences: {
      uiScale: "100",
      readerFontSize: "92",
      readerLineHeight: "166",
      editorFontSize: "84",
      terminalFontSize: "12",
      listDensity: "comfortable",
      previewWidth: "wide",
      formulaRendering: true,
      defaultTerminalMode: "shell",
      defaultWorkbenchMode: "preview",
      autoOpenWorkbench: true,
    },
    workbench: {
      path: "",
      href: "",
      kind: "",
      content: "",
      savedContent: "",
      updatedAt: "",
      writable: false,
      dirty: false,
      loading: false,
      mode: "preview",
      autoSave: true,
      lastSaveError: "",
      history: [],
      historyIndex: -1,
    },
    terminal: {
      sessionId: "",
      mode: "shell",
      status: "starting",
      cursor: 0,
      buffer: "",
      collapsed: false,
      polling: false,
      lastError: "",
      needsFit: false,
    },
    systemTerminal: {
      targets: [],
    },
  };

  const elements = {
    search: document.getElementById("globalSearch"),
    sidebarSearch: document.getElementById("sidebarSearch"),
    searchSectionBody: document.getElementById("searchSectionBody"),
    searchSectionMeta: document.getElementById("searchSectionMeta"),
    searchSectionToggleBtn: document.getElementById("searchSectionToggleBtn"),
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
    appShell: document.getElementById("appShell"),
    primarySidebar: document.getElementById("primarySidebar"),
    sidebarToggleBtn: document.getElementById("sidebarToggleBtn"),
    themeToggleMark: document.getElementById("themeToggleMark"),
    sidebarCollapseBtn: document.getElementById("sidebarCollapseBtn"),
    activitySearchBtn: document.getElementById("activitySearchBtn"),
    quickOpenBar: document.getElementById("quickOpenBar"),
    refreshNowBtn: document.getElementById("refreshNowBtn"),
    listResizer: document.getElementById("listResizer"),
    detailResizer: document.getElementById("detailResizer"),
    detailPanel: document.getElementById("detailPanel"),
    detailToggleBtn: document.getElementById("detailToggleBtn"),
    detailCollapseBtn: document.getElementById("detailCollapseBtn"),
    detailCollapsedHandle: document.getElementById("detailCollapsedHandle"),
    terminalToggleBtn: document.getElementById("terminalToggleBtn"),
    settingsBtn: document.getElementById("settingsBtn"),
    terminalResizer: document.getElementById("terminalResizer"),
    workbenchTitle: document.getElementById("workbenchTitle"),
    workbenchMeta: document.getElementById("workbenchMeta"),
    workbenchStatus: document.getElementById("workbenchStatus"),
    workbenchBackBtn: document.getElementById("workbenchBackBtn"),
    workbenchForwardBtn: document.getElementById("workbenchForwardBtn"),
    workbenchPath: document.getElementById("workbenchPath"),
    workbenchBody: document.getElementById("workbenchBody"),
    workbenchModeSplit: document.getElementById("workbenchModeSplit"),
    workbenchModeEdit: document.getElementById("workbenchModeEdit"),
    workbenchModePreview: document.getElementById("workbenchModePreview"),
    workbenchOpenExternalBtn: document.getElementById("workbenchOpenExternalBtn"),
    terminalPanel: document.getElementById("terminalPanel"),
    terminalTitle: document.getElementById("terminalTitle"),
    terminalMeta: document.getElementById("terminalMeta"),
    terminalFoot: document.getElementById("terminalFoot"),
    terminalViewport: document.getElementById("terminalViewport"),
    terminalScreen: document.getElementById("terminalScreen"),
    terminalStatus: document.getElementById("terminalStatus"),
    terminalHint: document.getElementById("terminalHint"),
    terminalEntry: document.getElementById("terminalEntry"),
    terminalInputSink: document.getElementById("terminalInputSink"),
    terminalLineInput: document.getElementById("terminalLineInput"),
    terminalSendBtn: document.getElementById("terminalSendBtn"),
    terminalCtrlCBtn: document.getElementById("terminalCtrlCBtn"),
    terminalCodexBtn: document.getElementById("terminalCodexBtn"),
    terminalShellBtn: document.getElementById("terminalShellBtn"),
    terminalCollapseBtn: document.getElementById("terminalCollapseBtn"),
    terminalCollapsedHandle: document.getElementById("terminalCollapsedHandle"),
  };

  const terminalRuntime = {
    xterm: null,
    fitAddon: null,
    ready: false,
  };

  const tooltipRuntime = {
    anchor: null,
    bubble: null,
  };

  const storage = {
    sidebarWidth: "research-kb-sidebar-width",
    detailWidth: "research-kb-detail-width",
    terminalHeight: "research-kb-terminal-height",
    sidebarCollapsed: "research-kb-sidebar-collapsed",
    detailCollapsed: "research-kb-detail-collapsed",
    terminalCollapsed: "research-kb-terminal-collapsed",
    theme: "research-kb-theme",
    uiScale: "research-kb-ui-scale",
    readerFontSize: "research-kb-reader-font-size",
    readerLineHeight: "research-kb-reader-line-height",
    editorFontSize: "research-kb-editor-font-size",
    terminalFontSize: "research-kb-terminal-font-size",
    listDensity: "research-kb-list-density",
    previewWidth: "research-kb-preview-width",
    formulaRendering: "research-kb-formula-rendering",
    defaultTerminalMode: "research-kb-default-terminal-mode",
    defaultWorkbenchMode: "research-kb-default-workbench-mode",
    autoOpenWorkbench: "research-kb-auto-open-workbench",
  };

  function norm(value) {
    return String(value || "").trim().toLowerCase();
  }

  function compactText(text, limit = 180) {
    const normalized = String(text || "").replace(/\s+/g, " ").trim();
    if (normalized.length <= limit) return normalized;
    return `${normalized.slice(0, Math.max(0, limit - 3)).trim()}...`;
  }

  function activeQuery() {
    return norm(state.query);
  }

  function tabIcon(id) {
    const icons = {
      overview: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11.5L12 4L20 11.5"></path><path d="M6.5 10.5V20H17.5V10.5"></path></svg>',
      literature: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5H17L19 6.5V19.5H7Z"></path><path d="M15 4.5V7H19"></path><path d="M10 11H16"></path><path d="M10 14H16"></path></svg>',
      repos: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.5H9L11 9.5H20.5V18.5H3.5Z"></path><path d="M3.5 7.5V5.5H9"></path></svg>',
      tags: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4H19.5V11.5L11 20L4 13Z"></path><circle cx="16" cy="8" r="1.2"></circle></svg>',
      landscapes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17L9 12L12 15L19 8"></path><path d="M19 8V14"></path><path d="M19 8H13"></path></svg>',
      programs: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="4" rx="1"></rect><rect x="4" y="10" width="16" height="4" rx="1"></rect><rect x="4" y="15" width="10" height="4" rx="1"></rect></svg>',
      wiki: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5.5A3.5 3.5 0 0 1 9.5 9V18.5A3.5 3.5 0 0 0 6 15H4.5V6.5H6Z"></path><path d="M18 5.5A3.5 3.5 0 0 0 14.5 9V18.5A3.5 3.5 0 0 1 18 15H19.5V6.5H18Z"></path></svg>',
    };
    return icons[id] || '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7"></circle></svg>';
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function isTextPath(path) {
    const lower = String(path || "").toLowerCase();
    return [".md", ".markdown", ".yaml", ".yml", ".txt", ".log", ".json", ".py", ".sh", ".toml"].some((suffix) => lower.endsWith(suffix));
  }

  function isMarkdownPath(path) {
    const lower = String(path || "").toLowerCase();
    return lower.endsWith(".md") || lower.endsWith(".markdown");
  }

  function normalizeInternalPath(path) {
    return String(path || "").replace(/^\/+/, "");
  }

  function hrefToPath(href) {
    const value = String(href || "");
    if (!value) return "";
    if (/^[a-z]+:\/\//i.test(value)) return "";
    return normalizeInternalPath(decodeURIComponent(value));
  }

  function basename(path) {
    const raw = String(path || "");
    if (!raw) return "";
    return raw.split("/").filter(Boolean).slice(-1)[0] || raw;
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function ensureTooltipBubble() {
    if (tooltipRuntime.bubble) return tooltipRuntime.bubble;
    const bubble = document.createElement("div");
    bubble.className = "kb-tooltip";
    bubble.id = "kbTooltip";
    bubble.setAttribute("role", "tooltip");
    document.body.appendChild(bubble);
    tooltipRuntime.bubble = bubble;
    return bubble;
  }

  function tooltipSideForElement(element) {
    const preferred = String(element.getAttribute("data-tip-side") || "").trim();
    if (preferred) return preferred;
    const rect = element.getBoundingClientRect();
    const spaces = {
      top: rect.top,
      bottom: window.innerHeight - rect.bottom,
      left: rect.left,
      right: window.innerWidth - rect.right,
    };
    if (spaces.left < 96 && spaces.right > 160) return "right";
    if (spaces.top < 72 && spaces.bottom > 72) return "bottom";
    if (spaces.right < 120 && spaces.left > 140) return "left";
    return "top";
  }

  function positionTooltip() {
    const anchor = tooltipRuntime.anchor;
    const bubble = ensureTooltipBubble();
    if (!anchor || !bubble) return;
    const text = String(anchor.getAttribute("data-tip") || "").trim();
    if (!text) {
      bubble.classList.remove("visible");
      return;
    }
    bubble.textContent = text;
    bubble.classList.add("visible");
    const side = tooltipSideForElement(anchor);
    const rect = anchor.getBoundingClientRect();
    const bubbleRect = bubble.getBoundingClientRect();
    const gap = 12;
    const margin = 10;
    let left = rect.left + rect.width / 2 - bubbleRect.width / 2;
    let top = rect.top - bubbleRect.height - gap;

    if (side === "right") {
      left = rect.right + gap;
      top = rect.top + rect.height / 2 - bubbleRect.height / 2;
    } else if (side === "left") {
      left = rect.left - bubbleRect.width - gap;
      top = rect.top + rect.height / 2 - bubbleRect.height / 2;
    } else if (side === "bottom") {
      left = rect.left + rect.width / 2 - bubbleRect.width / 2;
      top = rect.bottom + gap;
    }

    left = clamp(left, margin, window.innerWidth - bubbleRect.width - margin);
    top = clamp(top, margin, window.innerHeight - bubbleRect.height - margin);
    bubble.style.left = `${Math.round(left)}px`;
    bubble.style.top = `${Math.round(top)}px`;
  }

  function showTooltip(element) {
    if (!element || !String(element.getAttribute("data-tip") || "").trim()) return;
    tooltipRuntime.anchor = element;
    positionTooltip();
  }

  function hideTooltip() {
    tooltipRuntime.anchor = null;
    if (tooltipRuntime.bubble) {
      tooltipRuntime.bubble.classList.remove("visible");
    }
  }

  function loadSidebarWidth() {
    try {
      const raw = window.localStorage.getItem(storage.sidebarWidth);
      const width = Number(raw || 0);
      if (Number.isFinite(width) && width >= 220 && width <= 520) {
        document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
      }
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function saveSidebarWidth(width) {
    try {
      window.localStorage.setItem(storage.sidebarWidth, String(Math.round(width)));
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function loadDetailWidth() {
    try {
      const raw = window.localStorage.getItem(storage.detailWidth);
      const width = Number(raw || 0);
      if (Number.isFinite(width) && width >= 260 && width <= 520) {
        document.documentElement.style.setProperty("--detail-width", `${width}px`);
      }
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function saveDetailWidth(width) {
    try {
      window.localStorage.setItem(storage.detailWidth, String(Math.round(width)));
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function loadTerminalHeight() {
    try {
      const raw = window.localStorage.getItem(storage.terminalHeight);
      const height = Number(raw || 0);
      if (Number.isFinite(height) && height >= 220 && height <= 640) {
        document.documentElement.style.setProperty("--panel-height", `${height}px`);
      }
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function saveTerminalHeight(height) {
    try {
      window.localStorage.setItem(storage.terminalHeight, String(Math.round(height)));
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function loadBooleanPreference(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return fallback;
      return raw === "1";
    } catch (_error) {
      return fallback;
    }
  }

  function saveBooleanPreference(key, value) {
    try {
      window.localStorage.setItem(key, value ? "1" : "0");
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function loadTheme() {
    try {
      const value = window.localStorage.getItem(storage.theme);
      return value === "light" ? "light" : "dark";
    } catch (_error) {
      return "dark";
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage.setItem(storage.theme, theme);
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function loadStringPreference(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null || raw === "" ? fallback : raw;
    } catch (_error) {
      return fallback;
    }
  }

  function saveStringPreference(key, value) {
    try {
      window.localStorage.setItem(key, String(value));
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function currentKbUrl(params = {}) {
    const url = new URL(window.location.href);
    url.search = "";
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "" || value === false) return;
      url.searchParams.set(key, String(value));
    });
    return url.toString();
  }

  function syncWorkbenchUrl() {
    const params = {};
    if (state.workbench.kind === "settings") {
      params.settings = "1";
    } else if (state.workbench.path) {
      params.path = state.workbench.path;
    }
    const nextUrl = currentKbUrl(params);
    window.history.replaceState({}, "", nextUrl);
  }

  function parseLaunchState() {
    const url = new URL(window.location.href);
    return {
      path: normalizeInternalPath(url.searchParams.get("path") || ""),
      settings: url.searchParams.get("settings") === "1",
      consumed: false,
    };
  }

  function applyPreferences() {
    const uiScale = Number(state.preferences.uiScale || "100") / 100;
    const readerFont = Number(state.preferences.readerFontSize || "92") / 100;
    const editorFont = Number(state.preferences.editorFontSize || "84") / 100;
    const readerLine = Number(state.preferences.readerLineHeight || "166") / 100;
    const listDensity = state.preferences.listDensity || "comfortable";
    const previewWidthMap = {
      narrow: "54rem",
      wide: "68rem",
      full: "100%",
    };
    document.documentElement.style.setProperty("--ui-scale", String(uiScale));
    document.documentElement.style.setProperty("--reader-font-size", `${readerFont}rem`);
    document.documentElement.style.setProperty("--editor-font-size", `${editorFont}rem`);
    document.documentElement.style.setProperty("--reader-line-height", String(readerLine));
    document.documentElement.style.setProperty("--preview-max-width", previewWidthMap[state.preferences.previewWidth] || "68rem");
    document.documentElement.dataset.listDensity = listDensity;
    if (terminalRuntime.xterm) {
      terminalRuntime.xterm.options.fontSize = Number(state.preferences.terminalFontSize || "12");
      state.terminal.needsFit = true;
      fitTerminal();
    }
  }

  function loadPreferences() {
    state.preferences.uiScale = loadStringPreference(storage.uiScale, state.preferences.uiScale);
    state.preferences.readerFontSize = loadStringPreference(storage.readerFontSize, state.preferences.readerFontSize);
    state.preferences.readerLineHeight = loadStringPreference(storage.readerLineHeight, state.preferences.readerLineHeight);
    state.preferences.editorFontSize = loadStringPreference(storage.editorFontSize, state.preferences.editorFontSize);
    state.preferences.terminalFontSize = loadStringPreference(storage.terminalFontSize, state.preferences.terminalFontSize);
    state.preferences.listDensity = loadStringPreference(storage.listDensity, state.preferences.listDensity);
    state.preferences.previewWidth = loadStringPreference(storage.previewWidth, state.preferences.previewWidth);
    state.preferences.formulaRendering = loadBooleanPreference(storage.formulaRendering, state.preferences.formulaRendering);
    state.preferences.defaultTerminalMode = loadStringPreference(storage.defaultTerminalMode, state.preferences.defaultTerminalMode);
    state.preferences.defaultWorkbenchMode = loadStringPreference(storage.defaultWorkbenchMode, state.preferences.defaultWorkbenchMode);
    state.preferences.autoOpenWorkbench = loadBooleanPreference(storage.autoOpenWorkbench, state.preferences.autoOpenWorkbench);
    state.workbench.mode = state.preferences.defaultWorkbenchMode;
  }

  function resetLayoutPreferences() {
    document.documentElement.style.setProperty("--sidebar-width", "320px");
    document.documentElement.style.setProperty("--detail-width", "360px");
    document.documentElement.style.setProperty("--panel-height", "260px");
    saveSidebarWidth(320);
    saveDetailWidth(360);
    saveTerminalHeight(260);
    renderAll();
  }

  function themeToggleMarkup(theme) {
    if (theme === "light") {
      return `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20 14.5A7.5 7.5 0 0 1 9.5 4A8.5 8.5 0 1 0 20 14.5Z"></path>
        </svg>
      `;
    }
    return `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3.5V6.2"></path>
        <path d="M12 17.8V20.5"></path>
        <path d="M3.5 12H6.2"></path>
        <path d="M17.8 12H20.5"></path>
        <path d="M6 6L7.9 7.9"></path>
        <path d="M16.1 16.1L18 18"></path>
        <path d="M18 6L16.1 7.9"></path>
        <path d="M7.9 16.1L6 18"></path>
        <circle cx="12" cy="12" r="4.2"></circle>
      </svg>
    `;
  }

  function terminalPalette() {
    if (state.layout.theme === "light") {
      return {
        background: "#f8fafc",
        foreground: "#1b2430",
        cursor: "#d66a2d",
        cursorAccent: "#f8fafc",
        selectionBackground: "rgba(214, 106, 45, 0.18)",
      };
    }
    return {
      background: "#111926",
      foreground: "#eef2f5",
      cursor: "#f4d4bd",
      cursorAccent: "#111926",
      selectionBackground: "rgba(180, 90, 45, 0.28)",
    };
  }

  function applyTheme(theme) {
    state.layout.theme = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = state.layout.theme;
    saveTheme(state.layout.theme);
    if (elements.themeToggleMark) {
      elements.themeToggleMark.innerHTML = themeToggleMarkup(state.layout.theme);
    }
    if (elements.sidebarToggleBtn) {
      const nextTheme = state.layout.theme === "light" ? "暗色" : "亮色";
      elements.sidebarToggleBtn.setAttribute("data-tip", `切换到${nextTheme}主题`);
      elements.sidebarToggleBtn.setAttribute("aria-label", `切换到${nextTheme}主题`);
    }
    if (terminalRuntime.xterm) {
      terminalRuntime.xterm.options.theme = terminalPalette();
    }
  }

  function cssNumber(variableName, fallback) {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(variableName);
    const value = parseFloat(raw);
    return Number.isFinite(value) ? value : fallback;
  }

  function setSidebarCollapsed(collapsed) {
    state.layout.sidebarCollapsed = !!collapsed;
    saveBooleanPreference(storage.sidebarCollapsed, state.layout.sidebarCollapsed);
  }

  function setDetailCollapsed(collapsed) {
    state.layout.detailCollapsed = !!collapsed;
    saveBooleanPreference(storage.detailCollapsed, state.layout.detailCollapsed);
  }

  function setTerminalCollapsed(collapsed) {
    state.terminal.collapsed = !!collapsed;
    saveBooleanPreference(storage.terminalCollapsed, state.terminal.collapsed);
  }

  function setSearchExpanded(expanded) {
    state.layout.searchExpanded = !!expanded;
  }

  function updateSearchUi() {
    const expanded = !!state.layout.searchExpanded;
    const placeholder = `搜索当前${TAB_CONFIG.find((item) => item.id === state.tab)?.label || "视图"}，留空则显示当前筛选结果`;
    elements.search.placeholder = placeholder;
    elements.activitySearchBtn.classList.toggle("active", expanded);
    elements.activitySearchBtn.setAttribute("data-tip", expanded ? "收起搜索分栏" : "展开搜索分栏");
    elements.activitySearchBtn.setAttribute("aria-label", expanded ? "收起搜索分栏" : "展开搜索分栏");
  }

  function renderLayout() {
    const sidebarVisible = !state.layout.sidebarCollapsed;
    const detailVisible = !state.layout.detailCollapsed;
    const panelVisible = !state.terminal.collapsed;

    elements.appShell.classList.toggle("search-mode", !!state.layout.searchMode);
    elements.appShell.classList.toggle("sidebar-collapsed", !sidebarVisible);
    document.documentElement.style.setProperty("--sidebar-current-width", sidebarVisible ? `${cssNumber("--sidebar-width", 320)}px` : "0px");
    document.documentElement.style.setProperty("--detail-current-width", detailVisible ? `${cssNumber("--detail-width", 360)}px` : "0px");
    document.documentElement.style.setProperty("--panel-current-height", panelVisible ? `${cssNumber("--panel-height", 260)}px` : "0px");
    document.documentElement.style.setProperty("--left-resizer-current", sidebarVisible ? "4px" : "0px");
    document.documentElement.style.setProperty("--right-resizer-current", detailVisible ? "4px" : "0px");
    document.documentElement.style.setProperty("--bottom-resizer-current", panelVisible ? "4px" : "0px");

    elements.primarySidebar.classList.toggle("collapsed", !sidebarVisible);
    elements.detailPanel.classList.toggle("collapsed", !detailVisible);
    elements.terminalPanel.classList.toggle("collapsed", !panelVisible);
    elements.listResizer.classList.toggle("hidden", !sidebarVisible);
    elements.detailResizer.classList.toggle("hidden", !detailVisible);
    elements.terminalResizer.classList.toggle("hidden", !panelVisible);
    elements.detailCollapsedHandle.classList.toggle("hidden", detailVisible || window.innerWidth <= 1080);
    elements.terminalCollapsedHandle.classList.toggle("hidden", panelVisible || window.innerWidth <= 1080);

    elements.sidebarToggleBtn.classList.toggle("active", state.layout.theme === "light");
    elements.detailToggleBtn.classList.toggle("active", detailVisible);
    elements.terminalToggleBtn.classList.toggle("active", panelVisible);
    updateSearchUi();
  }

  function terminalSupportsXterm() {
    return Boolean(window.Terminal && window.FitAddon && window.FitAddon.FitAddon);
  }

  function ensureTerminalEmulator() {
    if (!terminalSupportsXterm()) return false;
    if (terminalRuntime.ready && terminalRuntime.xterm) return true;
    elements.terminalScreen.innerHTML = "";
    const term = new window.Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: '"SF Mono", "Menlo", "Monaco", "Cascadia Code", "Consolas", monospace',
      fontSize: Number(state.preferences.terminalFontSize || "12"),
      lineHeight: 1.2,
      allowTransparency: true,
      scrollback: 5000,
      theme: terminalPalette(),
    });
    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(elements.terminalScreen);
    term.onData((data) => {
      sendTerminalInput(data);
    });
    terminalRuntime.xterm = term;
    terminalRuntime.fitAddon = fitAddon;
    terminalRuntime.ready = true;
    state.terminal.needsFit = true;
    return true;
  }

  async function resizeTerminalBackend() {
    if (!state.terminal.sessionId || !terminalRuntime.xterm) return;
    try {
      await fetchJson(terminalResizeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.terminal.sessionId,
          cols: terminalRuntime.xterm.cols,
          rows: terminalRuntime.xterm.rows,
        }),
      });
    } catch (_error) {
      // Resize failures are non-fatal; keep the current session alive.
    }
  }

  function fitTerminal() {
    if (!terminalRuntime.ready || !terminalRuntime.fitAddon || state.terminal.collapsed) return;
    try {
      terminalRuntime.fitAddon.fit();
      resizeTerminalBackend();
      state.terminal.needsFit = false;
    } catch (_error) {
      // Ignore fit errors until the panel is visible.
    }
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

  function fmtShortTime(value) {
    if (!value) return "--:--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function badge(text, klass = "") {
    if (!text) return "";
    return `<span class="badge ${klass}">${escapeHtml(text)}</span>`;
  }

  function linkChip(link, label) {
    if (!link) return "";
    const href = typeof link === "string" ? link : link.href;
    if (!href) return "";
    const internalPath = typeof link === "object" ? normalizeInternalPath(link.path || hrefToPath(href)) : hrefToPath(href);
    const attrs = internalPath && isTextPath(internalPath)
      ? ` data-open-path="${escapeHtml(internalPath)}" data-open-kind="${isMarkdownPath(internalPath) ? "markdown" : "text"}" data-tip="${escapeHtml(`${label} · ${internalPath}`)}"`
      : "";
    return `<a class="link-chip" href="${escapeHtml(href)}" target="_blank" rel="noreferrer"${attrs}>${escapeHtml(label)}</a>`;
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
      user_entry_items: [],
      wiki_index_preview: "",
      wiki_log_preview: "",
      wiki_query_items: [],
      wiki_lint_preview: "",
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
        <button class="tab-button ${selected}" data-tab="${tab.id}" data-tip="${escapeHtml(`${tab.label} · ${countText}`)}" data-tip-side="right" aria-label="${escapeHtml(tab.label)}">
          ${tabIcon(tab.id)}
          <span class="tab-label">${escapeHtml(tab.label)}</span>
          <span class="tab-count">${escapeHtml(countText)}</span>
        </button>
      `;
    }).join("");
  }

  function searchTargetLabel(value) {
    const labels = {
      all: "全部",
      literature: "论文",
      repos: "仓库",
      tags: "标签",
      landscapes: "趋势",
      programs: "Program",
      wiki: "Wiki",
    };
    return labels[value] || value;
  }

  function programStageLabel(value) {
    return PROGRAM_STAGES.find((stage) => stage.id === value)?.label || value || "未标注";
  }

  function wikiKindLabel(value) {
    const labels = {
      index: "Index",
      log: "Log",
      lint: "Lint",
      query: "Query",
    };
    return labels[value] || value || "Wiki";
  }

  function facetOptions(items, key, options = {}) {
    const {
      numeric = false,
      limit = 60,
      labeler = null,
    } = options;
    const counts = new Map();
    (items || []).forEach((item) => {
      const raw = item ? item[key] : null;
      const values = Array.isArray(raw) ? raw : [raw];
      values.forEach((entry) => {
        const normalized = String(entry || "").trim();
        if (!normalized) return;
        counts.set(normalized, (counts.get(normalized) || 0) + 1);
      });
    });
    const entries = Array.from(counts.entries()).map(([value, count]) => ({
      value,
      count,
      label: typeof labeler === "function" ? labeler(value) : value,
    }));
    entries.sort((left, right) => {
      if (numeric) return Number(right.value) - Number(left.value) || right.count - left.count || String(left.label).localeCompare(String(right.label));
      return right.count - left.count || String(left.label).localeCompare(String(right.label));
    });
    return entries.slice(0, limit);
  }

  function includesFilter(raw, expected) {
    if (!expected || expected === "all") return true;
    if (Array.isArray(raw)) {
      return raw.map((entry) => String(entry || "")).includes(String(expected));
    }
    return String(raw || "") === String(expected);
  }

  function filterSpecsForTab(tab) {
    const snapshot = getSnapshot();
    if (tab === "literature") {
      const items = snapshot.literature_items || [];
      return [
        { key: "literatureYear", label: "年份", options: facetOptions(items, "year", { numeric: true, limit: 24 }) },
        { key: "literatureTopic", label: "领域 / Topic", options: facetOptions(items, "topics", { limit: 36 }) },
        { key: "literatureTag", label: "标签", options: facetOptions(items, "tags", { limit: 36 }) },
        { key: "literatureAuthor", label: "作者", options: facetOptions(items, "authors", { limit: 48 }) },
        { key: "literatureSourceKind", label: "来源类型", options: facetOptions(items, "source_kind", { limit: 12 }) },
        { key: "literatureClaims", label: "Claims", options: facetOptions(items, "claims_status", { limit: 12 }) },
      ];
    }
    if (tab === "repos") {
      const items = snapshot.repo_items || [];
      return [
        { key: "repoFramework", label: "框架", options: facetOptions(items, "frameworks", { limit: 24 }) },
        { key: "repoTag", label: "标签", options: facetOptions(items, "tags", { limit: 36 }) },
        { key: "repoTopic", label: "主题", options: facetOptions(items, "topics", { limit: 24 }) },
        { key: "repoOwner", label: "Owner", options: facetOptions(items, "owner_name", { limit: 20 }) },
        { key: "repoImportType", label: "导入方式", options: facetOptions(items, "import_type", { limit: 12 }) },
      ];
    }
    if (tab === "tags") {
      return [{ key: "tagStatus", label: "状态", options: facetOptions(snapshot.tag_items || [], "status", { limit: 12 }) }];
    }
    if (tab === "landscapes") {
      const items = snapshot.landscape_items || [];
      return [
        { key: "landscapeScope", label: "范围", options: facetOptions(items, "scope", { limit: 12 }) },
        { key: "landscapeTag", label: "查询标签", options: facetOptions(items, "query_tags", { limit: 24 }) },
      ];
    }
    if (tab === "programs") {
      const items = snapshot.program_items || [];
      return [
        { key: "programStage", label: "阶段", options: facetOptions(items, "stage", { limit: 12, labeler: programStageLabel }) },
        { key: "programRepo", label: "选中仓库", options: facetOptions(items, "selected_repo_id", { limit: 16 }) },
      ];
    }
    if (tab === "wiki") {
      return [{ key: "wikiKind", label: "类型", options: facetOptions(wikiItems(), "wiki_kind", { limit: 8, labeler: wikiKindLabel }) }];
    }
    return [];
  }

  function filterSpecsForCurrentTab() {
    if (state.layout.searchMode) {
      const target = state.filters.searchTarget || "all";
      const specs = [
        {
          key: "searchTarget",
          label: "范围",
          options: ["literature", "repos", "tags", "landscapes", "programs", "wiki"].map((value) => ({
            value,
            label: searchTargetLabel(value),
            count: snapshotCount(
              value === "literature" ? "literature_count" :
              value === "repos" ? "repo_count" :
              value === "tags" ? "tag_count" :
              value === "landscapes" ? "landscape_count" :
              value === "programs" ? "program_count" : "wiki_item_count"
            ),
          })),
        },
      ];
      return target === "all" ? specs : specs.concat(filterSpecsForTab(target));
    }
    return filterSpecsForTab(state.tab);
  }

  function renderFilterBar() {
    const specs = filterSpecsForCurrentTab();
    if (!specs.length) {
      elements.filterBar.innerHTML = state.layout.searchMode
        ? '<span class="inline-hint">输入关键词后开始搜索。</span>'
        : '<span class="inline-hint">当前视图无额外筛选。</span>';
      return;
    }
    elements.filterBar.innerHTML = specs
      .map((spec) => {
        const current = state.filters[spec.key] || "all";
        const options = ['<option value="all">全部</option>']
          .concat(
            (spec.options || []).map((rawOpt) => {
              const opt = typeof rawOpt === "string"
                ? { value: rawOpt, label: rawOpt, count: 0 }
                : rawOpt;
              const value = String(opt.value || "");
              const selected = current === value ? "selected" : "";
              const label = `${opt.label || value}${opt.count ? ` (${opt.count})` : ""}`;
              return `<option value="${escapeHtml(value)}" ${selected}>${escapeHtml(label)}</option>`;
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

  function quickOpenItems() {
    const snapshot = getSnapshot();
    const curated = Array.isArray(snapshot.user_entry_items) ? snapshot.user_entry_items : [];
    return curated.filter((item) => item && item.path && item.href).slice(0, 14);
  }

  function renderQuickOpenBar() {
    const items = quickOpenItems();
    if (!items.length) {
      elements.quickOpenBar.innerHTML = '<span class="inline-hint">当前没有可用快捷入口。</span>';
      return;
    }
    const shortLabel = (item) => {
      const group = String(item.group || "");
      const title = String(item.title || basename(item.path || ""));
      const path = normalizeInternalPath(item.path || "");
      if (title.includes("研究导航")) return "导航";
      if (title.includes("上手指南")) return "指南";
      if (title.includes("Wiki Log")) return "日志";
      if (title.includes("Wiki Index")) return "索引";
      if (group === "reading" || /reading/i.test(path)) return "阅读";
      if (group === "report") return "成果";
      if (/weekly\//.test(path)) return "周报";
      if (/state\.yaml$/.test(path)) return "状态";
      if (/system-design\.md$/.test(path)) return "设计";
      if (/runbook\.md$/.test(path)) return "实验";
      return title.replace(/humanoid[-_ ]vla[-_ ]wholebody[-_ ]control/gi, "").trim() || basename(path);
    };
    elements.quickOpenBar.innerHTML = items
      .map((item) => {
        const relPath = normalizeInternalPath(item.path || hrefToPath(item.href));
        const markdownClass = isMarkdownPath(relPath) ? "primary" : "";
        return `<a class="link-chip ${markdownClass}" href="${escapeHtml(item.href)}" data-open-path="${escapeHtml(relPath)}" data-open-kind="${isMarkdownPath(relPath) ? "markdown" : "text"}" data-tip="${escapeHtml(`${item.title || basename(relPath)} · ${relPath}`)}">${escapeHtml(shortLabel(item))}</a>`;
      })
      .join("");
  }

  function matchQuery(entity, query) {
    if (!query) return true;
    const haystack = [
      entity.source_id,
      entity.title,
      entity.repo_name,
      entity.repo_id,
      entity.tag,
      entity.field,
      entity.program_id,
      entity.goal,
      entity.question,
      entity.year,
      entity.source_kind,
      entity.owner_name,
      entity.import_type,
      entity.scope,
      entity.stage,
      entity.status,
      entity.claims_status,
      entity.selected_repo_id,
      entity.site_fingerprint,
      entity.short_summary,
      entity.summary_preview,
      entity.description,
      entity.preview,
      entity.query_path,
      entity.wiki_kind,
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

  function itemPassesFilters(tab, item) {
    if (tab === "literature") {
      return includesFilter(item.tags, state.filters.literatureTag)
        && includesFilter(item.topics, state.filters.literatureTopic)
        && includesFilter(item.authors, state.filters.literatureAuthor)
        && includesFilter(item.source_kind, state.filters.literatureSourceKind)
        && includesFilter(item.claims_status, state.filters.literatureClaims)
        && (state.filters.literatureYear === "all" || String(item.year || "") === String(state.filters.literatureYear));
    }
    if (tab === "repos") {
      return includesFilter(item.tags, state.filters.repoTag)
        && includesFilter(item.topics, state.filters.repoTopic)
        && includesFilter(item.frameworks, state.filters.repoFramework)
        && includesFilter(item.owner_name, state.filters.repoOwner)
        && includesFilter(item.import_type, state.filters.repoImportType);
    }
    if (tab === "tags") {
      return includesFilter(item.status, state.filters.tagStatus);
    }
    if (tab === "landscapes") {
      return includesFilter(item.scope, state.filters.landscapeScope)
        && includesFilter(item.query_tags, state.filters.landscapeTag);
    }
    if (tab === "programs") {
      return includesFilter(item.stage, state.filters.programStage)
        && includesFilter(item.selected_repo_id, state.filters.programRepo);
    }
    if (tab === "wiki") {
      return includesFilter(item.wiki_kind, state.filters.wikiKind);
    }
    return true;
  }

  function searchScopedFilter(tab, item) {
    const target = state.filters.searchTarget || "all";
    if (!state.layout.searchMode || target !== tab) return true;
    return itemPassesFilters(tab, item);
  }

  function filteredLiterature() {
    const query = activeQuery();
    return (getSnapshot().literature_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      return itemPassesFilters("literature", item);
    });
  }

  function filteredRepos() {
    const query = activeQuery();
    return (getSnapshot().repo_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      return itemPassesFilters("repos", item);
    });
  }

  function filteredTags() {
    const query = activeQuery();
    return (getSnapshot().tag_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      return itemPassesFilters("tags", item);
    });
  }

  function filteredLandscapes() {
    const query = activeQuery();
    return (getSnapshot().landscape_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      return itemPassesFilters("landscapes", item);
    });
  }

  function filteredPrograms() {
    const query = activeQuery();
    return (getSnapshot().program_items || []).filter((item) => {
      if (!matchQuery(item, query)) return false;
      return itemPassesFilters("programs", item);
    });
  }

  function filteredWiki() {
    return wikiItems().filter((item) => itemPassesFilters("wiki", item));
  }

  function wikiItems() {
    const snapshot = getSnapshot();
    const queryItems = Array.isArray(snapshot.wiki_query_items) ? snapshot.wiki_query_items : [];
    const baseItems = [
      {
        wiki_id: "wiki-index",
        title: "Wiki Index",
        subtitle: "index 预览",
        short_summary: snapshot.wiki_index_preview || "暂无 wiki index 结果。",
        wiki_kind: "index",
      },
      {
        wiki_id: "wiki-log",
        title: "Wiki Log",
        subtitle: "log 预览",
        short_summary: snapshot.wiki_log_preview || "暂无 wiki log 结果。",
        wiki_kind: "log",
      },
      {
        wiki_id: "wiki-lint",
        title: "Wiki Lint",
        subtitle: "lint 预览",
        short_summary: snapshot.wiki_lint_preview || "暂无 wiki lint 结果。",
        wiki_kind: "lint",
      },
    ];
    const queryCards = queryItems.map((entry, index) => ({
      wiki_id: `wiki-query-${entry.query_id || index}`,
      title: entry.title || entry.query_id || `query-${index + 1}`,
      subtitle: entry.query_path || "kb/wiki/queries",
      short_summary: entry.preview || "暂无 query 预览。",
      wiki_kind: "query",
      query_path: entry.query_path || "",
      query_href: entry.query_href || "",
      query_id: entry.query_id || "",
      updated_at: entry.updated_at || "",
      preview: entry.preview || "",
    }));
    return baseItems.concat(queryCards).filter((item) => matchQuery(item, activeQuery()));
  }

  function overviewItems() {
    const items = [
      {
        overview_id: "overview-literature",
        title: "查看论文库",
        subtitle: `${snapshotCount("literature_count")} 篇`,
        short_summary: "按标题、作者、标签、主题快速检索，并查看摘要、claims 状态和来源链接。",
        tags: ["跳转到论文"],
        kind: "jump",
        jump_tab: "literature",
      },
      {
        overview_id: "overview-repos",
        title: "查看仓库库",
        subtitle: `${snapshotCount("repo_count")} 个`,
        short_summary: "聚合仓库摘要、框架、入口点和源码链接，便于设计阶段快速选型。",
        tags: ["跳转到仓库"],
        kind: "jump",
        jump_tab: "repos",
      },
      {
        overview_id: "overview-programs",
        title: "查看 Program",
        subtitle: `${snapshotCount("program_count")} 个`,
        short_summary: "进入 Program 视图可通过阶段时间轴浏览问题定义、文献分析、想法评审到方法设计。",
        tags: ["跳转到 Program"],
        kind: "jump",
        jump_tab: "programs",
      },
      {
        overview_id: "overview-wiki",
        title: "查看 Wiki / 查询",
        subtitle: `${snapshotCount("wiki_query_count")} 条 query 结果`,
        short_summary: "集中查看 wiki index/log 预览、query 条目以及 lint 最新结果。",
        tags: ["跳转到 Wiki"],
        kind: "jump",
        jump_tab: "wiki",
      },
    ];
    return items.filter((item) => matchQuery(item, activeQuery()));
  }

  function normalizeArray(value) {
    return Array.isArray(value) ? value.filter(Boolean).map((entry) => String(entry)) : [];
  }

  function searchResults() {
    const query = norm(state.query);
    if (!state.layout.searchMode) return [];
    const target = state.filters.searchTarget || "all";
    const include = (tab) => target === "all" || target === tab;
    const results = [];

    if (include("literature")) {
      (getSnapshot().literature_items || []).forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("literature", item)) return;
        results.push({
          search_id: `literature:${item.source_id}`,
          search_tab: "literature",
          target_id: item.source_id,
          title: item.title || item.source_id,
          subtitle: `论文 · ${item.year || "未知年份"}`,
          short_summary: item.short_summary || item.note_preview || "",
          chips: (item.tags || []).slice(0, 3),
          open_path: item.links && item.links.note && item.links.note.path,
        });
      });
    }
    if (include("repos")) {
      (getSnapshot().repo_items || []).forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("repos", item)) return;
        results.push({
          search_id: `repos:${item.repo_id}`,
          search_tab: "repos",
          target_id: item.repo_id,
          title: item.repo_name || item.repo_id,
          subtitle: `仓库 · ${item.owner_name || "未知 owner"}`,
          short_summary: item.short_summary || "",
          chips: (item.frameworks || []).slice(0, 3),
          open_path: item.links && item.links.notes && item.links.notes.path,
        });
      });
    }
    if (include("tags")) {
      (getSnapshot().tag_items || []).forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("tags", item)) return;
        results.push({
          search_id: `tags:${item.tag}`,
          search_tab: "tags",
          target_id: item.tag,
          title: item.tag,
          subtitle: `标签 · 论文 ${item.literature_count || 0} / 仓库 ${item.repo_count || 0}`,
          short_summary: item.description || "",
          chips: [item.status || "active"],
          open_path: item.links && item.links.taxonomy && item.links.taxonomy.path,
        });
      });
    }
    if (include("landscapes")) {
      (getSnapshot().landscape_items || []).forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("landscapes", item)) return;
        results.push({
          search_id: `landscapes:${item.survey_id}`,
          search_tab: "landscapes",
          target_id: item.survey_id,
          title: item.field || item.survey_id,
          subtitle: `趋势 · ${item.scope || "未标注"}`,
          short_summary: item.summary_preview || "",
          chips: (item.query_tags || []).slice(0, 3),
          open_path: item.links && item.links.summary && item.links.summary.path,
        });
      });
    }
    if (include("programs")) {
      (getSnapshot().program_items || []).forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("programs", item)) return;
        results.push({
          search_id: `programs:${item.program_id}`,
          search_tab: "programs",
          target_id: item.program_id,
          title: item.program_id,
          subtitle: `Program · ${item.stage || "未设置阶段"}`,
          short_summary: item.goal || item.question || "",
          chips: item.selected_idea_title ? [item.selected_idea_title] : [],
          open_path:
            (item.links && item.links.design_doc && item.links.design_doc.path) ||
            (item.links && item.links.runbook && item.links.runbook.path) ||
            "",
        });
      });
    }
    if (include("wiki")) {
      wikiItems().forEach((item) => {
        if (!matchQuery(item, query)) return;
        if (!searchScopedFilter("wiki", item)) return;
        results.push({
          search_id: `wiki:${item.wiki_id}`,
          search_tab: "wiki",
          target_id: item.wiki_id,
          title: item.title || item.wiki_id,
          subtitle: `Wiki · ${item.wiki_kind || "query"}`,
          short_summary: item.short_summary || item.preview || "",
          chips: item.wiki_kind ? [item.wiki_kind] : [],
          open_path: item.query_path || "",
        });
      });
    }

    return results.slice(0, 80);
  }

  function hasActiveVisibleFilters() {
    return filterSpecsForCurrentTab().some((spec) => {
      const value = state.filters[spec.key];
      return value !== undefined && value !== "all";
    });
  }

  function listSearchContextActive() {
    return !!activeQuery() || hasActiveVisibleFilters();
  }

  function renderSearchSection() {
    const expanded = !!state.layout.searchExpanded;
    elements.sidebarSearch.classList.toggle("expanded", expanded);
    elements.searchSectionToggleBtn.classList.toggle("active", expanded);
    elements.searchSectionToggleBtn.setAttribute("data-tip", expanded ? "收起搜索分栏" : "展开搜索分栏");
    elements.searchSectionToggleBtn.setAttribute("aria-label", expanded ? "收起搜索分栏" : "展开搜索分栏");
    const parts = [];
    if (norm(state.query)) parts.push("含关键词");
    const filterCount = filterSpecsForCurrentTab().filter((spec) => {
      const value = state.filters[spec.key];
      return value !== undefined && value !== "all";
    }).length;
    if (filterCount) parts.push(`${filterCount} 个筛选`);
    if (!parts.length) parts.push("默认收起");
    elements.searchSectionMeta.textContent = parts.join(" · ");
  }

  function listForCurrentTab() {
    if (state.layout.searchMode) return searchResults();
    if (state.tab === "literature") return filteredLiterature();
    if (state.tab === "repos") return filteredRepos();
    if (state.tab === "tags") return filteredTags();
    if (state.tab === "landscapes") return filteredLandscapes();
    if (state.tab === "programs") return filteredPrograms();
    if (state.tab === "wiki") return filteredWiki();
    return overviewItems();
  }

  function selectedFieldForTab(tab) {
    if (tab === "literature") return "source_id";
    if (tab === "repos") return "repo_id";
    if (tab === "tags") return "tag";
    if (tab === "landscapes") return "survey_id";
    if (tab === "programs") return "program_id";
    if (tab === "wiki") return "wiki_id";
    return "overview_id";
  }

  function itemActionLinks(tab, item) {
    if (!item) return [];
    if (tab === "literature" && item.links) {
      return [
        linkChip(item.links.note, "笔记"),
        linkChip(item.links.primary_pdf, "PDF"),
        linkChip(item.links.metadata, "元数据"),
      ];
    }
    if (tab === "repos" && item.links) {
      return [
        linkChip(item.links.notes, "笔记"),
        linkChip(item.links.summary, "摘要"),
        linkChip(item.links.source, "源码"),
      ];
    }
    if (tab === "programs" && item.links) {
      return [
        linkChip(item.links.state, "状态"),
        linkChip(item.links.design_doc, "设计"),
        linkChip(item.links.runbook, "实验"),
      ];
    }
    if (tab === "wiki") {
      return [
        item.query_href ? linkChip(item.query_href, "查询文件") : "",
      ];
    }
    if (tab === "landscapes" && item.links) {
      return [
        linkChip(item.links.summary, "总结"),
        linkChip(item.links.report, "报告"),
      ];
    }
    if (tab === "tags" && item.links) {
      return [
        linkChip(item.links.taxonomy, "taxonomy"),
      ];
    }
    return [];
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
    if (state.layout.searchMode) {
      return `
        <article class="list-card compact search-hit" data-kind="search" data-id="${escapeHtml(item.search_id)}">
          <h3 class="list-title">${escapeHtml(item.title || item.search_id)}</h3>
          <div class="list-meta search-meta">
            <p class="list-subtitle">${escapeHtml(item.subtitle || searchTargetLabel(item.search_tab || ""))}</p>
            <p class="list-summary">${escapeHtml(compactText(item.short_summary || "无摘要", 90))}</p>
            <div class="badge-row">
              ${badge(searchTargetLabel(item.search_tab || ""), "soft")}
              ${(item.chips || []).slice(0, 3).map((chip) => badge(chip)).join("")}
            </div>
          </div>
        </article>
      `;
    }
    const searchContext = listSearchContextActive() ? "search-context" : "";
    if (state.tab === "literature") {
      const selected = state.selected.literature === item.source_id ? "selected" : "";
      const expanded = state.expanded.literature === item.source_id ? "expanded" : "";
      const subtitle = `${item.year || "未知年份"} · ${fmtList((item.authors || []).slice(0, 3), "作者未知")}`;
      const summary = compactText(item.short_summary || item.note_preview || "暂无摘要", 120);
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="literature" data-id="${escapeHtml(item.source_id)}">
          <h3 class="list-title">${escapeHtml(item.title || item.source_id)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(summary)}</p>
            <div class="badge-row">
            ${(item.tags || []).slice(0, 4).map((tag) => badge(tag)).join("")}
            ${item.claims_status ? badge(item.claims_status, item.claims_status.includes("placeholder") ? "warn" : "soft") : ""}
            </div>
            <div class="list-actions">${itemActionLinks("literature", item).join("")}</div>
          </div>
        </article>
      `;
    }
    if (state.tab === "repos") {
      const selected = state.selected.repos === item.repo_id ? "selected" : "";
      const expanded = state.expanded.repos === item.repo_id ? "expanded" : "";
      const subtitle = `${item.import_type || "unknown import"} · ${item.owner_name || "unknown owner"}`;
      const summary = compactText(item.short_summary || "暂无仓库摘要", 120);
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="repos" data-id="${escapeHtml(item.repo_id)}">
          <h3 class="list-title">${escapeHtml(item.repo_name || item.repo_id)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(summary)}</p>
            <div class="badge-row">
            ${(item.tags || []).slice(0, 3).map((tag) => badge(tag)).join("")}
            ${(item.frameworks || []).slice(0, 2).map((tag) => badge(tag, "soft")).join("")}
            </div>
            <div class="list-actions">${itemActionLinks("repos", item).join("")}</div>
          </div>
        </article>
      `;
    }
    if (state.tab === "tags") {
      const selected = state.selected.tags === item.tag ? "selected" : "";
      const expanded = state.expanded.tags === item.tag ? "expanded" : "";
      const subtitle = `${item.literature_count || 0} 篇论文 · ${item.repo_count || 0} 个仓库`;
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="tags" data-id="${escapeHtml(item.tag)}">
          <h3 class="list-title">${escapeHtml(item.tag)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(compactText(item.description || "暂无标签说明", 120))}</p>
            <div class="badge-row">
              ${badge(item.status || "active", item.status === "active" ? "ok" : "warn")}
            </div>
            <div class="list-actions">${itemActionLinks("tags", item).join("")}</div>
          </div>
        </article>
      `;
    }
    if (state.tab === "landscapes") {
      const selected = state.selected.landscapes === item.survey_id ? "selected" : "";
      const expanded = state.expanded.landscapes === item.survey_id ? "expanded" : "";
      const subtitle = `${item.scope || "scope 未标注"} · 论文 ${item.matched_literature_count || 0} · 仓库 ${item.matched_repo_count || 0}`;
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="landscapes" data-id="${escapeHtml(item.survey_id)}">
          <h3 class="list-title">${escapeHtml(item.field || item.survey_id)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(compactText(item.summary_preview || "暂无趋势总结", 120))}</p>
            <div class="badge-row">
            ${(item.query_tags || []).slice(0, 4).map((tag) => badge(tag)).join("")}
            </div>
            <div class="list-actions">${itemActionLinks("landscapes", item).join("")}</div>
          </div>
        </article>
      `;
    }
    if (state.tab === "programs") {
      const selected = state.selected.programs === item.program_id ? "selected" : "";
      const expanded = state.expanded.programs === item.program_id ? "expanded" : "";
      const subtitle = `${item.stage || "stage 未设置"} · idea ${item.idea_count || 0} 个`;
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="programs" data-id="${escapeHtml(item.program_id)}">
          <h3 class="list-title">${escapeHtml(item.program_id)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(compactText(item.goal || item.question || "暂无 program 摘要", 120))}</p>
            <div class="badge-row">
            ${item.selected_idea_title ? badge(item.selected_idea_title, "soft") : badge("尚未选中 idea", "warn")}
            </div>
            <div class="list-actions">${itemActionLinks("programs", item).join("")}</div>
          </div>
        </article>
      `;
    }
    if (state.tab === "wiki") {
      const selected = state.selected.wiki === item.wiki_id ? "selected" : "";
      const expanded = state.expanded.wiki === item.wiki_id ? "expanded" : "";
      const subtitle = `${item.subtitle || "wiki 条目"}${item.updated_at ? ` · ${fmtTime(item.updated_at)}` : ""}`;
      return `
        <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="wiki" data-id="${escapeHtml(item.wiki_id)}">
          <h3 class="list-title">${escapeHtml(item.title || item.wiki_id)}</h3>
          <div class="list-meta">
            <p class="list-subtitle">${escapeHtml(subtitle)}</p>
            <p class="list-summary">${escapeHtml(compactText(item.short_summary || "暂无预览", 120))}</p>
            <div class="badge-row">
              ${badge(item.wiki_kind || "wiki", "soft")}
            </div>
            <div class="list-actions">${itemActionLinks("wiki", item).join("")}</div>
          </div>
        </article>
      `;
    }
    const selected = state.selected.overview === item.overview_id ? "selected" : "";
    const expanded = state.expanded.overview === item.overview_id ? "expanded" : "";
    return `
      <article class="list-card compact ${searchContext} ${selected} ${expanded}" data-kind="overview" data-id="${escapeHtml(item.overview_id)}">
        <h3 class="list-title">${escapeHtml(item.title)}</h3>
        <div class="list-meta">
          <p class="list-subtitle">${escapeHtml(item.subtitle || "")}</p>
          <p class="list-summary">${escapeHtml(item.short_summary || "")}</p>
          <div class="badge-row">
            ${(item.tags || []).slice(0, 4).map((tag) => badge(tag, "soft")).join("")}
          </div>
          <div class="list-actions">${item.jump_tab ? badge(`跳到 ${item.jump_tab}`, "soft") : ""}</div>
        </div>
      </article>
    `;
  }

  function renderList() {
    const items = listForCurrentTab();
    if (!state.layout.searchMode) {
      ensureSelection(items);
    }
    const tabLabel = TAB_CONFIG.find((item) => item.id === state.tab)?.label || "总览";
    elements.listTitle.textContent = state.layout.searchMode ? "全局搜索" : tabLabel;
    elements.listMeta.textContent = state.layout.searchMode ? `${searchTargetLabel(state.filters.searchTarget || "all")} · ${items.length} 条` : `${items.length} 条`;
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
    const snapshot = getSnapshot();
    elements.detailTitle.textContent = item.title || "总览";
    elements.detailMeta.textContent = "把最重要的信息留在顶部和工作台，这里只保留必要跳转。";
    elements.detailBody.innerHTML = [
      section(
        "当前最值得看的 3 类内容",
        renderKeyValues([
          ["当前阅读", escapeHtml("优先看 reading list / 关键论文 note / PDF")],
          ["当前设计", escapeHtml("优先看 repo-choice / system-design / runbook")],
          ["当前进展", escapeHtml("优先看 latest weekly / wiki log / reporting-events")],
        ])
      ),
      section(
        "工作区统计（精简）",
        renderKeyValues([
          ["论文", escapeHtml(String(snapshotCount("literature_count")))],
          ["仓库", escapeHtml(String(snapshotCount("repo_count")))],
          ["Program", escapeHtml(String(snapshotCount("program_count")))],
          ["Wiki 条目", escapeHtml(String(snapshotCount("wiki_item_count")))],
        ])
      ),
    ].join("");
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

  function renderWikiDetail(item) {
    const snapshot = getSnapshot();
    const queryItems = Array.isArray(snapshot.wiki_query_items) ? snapshot.wiki_query_items : [];
    elements.detailTitle.textContent = item.title || "Wiki";
    elements.detailMeta.textContent = `query ${queryItems.length} 条 · 更新于 ${fmtTime(snapshot.last_updated || snapshot.generated_at)}`;
    const selectedQuerySection = item.wiki_kind === "query"
      ? section(
          "当前 Query",
          `
            ${renderKeyValues([
              ["Query ID", escapeHtml(item.query_id || "未知")],
              ["路径", escapeHtml(item.query_path || "未知")],
              ["更新时间", escapeHtml(fmtTime(item.updated_at || ""))],
            ])}
            <p class="detail-copy">${escapeHtml(item.preview || "暂无 query 预览。")}</p>
            ${detailLinks([linkChip(item.query_href, "打开 query 文件")])}
          `
        )
      : "";
    const queryListHtml = queryItems.length
      ? queryItems
          .slice(0, 40)
          .map(
            (entry) => `
              <li>
                <strong>${escapeHtml(entry.title || entry.query_id || "未命名 query")}</strong><br />
                ${escapeHtml(compactText(entry.preview || "暂无预览", 160))}<br />
                <span class="panel-subtle">${escapeHtml(entry.query_path || "")}</span>
              </li>
            `
          )
          .join("")
      : "<li>暂无 query 结果。</li>";
    elements.detailBody.innerHTML = [
      section("Index 预览", `<p class="detail-copy">${escapeHtml(snapshot.wiki_index_preview || "暂无 wiki index 结果。")}</p>`),
      section("Log 预览", `<p class="detail-copy">${escapeHtml(snapshot.wiki_log_preview || "暂无 wiki log 结果。")}</p>`),
      section("Lint 预览", `<p class="detail-copy">${escapeHtml(snapshot.wiki_lint_preview || "暂无 wiki lint 结果。")}</p>`),
      selectedQuerySection,
      section("Query 列表", `<ul class="detail-list">${queryListHtml}</ul>`),
    ]
      .filter(Boolean)
      .join("");
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
    if (state.layout.searchMode) {
      elements.detailTitle.textContent = "全局搜索";
      elements.detailMeta.textContent = state.filters.searchTarget === "all"
        ? "统一检索全部知识类型"
        : `当前范围：${searchTargetLabel(state.filters.searchTarget)}`;
      elements.detailBody.innerHTML = `<div class="empty-state">${norm(state.query) ? "从左侧结果中选择条目后会直接跳转到对应视图。" : "当前正在显示满足筛选条件的全部结果；输入关键词后会进一步收窄。"}</div>`;
      typesetMath(elements.detailBody);
      return;
    }
    const selected = selectedItem(items);
    if (!selected) {
      elements.detailTitle.textContent = "请先选择条目";
      elements.detailMeta.textContent = "右侧将显示结构化详情";
      elements.detailBody.innerHTML = '<div class="empty-state">左侧列表暂无可展示条目，或需要先调整搜索条件。</div>';
      typesetMath(elements.detailBody);
      return;
    }

    if (state.tab === "literature") {
      renderLiteratureDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    if (state.tab === "repos") {
      renderRepoDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    if (state.tab === "tags") {
      renderTagDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    if (state.tab === "landscapes") {
      renderLandscapeDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    if (state.tab === "programs") {
      renderProgramDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    if (state.tab === "wiki") {
      renderWikiDetail(selected);
      typesetMath(elements.detailBody);
      return;
    }
    renderOverviewDetail(selected);
    typesetMath(elements.detailBody);
  }

  function workbenchStatus(text, klass) {
    elements.workbenchStatus.textContent = text;
    elements.workbenchStatus.className = ["status-pill", "workbench-status", klass || ""].filter(Boolean).join(" ");
  }

  function canGoWorkbenchHistory(delta) {
    const nextIndex = state.workbench.historyIndex + delta;
    return nextIndex >= 0 && nextIndex < state.workbench.history.length;
  }

  function rememberWorkbenchHistory(path) {
    const normalized = normalizeInternalPath(path);
    if (!normalized) return;
    const history = state.workbench.history.slice(0, state.workbench.historyIndex + 1);
    if (history[history.length - 1] === normalized) {
      state.workbench.history = history;
      state.workbench.historyIndex = history.length - 1;
      return;
    }
    history.push(normalized);
    state.workbench.history = history.slice(-40);
    state.workbench.historyIndex = state.workbench.history.length - 1;
  }

  function goWorkbenchHistory(delta) {
    if (!canGoWorkbenchHistory(delta)) return;
    const nextIndex = state.workbench.historyIndex + delta;
    const nextPath = state.workbench.history[nextIndex] || "";
    if (!nextPath) return;
    state.workbench.historyIndex = nextIndex;
    openWorkbenchFile(nextPath, { force: true, recordHistory: false });
  }

  function markdownInline(text, currentPath) {
    let html = escapeHtml(text || "");
    html = html.replace(/`([^`]+)`/g, (_m, code) => `<code>${escapeHtml(code)}</code>`);
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label, target) => {
      const rawTarget = String(target || "").trim();
      const resolved = resolveMarkdownTarget(currentPath, rawTarget);
      if (resolved.internalPath) {
        return `<a href="${escapeHtml(resolved.href)}" data-open-path="${escapeHtml(resolved.internalPath)}">${escapeHtml(label)}</a>`;
      }
      return `<a href="${escapeHtml(resolved.href || rawTarget)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
    });
    return html;
  }

  function resolveMarkdownTarget(currentPath, rawTarget) {
    if (!rawTarget) return { href: "", internalPath: "" };
    if (/^[a-z]+:\/\//i.test(rawTarget) || rawTarget.startsWith("mailto:")) {
      return { href: rawTarget, internalPath: "" };
    }
    if (rawTarget.startsWith("#")) {
      return { href: rawTarget, internalPath: "" };
    }
    const baseSegments = normalizeInternalPath(currentPath).split("/").slice(0, -1);
    const targetSegments = rawTarget.split("#")[0].split("/").filter(Boolean);
    const stack = rawTarget.startsWith("/") ? [] : baseSegments.slice();
    targetSegments.forEach((segment) => {
      if (segment === ".") return;
      if (segment === "..") {
        stack.pop();
        return;
      }
      stack.push(segment);
    });
    const internalPath = stack.join("/");
    return {
      href: `/${encodeURI(internalPath)}`,
      internalPath,
    };
  }

  function renderMarkdown(text, currentPath) {
    const normalized = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = normalized.split("\n");
    const blocks = [];
    let index = 0;

    function flushParagraph(buffer) {
      if (!buffer.length) return;
      blocks.push(`<p>${markdownInline(buffer.join(" "), currentPath)}</p>`);
      buffer.length = 0;
    }

    const paragraph = [];
    while (index < lines.length) {
      const raw = lines[index];
      const line = raw.trimEnd();
      if (!line.trim()) {
        flushParagraph(paragraph);
        index += 1;
        continue;
      }
      const fence = line.match(/^```(.*)$/);
      if (fence) {
        flushParagraph(paragraph);
        const codeLines = [];
        const lang = (fence[1] || "").trim();
        index += 1;
        while (index < lines.length && !/^```/.test(lines[index].trimEnd())) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(`<pre><code class="lang-${escapeHtml(lang)}">${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        flushParagraph(paragraph);
        const level = heading[1].length;
        blocks.push(`<h${level}>${markdownInline(heading[2], currentPath)}</h${level}>`);
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        flushParagraph(paragraph);
        blocks.push(`<blockquote>${markdownInline(line.replace(/^>\s?/, ""), currentPath)}</blockquote>`);
        index += 1;
        continue;
      }
      if (/^(-|\*)\s+/.test(line)) {
        flushParagraph(paragraph);
        const items = [];
        while (index < lines.length && /^(-|\*)\s+/.test(lines[index].trimEnd())) {
          items.push(`<li>${markdownInline(lines[index].trimEnd().replace(/^(-|\*)\s+/, ""), currentPath)}</li>`);
          index += 1;
        }
        blocks.push(`<ul>${items.join("")}</ul>`);
        continue;
      }
      if (/^\d+\.\s+/.test(line)) {
        flushParagraph(paragraph);
        const items = [];
        while (index < lines.length && /^\d+\.\s+/.test(lines[index].trimEnd())) {
          items.push(`<li>${markdownInline(lines[index].trimEnd().replace(/^\d+\.\s+/, ""), currentPath)}</li>`);
          index += 1;
        }
        blocks.push(`<ol>${items.join("")}</ol>`);
        continue;
      }
      if (/^\|.+\|$/.test(line) && index + 1 < lines.length && /^\|?[\s:-]+\|[\s|:-]+$/.test(lines[index + 1].trim())) {
        flushParagraph(paragraph);
        const headerCells = line.split("|").slice(1, -1).map((cell) => `<th>${markdownInline(cell.trim(), currentPath)}</th>`);
        index += 2;
        const rows = [];
        while (index < lines.length && /^\|.+\|$/.test(lines[index].trim())) {
          const cells = lines[index].split("|").slice(1, -1).map((cell) => `<td>${markdownInline(cell.trim(), currentPath)}</td>`);
          rows.push(`<tr>${cells.join("")}</tr>`);
          index += 1;
        }
        blocks.push(`<table><thead><tr>${headerCells.join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`);
        continue;
      }
      paragraph.push(line.trim());
      index += 1;
    }
    flushParagraph(paragraph);
    return blocks.join("");
  }

  function typesetMath(target) {
    if (!state.preferences.formulaRendering) return;
    if (!target || !window.MathJax || typeof window.MathJax.typesetPromise !== "function") return;
    try {
      if (typeof window.MathJax.typesetClear === "function") {
        window.MathJax.typesetClear([target]);
      }
      window.MathJax.typesetPromise([target]).catch(() => {});
    } catch (_error) {
      // Ignore math render failures and keep plain text fallback visible.
    }
  }

  function settingsField(label, control, hint = "") {
    return `
      <label class="settings-field">
        <span class="settings-label">${escapeHtml(label)}</span>
        ${control}
        ${hint ? `<span class="settings-hint">${escapeHtml(hint)}</span>` : ""}
      </label>
    `;
  }

  function settingsSectionButton(id, label) {
    const active = state.settingsView === id ? "active" : "";
    return `<button class="settings-tab ${active}" type="button" data-settings-section="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
  }

  function preferenceDisplay(key, value) {
    const maps = {
      theme: {
        dark: "暗色",
        light: "亮色",
      },
      uiScale: {
        "95": "紧凑 95%",
        "100": "标准 100%",
        "108": "舒展 108%",
        "116": "大字号 116%",
      },
      readerFontSize: {
        "86": "小",
        "92": "中",
        "100": "大",
        "108": "超大",
      },
      readerLineHeight: {
        "150": "紧",
        "166": "标准",
        "182": "舒展",
      },
      listDensity: {
        compact: "紧凑",
        comfortable: "舒适",
      },
      previewWidth: {
        narrow: "窄栏",
        wide: "宽栏",
        full: "全宽",
      },
      editorFontSize: {
        "78": "小",
        "84": "中",
        "92": "大",
      },
      defaultTerminalMode: {
        shell: "Shell",
        codex: "Codex CLI",
      },
      defaultWorkbenchMode: {
        split: "分栏",
        edit: "仅编辑",
        preview: "仅预览",
      },
    };
    return maps[key] && maps[key][value] ? maps[key][value] : String(value || "");
  }

  function renderWorkbenchSettings() {
    const prefs = state.preferences;
    const sections = {
      appearance: `
        ${settingsField(
          "主题",
          `
            <select class="settings-select" data-setting-key="theme">
              <option value="dark" ${state.layout.theme === "dark" ? "selected" : ""}>暗色</option>
              <option value="light" ${state.layout.theme === "light" ? "selected" : ""}>亮色</option>
            </select>
          `
        )}
        ${settingsField(
          "界面缩放",
          `
            <select class="settings-select" data-setting-key="uiScale">
              <option value="95" ${prefs.uiScale === "95" ? "selected" : ""}>紧凑 95%</option>
              <option value="100" ${prefs.uiScale === "100" ? "selected" : ""}>标准 100%</option>
              <option value="108" ${prefs.uiScale === "108" ? "selected" : ""}>舒展 108%</option>
              <option value="116" ${prefs.uiScale === "116" ? "selected" : ""}>大字号 116%</option>
            </select>
          `
        )}
        ${settingsField(
          "列表密度",
          `
            <select class="settings-select" data-setting-key="listDensity">
              <option value="compact" ${prefs.listDensity === "compact" ? "selected" : ""}>紧凑</option>
              <option value="comfortable" ${prefs.listDensity === "comfortable" ? "selected" : ""}>舒适</option>
            </select>
          `
        )}
        ${settingsField(
          "预览宽度",
          `
            <select class="settings-select" data-setting-key="previewWidth">
              <option value="narrow" ${prefs.previewWidth === "narrow" ? "selected" : ""}>窄栏阅读</option>
              <option value="wide" ${prefs.previewWidth === "wide" ? "selected" : ""}>宽栏阅读</option>
              <option value="full" ${prefs.previewWidth === "full" ? "selected" : ""}>全宽</option>
            </select>
          `
        )}
      `,
      reading: `
        ${settingsField(
          "阅读字号",
          `
            <select class="settings-select" data-setting-key="readerFontSize">
              <option value="86" ${prefs.readerFontSize === "86" ? "selected" : ""}>小</option>
              <option value="92" ${prefs.readerFontSize === "92" ? "selected" : ""}>中</option>
              <option value="100" ${prefs.readerFontSize === "100" ? "selected" : ""}>大</option>
              <option value="108" ${prefs.readerFontSize === "108" ? "selected" : ""}>超大</option>
            </select>
          `
        )}
        ${settingsField(
          "阅读行高",
          `
            <select class="settings-select" data-setting-key="readerLineHeight">
              <option value="150" ${prefs.readerLineHeight === "150" ? "selected" : ""}>紧</option>
              <option value="166" ${prefs.readerLineHeight === "166" ? "selected" : ""}>标准</option>
              <option value="182" ${prefs.readerLineHeight === "182" ? "selected" : ""}>舒展</option>
            </select>
          `
        )}
        ${settingsField(
          "公式渲染",
          `
            <label class="settings-checkbox compact">
              <input type="checkbox" data-setting-key="formulaRendering" ${prefs.formulaRendering ? "checked" : ""} />
              <span>启用 TeX 数学公式</span>
            </label>
          `
        )}
      `,
      workspace: `
        ${settingsField(
          "默认工作台模式",
          `
            <select class="settings-select" data-setting-key="defaultWorkbenchMode">
              <option value="split" ${prefs.defaultWorkbenchMode === "split" ? "selected" : ""}>分栏</option>
              <option value="edit" ${prefs.defaultWorkbenchMode === "edit" ? "selected" : ""}>仅编辑</option>
              <option value="preview" ${prefs.defaultWorkbenchMode === "preview" ? "selected" : ""}>仅预览</option>
            </select>
          `
        )}
        ${settingsField(
          "条目联动",
          `
            <label class="settings-checkbox compact">
              <input type="checkbox" data-setting-key="autoOpenWorkbench" ${prefs.autoOpenWorkbench ? "checked" : ""} />
              <span>选择条目时自动打开文件</span>
            </label>
          `
        )}
      `,
      terminal: `
        ${settingsField(
          "默认终端模式",
          `
            <select class="settings-select" data-setting-key="defaultTerminalMode">
              <option value="shell" ${prefs.defaultTerminalMode === "shell" ? "selected" : ""}>Workspace Shell</option>
              <option value="codex" ${prefs.defaultTerminalMode === "codex" ? "selected" : ""}>Codex CLI</option>
            </select>
          `
        )}
        ${settingsField(
          "终端字号",
          `
            <select class="settings-select" data-setting-key="terminalFontSize">
              <option value="11" ${prefs.terminalFontSize === "11" ? "selected" : ""}>11</option>
              <option value="12" ${prefs.terminalFontSize === "12" ? "selected" : ""}>12</option>
              <option value="13" ${prefs.terminalFontSize === "13" ? "selected" : ""}>13</option>
              <option value="14" ${prefs.terminalFontSize === "14" ? "selected" : ""}>14</option>
              <option value="16" ${prefs.terminalFontSize === "16" ? "selected" : ""}>16</option>
            </select>
          `
        )}
      `,
    };
    return `
      <div class="settings-shell compact">
        <section class="settings-compact-head">
          <h3>工作区设置</h3>
          <div class="settings-toolbar">
            ${settingsSectionButton("appearance", "外观")}
            ${settingsSectionButton("reading", "阅读")}
            ${settingsSectionButton("workspace", "工作台")}
            ${settingsSectionButton("terminal", "终端")}
          </div>
        </section>
        <section class="settings-panel-card">
          <div class="settings-panel-grid">
            ${sections[state.settingsView] || sections.appearance}
          </div>
          <div class="settings-actions inline compact">
            <button class="toolbar-button" type="button" data-settings-action="reset-layout">重置布局尺寸</button>
            <button class="toolbar-button" type="button" data-settings-action="open-current-file">回到当前文件</button>
          </div>
        </section>
      </div>
    `;
  }

  function renderWorkbenchShell(content, currentPath, kind) {
    if (kind === "settings") {
      elements.workbenchBody.className = "workbench-body mode-preview settings-mode";
      elements.workbenchBody.innerHTML = renderWorkbenchSettings();
      return;
    }
    if (!content && !currentPath) {
      elements.workbenchBody.className = "workbench-body empty";
      elements.workbenchBody.innerHTML = '<div class="empty-state">点击 Markdown / YAML / 文本文件后，这里会出现可编辑或可预览的工作台。</div>';
      return;
    }
    const mode = state.workbench.mode || "split";
    const isMarkdown = kind === "markdown";
    const editorDisabled = !state.workbench.writable;
    const previewHtml = isMarkdown
      ? renderMarkdown(content, currentPath)
      : `<pre class="workbench-readonly">${escapeHtml(content || "")}</pre>`;
    const editorPane = `
      <section class="workbench-pane">
        <div class="workbench-pane-head"><span>${editorDisabled ? "只读文本" : "编辑器"}</span></div>
        <textarea id="workbenchEditor" class="workbench-editor" ${editorDisabled ? "readonly" : ""}>${escapeHtml(content || "")}</textarea>
      </section>
    `;
    const previewPane = `
      <section class="workbench-pane">
        <div class="workbench-pane-head"><span>${isMarkdown ? "实时预览" : "文本预览"}</span></div>
        <div id="workbenchPreview" class="markdown-preview">${previewHtml}</div>
      </section>
    `;
    const singlePane = mode === "edit" ? editorPane : previewPane;
    elements.workbenchBody.className = `workbench-body mode-${mode}`;
    elements.workbenchBody.innerHTML = mode === "split" ? `${editorPane}${previewPane}` : singlePane;
  }

  function renderWorkbench() {
    const wb = state.workbench;
    elements.appShell.classList.toggle("workbench-active", !!wb.path || wb.kind === "settings");
    elements.workbenchTitle.textContent = wb.kind === "settings" ? "工作区设置" : wb.path ? basename(wb.path) : "知识工作台";
    elements.workbenchMeta.textContent = "";
    elements.workbenchPath.textContent = wb.kind === "settings" ? "kb://settings" : wb.path || "尚未打开";
    if (wb.kind === "settings") {
      workbenchStatus("本地偏好", "ready");
      renderWorkbenchShell("", "kb://settings", "settings");
    } else if (!wb.path) {
      workbenchStatus("未打开文件");
      renderWorkbenchShell("", "", "");
    } else if (wb.loading) {
      workbenchStatus("读取中", "warn");
      elements.workbenchBody.className = "workbench-body empty";
      elements.workbenchBody.innerHTML = '<div class="empty-state">正在加载文件内容...</div>';
    } else if (wb.lastSaveError) {
      workbenchStatus("保存失败", "failed");
      renderWorkbenchShell(wb.content, wb.path, wb.kind);
    } else if (wb.dirty) {
      workbenchStatus("未保存", "warn");
      renderWorkbenchShell(wb.content, wb.path, wb.kind);
    } else {
      workbenchStatus(wb.writable ? "已同步" : "只读", wb.writable ? "ready" : "");
      renderWorkbenchShell(wb.content, wb.path, wb.kind);
    }
    [elements.workbenchModeSplit, elements.workbenchModeEdit, elements.workbenchModePreview].forEach((button) => {
      if (!button) return;
      button.classList.toggle("active", button.id === `workbenchMode${wb.mode[0].toUpperCase()}${wb.mode.slice(1)}`);
      button.disabled = wb.kind === "settings";
    });
    elements.workbenchBackBtn.disabled = !canGoWorkbenchHistory(-1);
    elements.workbenchForwardBtn.disabled = !canGoWorkbenchHistory(1);
    elements.workbenchOpenExternalBtn.disabled = !wb.href && wb.kind !== "settings";
    document.title = wb.kind === "settings"
      ? "工作区设置 · workspace 研究知识库浏览器"
      : wb.path
        ? `${basename(wb.path)} · workspace 研究知识库浏览器`
        : "workspace 研究知识库浏览器";
    typesetMath(wb.kind === "settings" ? elements.workbenchBody : document.getElementById("workbenchPreview"));
  }

  function updateWorkbenchLive() {
    const wb = state.workbench;
    if (wb.kind === "settings") return;
    workbenchStatus(
      wb.lastSaveError ? "保存失败" : wb.dirty ? "未保存" : wb.writable ? "已同步" : "只读",
      wb.lastSaveError ? "failed" : wb.dirty ? "warn" : wb.writable ? "ready" : ""
    );
    const preview = document.getElementById("workbenchPreview");
    if (preview) {
      preview.innerHTML = wb.kind === "markdown"
        ? renderMarkdown(wb.content, wb.path)
        : `<pre class="workbench-readonly">${escapeHtml(wb.content || "")}</pre>`;
      typesetMath(preview);
    }
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `request failed: ${response.status}`);
    }
    return payload;
  }

  async function refreshSystemTerminalTargets() {
    try {
      const payload = await fetchJson(`${systemTerminalTargetsUrl}?t=${Date.now()}`, { cache: "no-store" });
      state.systemTerminal.targets = Array.isArray(payload.targets) ? payload.targets : [];
    } catch (_error) {
      state.systemTerminal.targets = [];
    }
    renderTerminal();
  }

  function initTerminalResizer() {
    const handle = elements.terminalResizer;
    if (!handle) return;
    let dragging = false;
    let startY = 0;
    let startHeight = 260;

    function stopDrag() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", stopDrag);
    }

    function onMove(event) {
      if (!dragging) return;
      const delta = startY - event.clientY;
      const height = Math.min(620, Math.max(180, startHeight + delta));
      document.documentElement.style.setProperty("--panel-height", `${height}px`);
      saveTerminalHeight(height);
      state.terminal.needsFit = true;
      renderLayout();
      renderTerminal();
    }

    handle.addEventListener("mousedown", (event) => {
      if (window.innerWidth <= 1020 || state.terminal.collapsed) return;
      dragging = true;
      startY = event.clientY;
      startHeight = cssNumber("--panel-height", 260);
      handle.classList.add("dragging");
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", stopDrag);
    });
  }

  function initListResizer() {
    const handle = elements.listResizer;
    if (!handle) return;
    let dragging = false;
    let startX = 0;
    let startWidth = 248;

    function stopDrag() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", stopDrag);
    }

    function onMove(event) {
      if (!dragging) return;
      const delta = event.clientX - startX;
      const width = Math.min(520, Math.max(220, startWidth + delta));
      document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
      saveSidebarWidth(width);
      renderLayout();
    }

    handle.addEventListener("mousedown", (event) => {
      if (window.innerWidth <= 1020 || state.layout.sidebarCollapsed) return;
      dragging = true;
      startX = event.clientX;
      startWidth = cssNumber("--sidebar-width", 320);
      handle.classList.add("dragging");
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", stopDrag);
    });
  }

  function initDetailResizer() {
    const handle = elements.detailResizer;
    if (!handle) return;
    let dragging = false;
    let startX = 0;
    let startWidth = 360;

    function stopDrag() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", stopDrag);
    }

    function onMove(event) {
      if (!dragging) return;
      const delta = startX - event.clientX;
      const width = Math.min(520, Math.max(260, startWidth + delta));
      document.documentElement.style.setProperty("--detail-width", `${width}px`);
      saveDetailWidth(width);
      renderLayout();
    }

    handle.addEventListener("mousedown", (event) => {
      if (window.innerWidth <= 1020 || state.layout.detailCollapsed) return;
      dragging = true;
      startX = event.clientX;
      startWidth = cssNumber("--detail-width", 360);
      handle.classList.add("dragging");
      document.body.style.userSelect = "none";
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", stopDrag);
    });
  }

  async function openWorkbenchFile(path, options = {}) {
    const relPath = normalizeInternalPath(path);
    if (!relPath || !isTextPath(relPath)) return;
    if (!options.force && state.workbench.path === relPath && !options.reload) return;
    if (state.workbench.dirty && state.workbench.writable && state.workbench.path && state.workbench.path !== relPath) {
      await saveWorkbenchFile();
      if (state.workbench.lastSaveError) {
        renderWorkbench();
        return;
      }
    }
    const shouldRecordHistory = options.recordHistory !== false && !options.reload;
    state.workbench.loading = true;
    state.workbench.lastSaveError = "";
    state.workbench.kind = "";
    state.workbench.path = relPath;
    state.workbench.href = currentKbUrl({ path: relPath });
    renderWorkbench();
    try {
      const payload = await fetchJson(`${fileApiUrl}?path=${encodeURIComponent(relPath)}&t=${Date.now()}`, { cache: "no-store" });
      state.workbench.path = payload.path || relPath;
      state.workbench.href = currentKbUrl({ path: state.workbench.path });
      state.workbench.kind = payload.kind || (isMarkdownPath(relPath) ? "markdown" : "text");
      state.workbench.content = payload.content || "";
      state.workbench.savedContent = payload.content || "";
      state.workbench.updatedAt = payload.updated_at || "";
      state.workbench.writable = !!payload.writable;
      state.workbench.dirty = false;
      state.workbench.loading = false;
      state.workbench.lastSaveError = "";
      if (shouldRecordHistory) {
        rememberWorkbenchHistory(state.workbench.path);
      }
      syncWorkbenchUrl();
      renderWorkbench();
    } catch (error) {
      state.workbench.loading = false;
      state.workbench.lastSaveError = error instanceof Error ? error.message : String(error);
      renderWorkbench();
    }
  }

  function openWorkbenchSettings() {
    state.workbench.kind = "settings";
    state.workbench.path = "";
    state.workbench.href = currentKbUrl({ settings: "1" });
    state.workbench.loading = false;
    state.workbench.dirty = false;
    state.workbench.lastSaveError = "";
    state.workbench.writable = false;
    renderWorkbench();
    syncWorkbenchUrl();
  }

  let autoSaveTimer = null;

  async function saveWorkbenchFile() {
    const wb = state.workbench;
    if (!wb.path || !wb.writable) return;
    try {
      const payload = await fetchJson(fileApiUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: wb.path,
          content: wb.content,
        }),
      });
      wb.content = payload.content || wb.content;
      wb.savedContent = wb.content;
      wb.updatedAt = payload.updated_at || "";
      wb.dirty = false;
      wb.lastSaveError = "";
      renderWorkbench();
      refresh(false);
    } catch (error) {
      wb.lastSaveError = error instanceof Error ? error.message : String(error);
      renderWorkbench();
    }
  }

  function scheduleWorkbenchSave() {
    if (!state.workbench.autoSave || !state.workbench.writable) return;
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
      saveWorkbenchFile();
    }, 900);
  }

  function preferredWorkbenchPathForSelection() {
    if (state.tab === "literature") {
      const item = filteredLiterature().find((entry) => entry.source_id === state.selected.literature);
      return item && item.links && item.links.note && item.links.note.path;
    }
    if (state.tab === "repos") {
      const item = filteredRepos().find((entry) => entry.repo_id === state.selected.repos);
      return item && item.links && item.links.notes && item.links.notes.path;
    }
    if (state.tab === "landscapes") {
      const item = filteredLandscapes().find((entry) => entry.survey_id === state.selected.landscapes);
      return item && item.links && item.links.summary && item.links.summary.path;
    }
    if (state.tab === "wiki") {
      const item = filteredWiki().find((entry) => entry.wiki_id === state.selected.wiki);
      return item && item.query_path;
    }
    if (state.tab === "programs") {
      const item = filteredPrograms().find((entry) => entry.program_id === state.selected.programs);
      return item && item.links && (item.links.design_doc && item.links.design_doc.path || item.links.runbook && item.links.runbook.path);
    }
    return "";
  }

  function stripAnsi(text) {
    return String(text || "")
      .replace(/\u001b\][^\u0007\u001b]*(?:\u0007|\u001b\\)/g, "")
      .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "")
      .replace(/\u001b[@-_]/g, "")
      .replace(/\u0008/g, "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n");
  }

  function collapseSingleCharTerminalLines(text) {
    const lines = stripAnsi(text).split("\n");
    const output = [];
    let buffer = "";
    lines.forEach((line) => {
      const compact = line.trim();
      if (!compact) {
        return;
      }
      if (compact.length === 1) {
        buffer += compact;
        return;
      }
      if (buffer) {
        output.push(buffer);
        buffer = "";
      }
      output.push(line);
    });
    if (buffer) output.push(buffer);
    return output.join("\n");
  }

  function renderTerminal() {
    const terminal = state.terminal;
    renderLayout();
    const xtermReady = ensureTerminalEmulator();
    elements.terminalStatus.textContent =
      terminal.status === "running" ? (terminal.mode === "codex" ? "Codex CLI" : "Workspace Shell") :
      terminal.status === "starting" ? "启动中" :
      terminal.status === "exited" ? "已退出" : "连接失败";
    elements.terminalStatus.className = `status-pill ${terminal.status === "running" ? "ready" : terminal.status === "starting" ? "warn" : terminal.status === "failed" ? "failed" : ""}`.trim();
    elements.terminalHint.textContent = terminal.lastError
      ? `最近错误：${terminal.lastError}`
      : (terminal.mode === "codex"
          ? "Codex CLI 在内嵌终端中会比 Shell 更重；若感觉卡顿，优先切回 Shell 或直接用系统终端。"
          : "当前默认使用更轻的 workspace shell，减小卡顿；需要时再手动切到 Codex CLI。");
    elements.terminalHint.parentElement.style.display = terminal.lastError ? "grid" : "none";
    elements.terminalTitle.textContent = terminal.mode === "codex" ? "底部 Panel · Codex CLI" : "底部 Panel · Workspace Shell";
    elements.terminalMeta.textContent = "";
    elements.terminalCodexBtn.classList.toggle("active", terminal.mode === "codex");
    elements.terminalShellBtn.classList.toggle("active", terminal.mode === "shell");
    const showFallbackEntry = !xtermReady;
    elements.terminalEntry.classList.toggle("hidden", !showFallbackEntry);
    elements.terminalFoot.classList.toggle("hidden", xtermReady && !terminal.lastError);
    elements.terminalLineInput.disabled = terminal.status === "failed";
    elements.terminalSendBtn.disabled = terminal.status === "failed";
    elements.terminalCtrlCBtn.disabled = !state.terminal.sessionId;
    elements.terminalLineInput.placeholder = terminal.mode === "codex"
      ? "xterm 不可用时，才使用这一行发送命令"
      : "xterm 不可用时，才使用这一行发送到 shell";
    if (!xtermReady) {
      elements.terminalScreen.innerHTML = `<span>${escapeHtml(collapseSingleCharTerminalLines(terminal.buffer) || "终端尚无输出。")}</span>`;
    }
    if (!terminal.collapsed) {
      if (!xtermReady) {
        elements.terminalViewport.scrollTop = elements.terminalViewport.scrollHeight;
      }
      if (state.terminal.needsFit) fitTerminal();
    }
  }

  async function openTerminal(mode, force) {
    try {
      const payload = await fetchJson(terminalOpenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, force: !!force }),
      });
      state.terminal.sessionId = payload.session_id || "";
      state.terminal.mode = payload.mode || mode || "shell";
      state.terminal.status = payload.status || "starting";
      state.terminal.cursor = 0;
      state.terminal.buffer = "";
      state.terminal.lastError = payload.last_error || "";
      state.terminal.needsFit = true;
      if (ensureTerminalEmulator() && terminalRuntime.xterm) {
        terminalRuntime.xterm.reset();
      }
      renderTerminal();
      pollTerminal(true);
    } catch (error) {
      state.terminal.status = "failed";
      state.terminal.lastError = error instanceof Error ? error.message : String(error);
      renderTerminal();
    }
  }

  async function pollTerminal(force) {
    if (!state.terminal.sessionId || (state.terminal.polling && !force)) return;
    state.terminal.polling = true;
    try {
      const payload = await fetchJson(`${terminalPollUrl}?session_id=${encodeURIComponent(state.terminal.sessionId)}&cursor=${encodeURIComponent(state.terminal.cursor)}`, {
        cache: "no-store",
      });
      state.terminal.status = payload.status || state.terminal.status;
      state.terminal.mode = payload.mode || state.terminal.mode;
      state.terminal.lastError = payload.last_error || "";
      if (payload.reset) {
        state.terminal.buffer = payload.data || "";
      } else if (payload.data) {
        state.terminal.buffer += payload.data;
      }
      state.terminal.cursor = Number(payload.cursor || state.terminal.cursor || 0);
      if (state.terminal.buffer.length > 160000) {
        state.terminal.buffer = state.terminal.buffer.slice(-120000);
      }
      if (ensureTerminalEmulator() && terminalRuntime.xterm) {
        if (payload.reset) {
          terminalRuntime.xterm.reset();
          if (payload.data) terminalRuntime.xterm.write(payload.data);
        } else if (payload.data) {
          terminalRuntime.xterm.write(payload.data);
        }
      }
      renderTerminal();
    } catch (error) {
      state.terminal.status = "failed";
      state.terminal.lastError = error instanceof Error ? error.message : String(error);
      renderTerminal();
    } finally {
      state.terminal.polling = false;
    }
  }

  async function sendTerminalInput(data) {
    if (!state.terminal.sessionId || !data) return;
    try {
      await fetchJson(terminalInputUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.terminal.sessionId,
          data,
        }),
      });
      pollTerminal(true);
    } catch (error) {
      state.terminal.status = "failed";
      state.terminal.lastError = error instanceof Error ? error.message : String(error);
      renderTerminal();
    }
  }

  function sendTerminalLine() {
    const value = elements.terminalLineInput.value || "";
    if (!value.trim()) return;
    elements.terminalLineInput.value = "";
    sendTerminalInput(`${value}\r`);
  }

  function renderAll() {
    hideTooltip();
    renderTabNav();
    renderFilterBar();
    renderSearchSection();
    renderQuickOpenBar();
    const items = renderList();
    renderDetail(items);
    renderWorkbench();
    renderLayout();
    renderTerminal();
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
    elements.refreshNowBtn.classList.remove("sync-ready", "sync-failed", "sync-loading", "sync-stale", "sync-missing");
    elements.refreshNowBtn.classList.add(
      raw === "ready" ? "sync-ready" :
      raw === "failed" ? "sync-failed" :
      raw === "stale" ? "sync-stale" :
      raw === "missing" ? "sync-missing" : "sync-loading"
    );
    if (state.live.lastError) {
      elements.updatedAt.textContent = "错误";
      elements.updatedAt.setAttribute("data-tip", `最近错误：${state.live.lastError}`);
      elements.refreshNowBtn.setAttribute("data-tip", `同步失败 · ${state.live.lastError}`);
      return;
    }
    elements.updatedAt.textContent = fmtShortTime(state.live.generatedAt);
    const detail = `状态：${textMap[raw] || raw} · 更新于 ${fmtTime(state.live.generatedAt)}`;
    elements.updatedAt.setAttribute("data-tip", detail);
    elements.refreshNowBtn.setAttribute("data-tip", `立即刷新快照\n${detail}`);
  }

  function consumeLaunchState() {
    if (state.launch.consumed) return;
    if (state.launch.settings) {
      state.launch.consumed = true;
      openWorkbenchSettings();
      return;
    }
    if (state.launch.path && isTextPath(state.launch.path)) {
      state.launch.consumed = true;
      openWorkbenchFile(state.launch.path, { force: true });
    }
  }

  function applySnapshot(snapshot, live) {
    state.snapshot = snapshot;
    state.version = String((live && live.snapshot_version) || snapshot.snapshot_version || "");
    state.live.buildStatus = String((live && live.build_status) || "ready");
    state.live.generatedAt = String((live && live.generated_at) || snapshot.generated_at || "");
    state.live.lastError = String((live && live.last_error) || "");
    updateStatusPill();
    renderAll();
    consumeLaunchState();
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
        if (state.workbench.path && !state.workbench.dirty) {
          openWorkbenchFile(state.workbench.path, { reload: true });
        }
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
    const button = event.target.closest("button");
    const link = event.target.closest("a[data-open-path]");
    if (link && !(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)) {
      event.preventDefault();
      const path = link.getAttribute("data-open-path") || "";
      if (path) {
        openWorkbenchFile(path, { force: true });
      }
      return;
    }

    if (button === elements.refreshNowBtn) {
      refresh(true);
      return;
    }

    if (button === elements.sidebarToggleBtn) {
      applyTheme(state.layout.theme === "light" ? "dark" : "light");
      renderWorkbench();
      renderTerminal();
      return;
    }

    if (button === elements.activitySearchBtn || button === elements.searchSectionToggleBtn) {
      state.layout.searchMode = false;
      setSearchExpanded(!state.layout.searchExpanded);
      if (state.layout.sidebarCollapsed) {
        setSidebarCollapsed(false);
      }
      renderAll();
      if (state.layout.searchExpanded) {
        window.requestAnimationFrame(() => {
          elements.search.focus();
          elements.search.select();
        });
      }
      return;
    }

    if (button === elements.sidebarCollapseBtn) {
      setSidebarCollapsed(!state.layout.sidebarCollapsed);
      renderAll();
      return;
    }

    if (button === elements.detailToggleBtn || button === elements.detailCollapseBtn) {
      setDetailCollapsed(!state.layout.detailCollapsed);
      renderLayout();
      return;
    }

    if (button === elements.detailCollapsedHandle) {
      setDetailCollapsed(false);
      renderLayout();
      return;
    }

    if (button === elements.workbenchModeSplit) {
      state.workbench.mode = "split";
      renderWorkbench();
      return;
    }
    if (button === elements.workbenchModeEdit) {
      state.workbench.mode = "edit";
      renderWorkbench();
      return;
    }
    if (button === elements.workbenchModePreview) {
      state.workbench.mode = "preview";
      renderWorkbench();
      return;
    }

    if (button === elements.workbenchBackBtn) {
      goWorkbenchHistory(-1);
      return;
    }

    if (button === elements.workbenchForwardBtn) {
      goWorkbenchHistory(1);
      return;
    }
    if (button === elements.workbenchOpenExternalBtn) {
      const externalUrl = state.workbench.kind === "settings"
        ? currentKbUrl({ settings: "1" })
        : (state.workbench.path ? currentKbUrl({ path: state.workbench.path }) : "");
      if (externalUrl) window.open(externalUrl, "_blank", "noopener,noreferrer");
      return;
    }

    if (button === elements.settingsBtn) {
      openWorkbenchSettings();
      return;
    }

    const settingsSectionButton = event.target.closest("[data-settings-section]");
    if (settingsSectionButton) {
      state.settingsView = settingsSectionButton.getAttribute("data-settings-section") || "appearance";
      renderWorkbench();
      return;
    }

    if (button === elements.terminalToggleBtn || button === elements.terminalCollapseBtn) {
      if (state.terminal.collapsed) state.terminal.needsFit = true;
      setTerminalCollapsed(!state.terminal.collapsed);
      renderTerminal();
      return;
    }
    if (button === elements.terminalCollapsedHandle) {
      setTerminalCollapsed(false);
      state.terminal.needsFit = true;
      renderTerminal();
      return;
    }
    if (button === elements.terminalCodexBtn) {
      setTerminalCollapsed(false);
      openTerminal("codex", false);
      return;
    }
    if (button === elements.terminalShellBtn) {
      setTerminalCollapsed(false);
      openTerminal("shell", false);
      return;
    }
    const terminalTargetButton = event.target.closest("[data-terminal-target]");
    if (terminalTargetButton) {
      const target = terminalTargetButton.getAttribute("data-terminal-target") || "terminal";
      fetchJson(systemTerminalOpenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: state.terminal.mode || "codex", target }),
      }).catch((error) => {
        state.terminal.lastError = error instanceof Error ? error.message : String(error);
        renderTerminal();
      });
      return;
    }
    if (button === elements.terminalSendBtn) {
      sendTerminalLine();
      return;
    }
    if (button === elements.terminalCtrlCBtn) {
      sendTerminalInput("\u0003");
      return;
    }

    const settingsActionButton = event.target.closest("[data-settings-action]");
    if (settingsActionButton) {
      const action = settingsActionButton.getAttribute("data-settings-action") || "";
      if (action === "reset-layout") {
        resetLayoutPreferences();
        return;
      }
      if (action === "open-current-file") {
        if (state.workbench.history.length) {
          const latestFile = state.workbench.history[state.workbench.history.length - 1];
          if (latestFile) {
            openWorkbenchFile(latestFile, { force: true, recordHistory: false });
            return;
          }
        }
        renderWorkbench();
        return;
      }
    }

    const tabButton = event.target.closest("[data-tab]");
    if (tabButton) {
      const nextTab = tabButton.getAttribute("data-tab") || "overview";
      setSearchExpanded(false);
      if (state.tab === nextTab) {
        if (state.layout.sidebarCollapsed) {
          setSidebarCollapsed(false);
          renderAll();
        } else {
          setSidebarCollapsed(true);
          renderAll();
        }
        return;
      }
      state.tab = nextTab;
      state.layout.searchMode = false;
      setSidebarCollapsed(false);
      renderAll();
      return;
    }

    const listCard = event.target.closest("[data-kind][data-id]");
    if (listCard) {
      const kind = listCard.getAttribute("data-kind");
      const id = listCard.getAttribute("data-id");
      if (state.layout.searchMode && kind === "search" && id) {
        const hit = searchResults().find((item) => item.search_id === id);
        if (hit) {
          state.tab = hit.search_tab;
          state.layout.searchMode = false;
          setSidebarCollapsed(false);
          state.selected[hit.search_tab] = hit.target_id;
          renderAll();
          const preferredPath = hit.open_path || preferredWorkbenchPathForSelection();
          if (state.preferences.autoOpenWorkbench && preferredPath && (!state.workbench.dirty || state.workbench.path === preferredPath)) {
            openWorkbenchFile(preferredPath, { force: true });
          }
        }
        return;
      }
      if (kind && id && state.selected[kind] !== undefined) {
        const sameCard = state.selected[kind] === id;
        state.selected[kind] = id;
        state.expanded[kind] = sameCard && state.expanded[kind] === id ? "" : id;
        if (kind === "overview") {
          const item = (overviewItems() || []).find((entry) => entry.overview_id === id);
          if (item && item.kind === "jump" && item.jump_tab) {
            state.tab = item.jump_tab;
          }
        }
        renderAll();
        const preferredPath = preferredWorkbenchPathForSelection();
        if (state.preferences.autoOpenWorkbench && preferredPath && (!state.workbench.dirty || state.workbench.path === preferredPath)) {
          openWorkbenchFile(preferredPath, { force: true });
        }
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
      return;
    }
    const settingKey = event.target && event.target.getAttribute ? event.target.getAttribute("data-setting-key") : "";
    if (settingKey) {
      if (settingKey === "autoOpenWorkbench") {
        state.preferences.autoOpenWorkbench = !!event.target.checked;
        saveBooleanPreference(storage.autoOpenWorkbench, state.preferences.autoOpenWorkbench);
      }
      return;
    }
    if (event.target && event.target.id === "workbenchEditor") {
      state.workbench.content = event.target.value || "";
      state.workbench.dirty = state.workbench.content !== state.workbench.savedContent;
      state.workbench.lastSaveError = "";
      updateWorkbenchLive();
      scheduleWorkbenchSave();
    }
  }

  function onTerminalLineKeyDown(event) {
    if (event.target !== elements.terminalLineInput) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendTerminalLine();
    }
  }

  function onChange(event) {
    const settingKey = event.target && event.target.getAttribute ? event.target.getAttribute("data-setting-key") : "";
    if (settingKey) {
      const value = event.target.type === "checkbox" ? (event.target.checked ? "1" : "0") : (event.target.value || "");
      if (settingKey === "theme") {
        applyTheme(value);
      } else if (settingKey === "uiScale") {
        state.preferences.uiScale = value;
        saveStringPreference(storage.uiScale, value);
      } else if (settingKey === "readerFontSize") {
        state.preferences.readerFontSize = value;
        saveStringPreference(storage.readerFontSize, value);
      } else if (settingKey === "readerLineHeight") {
        state.preferences.readerLineHeight = value;
        saveStringPreference(storage.readerLineHeight, value);
      } else if (settingKey === "editorFontSize") {
        state.preferences.editorFontSize = value;
        saveStringPreference(storage.editorFontSize, value);
      } else if (settingKey === "terminalFontSize") {
        state.preferences.terminalFontSize = value;
        saveStringPreference(storage.terminalFontSize, value);
      } else if (settingKey === "listDensity") {
        state.preferences.listDensity = value;
        saveStringPreference(storage.listDensity, value);
      } else if (settingKey === "previewWidth") {
        state.preferences.previewWidth = value;
        saveStringPreference(storage.previewWidth, value);
      } else if (settingKey === "formulaRendering") {
        state.preferences.formulaRendering = event.target.checked;
        saveBooleanPreference(storage.formulaRendering, state.preferences.formulaRendering);
      } else if (settingKey === "defaultTerminalMode") {
        state.preferences.defaultTerminalMode = value;
        saveStringPreference(storage.defaultTerminalMode, value);
      } else if (settingKey === "defaultWorkbenchMode") {
        state.preferences.defaultWorkbenchMode = value;
        state.workbench.mode = value;
        saveStringPreference(storage.defaultWorkbenchMode, value);
      } else if (settingKey === "autoOpenWorkbench") {
        state.preferences.autoOpenWorkbench = event.target.checked;
        saveBooleanPreference(storage.autoOpenWorkbench, state.preferences.autoOpenWorkbench);
      }
      applyPreferences();
      if (state.workbench.kind === "settings") {
        renderWorkbench();
      } else {
        renderAll();
      }
      return;
    }
    const key = event.target.getAttribute("data-filter-key");
    if (key && state.filters[key] !== undefined) {
      state.filters[key] = event.target.value || "all";
      renderAll();
    }
  }

  function terminalSequenceForKey(event) {
    if (event.key === "Enter") return "\r";
    if (event.key === "Backspace") return "\u007f";
    if (event.key === "Tab") return "\t";
    if (event.key === "ArrowUp") return "\u001b[A";
    if (event.key === "ArrowDown") return "\u001b[B";
    if (event.key === "ArrowRight") return "\u001b[C";
    if (event.key === "ArrowLeft") return "\u001b[D";
    if (event.key === "Escape") return "\u001b";
    if (event.ctrlKey && event.key.toLowerCase() === "c") return "\u0003";
    if (event.ctrlKey && event.key.toLowerCase() === "d") return "\u0004";
    if (event.key.length === 1 && !event.metaKey && !event.ctrlKey) return event.key;
    return "";
  }

  function onTerminalKeyDown(event) {
    if (document.activeElement !== elements.terminalInputSink) return;
    const sequence = terminalSequenceForKey(event);
    if (!sequence) return;
    event.preventDefault();
    sendTerminalInput(sequence);
  }

  function onTerminalPaste(event) {
    const text = event.clipboardData ? event.clipboardData.getData("text/plain") : "";
    if (!text) return;
    event.preventDefault();
    sendTerminalInput(text);
  }

  function tooltipTarget(target) {
    return target instanceof Element ? target.closest("[data-tip]") : null;
  }

  function onPointerOver(event) {
    const target = tooltipTarget(event.target);
    if (!target) return;
    const related = tooltipTarget(event.relatedTarget);
    if (target === related) return;
    showTooltip(target);
  }

  function onPointerOut(event) {
    const target = tooltipTarget(event.target);
    if (!target) return;
    const related = tooltipTarget(event.relatedTarget);
    if (target === related) return;
    if (tooltipRuntime.anchor === target) hideTooltip();
  }

  function onFocusIn(event) {
    const target = tooltipTarget(event.target);
    if (target) showTooltip(target);
  }

  function onFocusOut(event) {
    const target = tooltipTarget(event.target);
    if (target && tooltipRuntime.anchor === target) hideTooltip();
  }

  document.addEventListener("click", onClick);
  document.addEventListener("change", onChange);
  document.addEventListener("mouseover", onPointerOver);
  document.addEventListener("mouseout", onPointerOut);
  document.addEventListener("focusin", onFocusIn);
  document.addEventListener("focusout", onFocusOut);
  document.addEventListener("kb-mathjax-ready", () => {
    typesetMath(document.getElementById("workbenchPreview"));
    typesetMath(elements.detailBody);
  });
  elements.search.addEventListener("input", onInput);
  document.addEventListener("input", onInput);
  elements.terminalViewport.addEventListener("click", () => {
    if (terminalRuntime.ready && terminalRuntime.xterm) {
      terminalRuntime.xterm.focus();
    } else {
      elements.terminalInputSink.focus();
    }
  });
  elements.terminalViewport.addEventListener("focus", () => {
    if (terminalRuntime.ready && terminalRuntime.xterm) {
      terminalRuntime.xterm.focus();
    } else {
      elements.terminalInputSink.focus();
    }
  });
  elements.terminalInputSink.addEventListener("keydown", onTerminalKeyDown);
  elements.terminalInputSink.addEventListener("paste", onTerminalPaste);
  elements.terminalLineInput.addEventListener("keydown", onTerminalLineKeyDown);
  window.addEventListener("resize", () => {
    renderLayout();
    positionTooltip();
    state.terminal.needsFit = true;
    fitTerminal();
  });
  window.addEventListener("scroll", hideTooltip, true);
  state.launch = parseLaunchState();
  state.layout.sidebarCollapsed = loadBooleanPreference(storage.sidebarCollapsed, false);
  state.layout.detailCollapsed = loadBooleanPreference(storage.detailCollapsed, false);
  state.terminal.collapsed = loadBooleanPreference(storage.terminalCollapsed, false);
  state.layout.theme = loadTheme();
  loadPreferences();
  loadSidebarWidth();
  loadDetailWidth();
  loadTerminalHeight();
  initListResizer();
  initDetailResizer();
  initTerminalResizer();
  applyTheme(state.layout.theme);
  applyPreferences();
  renderLayout();

  refresh(true);
  refreshSystemTerminalTargets();
  setInterval(() => refresh(false), pollMs);
  openTerminal(state.preferences.defaultTerminalMode || "shell", false);
  setInterval(() => pollTerminal(false), 650);
})();
