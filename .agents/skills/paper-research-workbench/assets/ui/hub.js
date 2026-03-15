(function () {
  const appDataElement = document.getElementById("app-data");
  if (!appDataElement) {
    return;
  }

  const data = JSON.parse(appDataElement.textContent || "{}");
  const THEME_KEY = "paper-research-workbench-theme-v2";
  const HEARTBEAT_INTERVAL_MS = 25000;

  const state = {
    query: "",
    topic: "",
    selectedTopic: data.topics?.[0]?.topic || "",
    selectedPaperId: data.papers?.[0]?.paper_id || null,
    activeTab: document.body.dataset.defaultTab || "overview",
    graphMinScore: 3,
    showAllLabels: false,
    hoveredPaperId: null,
    theme: "light",
  };

  const paperMap = new Map((data.papers || []).map((paper) => [paper.paper_id, paper]));
  const topicMap = new Map((data.topics || []).map((topic) => [topic.topic, topic]));

  const searchInput = document.getElementById("searchInput");
  const chipbar = document.getElementById("chipbar");
  const paperList = document.getElementById("paperList");
  const generatedAt = document.getElementById("generatedAt");
  const paperCount = document.getElementById("paperCount");
  const edgeCount = document.getElementById("edgeCount");
  const topicCount = document.getElementById("topicCount");
  const ideaCount = document.getElementById("ideaCount");
  const overviewHero = document.getElementById("overviewHero");
  const overviewRoutes = document.getElementById("overviewRoutes");
  const overviewPapers = document.getElementById("overviewPapers");
  const overviewSelection = document.getElementById("overviewSelection");
  const topicList = document.getElementById("topicList");
  const topicDetail = document.getElementById("topicDetail");
  const topicDetailBadge = document.getElementById("topicDetailBadge");
  const topicOpenSelected = document.getElementById("topicOpenSelected");
  const ideaSummary = document.getElementById("ideaSummary");
  const ideaList = document.getElementById("ideaList");
  const detailPanel = document.getElementById("detailPanel");
  const graphDetail = document.getElementById("graphDetail");
  const graphCanvas = document.getElementById("graphCanvas");
  const graphStatus = document.getElementById("graphStatus");
  const edgeThresholdInput = document.getElementById("edgeThreshold");
  const edgeThresholdValue = document.getElementById("edgeThresholdValue");
  const toggleLabelsButton = document.getElementById("toggleLabels");
  const resetViewButton = document.getElementById("resetView");
  const themeToggle = document.getElementById("themeToggle");
  const quickActionsPaper = document.getElementById("quickActionsPaper");
  const quickViewNote = document.getElementById("quickViewNote");
  const quickEditNote = document.getElementById("quickEditNote");
  const quickViewIdeas = document.getElementById("quickViewIdeas");
  const quickEditIdeas = document.getElementById("quickEditIdeas");
  const quickViewFeasibility = document.getElementById("quickViewFeasibility");
  const quickEditFeasibility = document.getElementById("quickEditFeasibility");
  const quickOpenPdf = document.getElementById("quickOpenPdf");
  const mdEditorOverlay = document.getElementById("mdEditorOverlay");
  const mdEditorTitle = document.getElementById("mdEditorTitle");
  const mdEditorPath = document.getElementById("mdEditorPath");
  const mdEditorStatus = document.getElementById("mdEditorStatus");
  const mdEditorInput = document.getElementById("mdEditorInput");
  const mdEditorPreview = document.getElementById("mdEditorPreview");
  const mdEditorSave = document.getElementById("mdEditorSave");
  const mdEditorClose = document.getElementById("mdEditorClose");
  const mdEditorSwitchMode = document.getElementById("mdEditorSwitchMode");
  const tabs = Array.from(document.querySelectorAll(".tab"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  const ctx = graphCanvas?.getContext("2d");

  if (!graphCanvas || !ctx) {
    return;
  }

  const viewport = {
    width: Number(graphCanvas.getAttribute("width")) || 1280,
    height: Number(graphCanvas.getAttribute("height")) || 780,
    dpr: Math.max(1, window.devicePixelRatio || 1),
    scale: 1,
    panX: 0,
    panY: 0,
    minScale: 0.45,
    maxScale: 2.8,
  };

  const interaction = {
    mode: "none",
    pointerId: null,
    node: null,
    moved: false,
    startScreenX: 0,
    startScreenY: 0,
    startPanX: 0,
    startPanY: 0,
    offsetX: 0,
    offsetY: 0,
    targetX: 0,
    targetY: 0,
  };

  const motion = {
    rafId: null,
    lastTs: 0,
    settleFrames: 0,
    isAnimating: false,
  };
  const lifecycle = {
    heartbeatTimerId: null,
    lastHeartbeatAt: 0,
  };
  const editor = {
    open: false,
    loading: false,
    saving: false,
    dirty: false,
    mode: "edit",
    path: "",
    title: "",
    content: "",
  };

  let graphNodes = [];
  let graphEdges = [];
  let scoreRange = { min: 3, max: 3 };

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function shortLabel(text, maxLen) {
    const value = String(text || "");
    if (value.length <= maxLen) {
      return value;
    }
    return `${value.slice(0, maxLen - 1)}…`;
  }

  function compactText(text, maxLen) {
    const value = String(text || "").replace(/\s+/g, " ").trim();
    if (value.length <= maxLen) {
      return value;
    }
    return `${value.slice(0, maxLen - 1)}…`;
  }

  function hashText(value) {
    let hash = 2166136261;
    const input = String(value || "");
    for (let index = 0; index < input.length; index += 1) {
      hash ^= input.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function unitNoise(value, salt) {
    const seed = hashText(`${value}:${salt}`);
    return (seed % 100000) / 100000;
  }

  function readThemeVar(name, fallback) {
    const style = getComputedStyle(document.body);
    const value = style.getPropertyValue(name).trim();
    return value || fallback;
  }

  function initTheme() {
    let preferred = "light";
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved === "light" || saved === "dark") {
        preferred = saved;
      } else if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
        preferred = "dark";
      }
    } catch (error) {}
    applyTheme(preferred, false);
  }

  function applyTheme(theme, persist = true) {
    state.theme = theme === "dark" ? "dark" : "light";
    document.body.dataset.theme = state.theme;
    if (themeToggle) {
      themeToggle.setAttribute("aria-label", state.theme === "dark" ? "切换浅色" : "切换深色");
      themeToggle.setAttribute("title", state.theme === "dark" ? "切换浅色" : "切换深色");
    }
    if (persist) {
      try {
        localStorage.setItem(THEME_KEY, state.theme);
      } catch (error) {}
    }
    drawGraph();
  }

  function canUseMarkdownApi() {
    return window.location.protocol === "http:" || window.location.protocol === "https:";
  }

  async function sendHubHeartbeat(reason = "interval") {
    if (!canUseMarkdownApi()) {
      return;
    }
    try {
      await fetch("/api/healthz", {
        method: "GET",
        cache: "no-store",
        keepalive: reason === "visibility" || reason === "focus",
      });
      lifecycle.lastHeartbeatAt = Date.now();
    } catch (error) {}
  }

  function startHubHeartbeat() {
    if (!canUseMarkdownApi() || lifecycle.heartbeatTimerId !== null) {
      return;
    }
    sendHubHeartbeat("startup");
    lifecycle.heartbeatTimerId = window.setInterval(() => {
      sendHubHeartbeat("interval");
    }, HEARTBEAT_INTERVAL_MS);
  }

  function stopHubHeartbeat() {
    if (lifecycle.heartbeatTimerId === null) {
      return;
    }
    window.clearInterval(lifecycle.heartbeatTimerId);
    lifecycle.heartbeatTimerId = null;
  }

  function toProjectMarkdownPath(path) {
    const value = String(path || "").trim().replace(/^\.?\//, "");
    if (!value) {
      return "";
    }
    if (value.startsWith("doc/")) {
      return value;
    }
    return `doc/papers/user/${value}`.replace(/\/+/g, "/");
  }

  function inlineMarkdown(text) {
    return text
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function markdownToHtml(text) {
    const escaped = escapeHtml(text || "");
    const codeBlocks = [];
    let working = escaped.replace(/```([\s\S]*?)```/g, (_, block) => {
      const token = `@@CODE_${codeBlocks.length}@@`;
      codeBlocks.push(`<pre><code>${block}</code></pre>`);
      return token;
    });

    const lines = working.split(/\r?\n/);
    const html = [];
    let inUl = false;
    let inOl = false;

    function closeLists() {
      if (inUl) {
        html.push("</ul>");
        inUl = false;
      }
      if (inOl) {
        html.push("</ol>");
        inOl = false;
      }
    }

    lines.forEach((rawLine) => {
      const line = rawLine.trim();
      if (!line) {
        closeLists();
        return;
      }

      if (/^@@CODE_\d+@@$/.test(line)) {
        closeLists();
        html.push(line);
        return;
      }

      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        closeLists();
        const level = heading[1].length;
        html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
        return;
      }

      const quote = line.match(/^>\s?(.*)$/);
      if (quote) {
        closeLists();
        html.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
        return;
      }

      const ordered = line.match(/^\d+\.\s+(.+)$/);
      if (ordered) {
        if (!inOl) {
          closeLists();
          html.push("<ol>");
          inOl = true;
        }
        html.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
        return;
      }

      const unordered = line.match(/^[-*]\s+(.+)$/);
      if (unordered) {
        if (!inUl) {
          closeLists();
          html.push("<ul>");
          inUl = true;
        }
        html.push(`<li>${inlineMarkdown(unordered[1])}</li>`);
        return;
      }

      closeLists();
      html.push(`<p>${inlineMarkdown(line)}</p>`);
    });

    closeLists();
    let result = html.join("\n");
    codeBlocks.forEach((block, index) => {
      result = result.replace(`@@CODE_${index}@@`, block);
    });
    return result || "<p class='subtle'>空文档</p>";
  }

  function setEditorStatus(text) {
    if (mdEditorStatus) {
      mdEditorStatus.textContent = text;
    }
  }

  function setEditorMode(mode) {
    const nextMode = mode === "view" ? "view" : "edit";
    editor.mode = nextMode;
    const shell = mdEditorOverlay?.querySelector(".editor-shell");
    if (shell) {
      shell.classList.toggle("view-mode", nextMode === "view");
    }
    if (mdEditorInput) {
      mdEditorInput.readOnly = nextMode === "view";
    }
    if (mdEditorSwitchMode) {
      mdEditorSwitchMode.textContent = nextMode === "view" ? "进入编辑" : "仅预览";
    }
  }

  function renderEditorPreview() {
    if (!mdEditorPreview) {
      return;
    }
    mdEditorPreview.innerHTML = markdownToHtml(mdEditorInput?.value || "");
  }

  function ensureEditorAvailable() {
    if (!canUseMarkdownApi()) {
      window.alert(
        "当前是 file:// 模式，浏览器无法直接写回本地文件。\n请先运行: python3 .agents/skills/paper-research-workbench/scripts/serve_user_hub.py\n然后访问: http://127.0.0.1:8765/doc/papers/user/index.html",
      );
      return false;
    }
    return true;
  }

  async function openMarkdownEditor(path, title, options = {}) {
    if (!ensureEditorAvailable()) {
      return;
    }
    if (!mdEditorOverlay || !mdEditorInput || !mdEditorPreview) {
      return;
    }

    const normalizedPath = toProjectMarkdownPath(path);
    editor.path = normalizedPath;
    editor.title = title || "Markdown";
    editor.loading = true;
    editor.dirty = false;
    editor.open = true;
    setEditorMode(options.mode || "edit");

    mdEditorOverlay.classList.add("open");
    mdEditorOverlay.setAttribute("aria-hidden", "false");
    window.requestAnimationFrame(() => {
      mdEditorOverlay.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    if (mdEditorTitle) {
      mdEditorTitle.textContent = `${editor.mode === "view" ? "查看" : "编辑"} ${editor.title}`;
    }
    if (mdEditorPath) {
      mdEditorPath.textContent = normalizedPath;
    }
    setEditorStatus("正在加载...");

    try {
      const response = await fetch(`/api/md?path=${encodeURIComponent(normalizedPath)}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`load failed: ${response.status}`);
      }
      const payload = await response.json();
      const content = String(payload.content || "");
      editor.content = content;
      mdEditorInput.value = content;
      renderEditorPreview();
      setEditorStatus(editor.mode === "view" ? "预览模式，可切换到编辑。" : "已加载，可编辑。");
      if (editor.mode === "edit") {
        window.requestAnimationFrame(() => mdEditorInput.focus());
      }
    } catch (error) {
      setEditorStatus("加载失败，请检查本地服务日志。");
    } finally {
      editor.loading = false;
    }
  }

  function openMarkdownViewer(path, title) {
    openMarkdownEditor(path, title, { mode: "view" });
  }

  function closeMarkdownEditor(force = false) {
    if (!mdEditorOverlay) {
      return;
    }
    if (!force && editor.dirty) {
      const confirmClose = window.confirm("当前有未保存内容，确定关闭编辑器吗？");
      if (!confirmClose) {
        return;
      }
    }
    editor.open = false;
    editor.loading = false;
    editor.saving = false;
    editor.dirty = false;
    editor.mode = "edit";
    editor.path = "";
    editor.title = "";
    editor.content = "";
    mdEditorOverlay.classList.remove("open");
    mdEditorOverlay.setAttribute("aria-hidden", "true");
    if (mdEditorInput) {
      mdEditorInput.value = "";
    }
    if (mdEditorPreview) {
      mdEditorPreview.innerHTML = "";
    }
    if (mdEditorPath) {
      mdEditorPath.textContent = "";
    }
    setEditorStatus("未打开文件");
  }

  async function saveMarkdownEditor() {
    if (!editor.open || editor.saving || editor.loading || editor.mode === "view" || !mdEditorInput) {
      return;
    }
    if (!ensureEditorAvailable()) {
      return;
    }
    editor.saving = true;
    const content = mdEditorInput.value;
    setEditorStatus("保存中...");
    try {
      const response = await fetch("/api/md", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: editor.path,
          content,
        }),
      });
      if (!response.ok) {
        throw new Error(`save failed: ${response.status}`);
      }
      editor.content = content;
      editor.dirty = false;
      setEditorStatus("已保存。");
    } catch (error) {
      setEditorStatus("保存失败，请检查本地服务。");
    } finally {
      editor.saving = false;
    }
  }

  function bindMarkdownViewLinks(root = document) {
    root.querySelectorAll(".md-view-link").forEach((element) => {
      if (element.dataset.mdBound === "1") {
        return;
      }
      element.dataset.mdBound = "1";
      element.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openMarkdownViewer(element.dataset.mdPath || "", element.dataset.mdTitle || "markdown");
      });
    });
  }

  function bindMarkdownEditLinks(root = document) {
    root.querySelectorAll(".md-edit-link").forEach((element) => {
      if (element.dataset.mdEditBound === "1") {
        return;
      }
      element.dataset.mdEditBound = "1";
      element.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openMarkdownEditor(element.dataset.mdPath || "", element.dataset.mdTitle || "markdown");
      });
    });
  }

  function setQuickMdButton(button, path, title) {
    if (!button) {
      return;
    }
    const enabled = Boolean(path);
    button.dataset.mdPath = enabled ? path : "";
    button.dataset.mdTitle = title;
    button.disabled = !enabled;
    button.setAttribute("aria-disabled", enabled ? "false" : "true");
  }

  function syncQuickActions() {
    const paper = paperMap.get(state.selectedPaperId) || null;
    if (quickActionsPaper) {
      quickActionsPaper.textContent = paper ? shortLabel(paper.title || paper.paper_id, 42) : "未选中论文";
    }
    setQuickMdButton(quickViewNote, paper?.note_path || "", "note.md");
    setQuickMdButton(quickEditNote, paper?.note_path || "", "note.md");
    setQuickMdButton(quickViewIdeas, paper?.ideas_path || "", "ideas.md");
    setQuickMdButton(quickEditIdeas, paper?.ideas_path || "", "ideas.md");
    setQuickMdButton(quickViewFeasibility, paper?.feasibility_path || "", "feasibility.md");
    setQuickMdButton(quickEditFeasibility, paper?.feasibility_path || "", "feasibility.md");

    if (quickOpenPdf) {
      const href = String(paper?.source_pdf_link || "").trim();
      if (href) {
        quickOpenPdf.href = href;
        quickOpenPdf.removeAttribute("aria-disabled");
      } else {
        quickOpenPdf.removeAttribute("href");
        quickOpenPdf.setAttribute("aria-disabled", "true");
      }
    }
  }

  function currentPaper() {
    return paperMap.get(state.selectedPaperId) || null;
  }

  function ensureSelectedTopic() {
    if (state.selectedTopic && topicMap.has(state.selectedTopic)) {
      return;
    }
    state.selectedTopic = data.topics?.[0]?.topic || "";
  }

  function currentTopic() {
    ensureSelectedTopic();
    return topicMap.get(state.selectedTopic) || null;
  }

  function bindTabSwitchLinks(root = document) {
    root.querySelectorAll("[data-switch-tab]").forEach((element) => {
      if (element.dataset.tabBound === "1") {
        return;
      }
      element.dataset.tabBound = "1";
      element.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setActiveTab(element.dataset.switchTab || "overview");
      });
    });
  }

  function filteredPapers() {
    const query = state.query.trim().toLowerCase();
    return (data.papers || []).filter((paper) => {
      const searchable = [paper.title, ...(paper.tags || []), ...(paper.topics || []), ...(paper.authors || [])]
        .join(" ")
        .toLowerCase();
      if (query && !searchable.includes(query)) {
        return false;
      }
      if (state.topic && !(paper.topics || []).includes(state.topic)) {
        return false;
      }
      return true;
    });
  }

  function resetViewport() {
    viewport.scale = 1;
    viewport.panX = 0;
    viewport.panY = 0;
  }

  function syncCanvasSize() {
    const rect = graphCanvas.getBoundingClientRect();
    const width = rect.width > 12 ? Math.round(rect.width) : viewport.width;
    const height = rect.height > 12 ? Math.round(rect.height) : viewport.height;
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const pixelWidth = Math.max(1, Math.round(width * dpr));
    const pixelHeight = Math.max(1, Math.round(height * dpr));

    viewport.width = width;
    viewport.height = height;
    viewport.dpr = dpr;

    if (graphCanvas.width !== pixelWidth || graphCanvas.height !== pixelHeight) {
      graphCanvas.width = pixelWidth;
      graphCanvas.height = pixelHeight;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function screenToWorld(point) {
    return {
      x: (point.x - viewport.panX) / viewport.scale,
      y: (point.y - viewport.panY) / viewport.scale,
    };
  }

  function canvasPoint(event) {
    const rect = graphCanvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  function updateCanvasCursor() {
    if (interaction.mode === "node" || interaction.mode === "pan") {
      graphCanvas.style.cursor = "grabbing";
      return;
    }
    graphCanvas.style.cursor = state.hoveredPaperId ? "pointer" : "grab";
  }

  function stopGraphMotion() {
    if (motion.rafId !== null) {
      window.cancelAnimationFrame(motion.rafId);
      motion.rafId = null;
    }
    motion.lastTs = 0;
    motion.settleFrames = 0;
    motion.isAnimating = false;
    graphNodes.forEach((node) => {
      node.vx = 0;
      node.vy = 0;
      node.ax = 0;
      node.ay = 0;
    });
  }

  function requestMotionFrame() {
    if (motion.rafId !== null) {
      return;
    }
    motion.rafId = window.requestAnimationFrame(runMotionFrame);
  }

  function startSettleMotion(frames) {
    motion.settleFrames = Math.max(motion.settleFrames, frames);
    requestMotionFrame();
  }

  function buildGraphData() {
    syncCanvasSize();

    graphNodes = (data.papers || []).map((paper) => {
      const degree = Math.max((paper.neighbors || []).length, 1);
      return {
        id: paper.paper_id,
        label: paper.title,
        degree,
        role: "dim",
        radius: 5 + Math.min(degree * 1.05, 6.2),
        x: 0,
        y: 0,
        homeX: 0,
        homeY: 0,
        vx: 0,
        vy: 0,
        ax: 0,
        ay: 0,
      };
    });

    const nodeMap = new Map(graphNodes.map((node) => [node.id, node]));
    graphEdges = (data.edges || [])
      .map((edge) => {
        const source = nodeMap.get(edge.source_paper_id);
        const target = nodeMap.get(edge.target_paper_id);
        if (!source || !target) {
          return null;
        }
        return { source, target, score: Number(edge.score || 0) };
      })
      .filter(Boolean);

    if (graphEdges.length) {
      scoreRange = {
        min: Math.min(...graphEdges.map((edge) => edge.score)),
        max: Math.max(...graphEdges.map((edge) => edge.score)),
      };
    } else {
      scoreRange = { min: 3, max: 3 };
    }

    const minScore = Math.max(3, Math.floor(scoreRange.min * 2) / 2);
    const maxScore = Math.max(minScore, Math.ceil(scoreRange.max * 2) / 2);
    state.graphMinScore = minScore;

    if (edgeThresholdInput) {
      edgeThresholdInput.min = String(minScore);
      edgeThresholdInput.max = String(maxScore);
      edgeThresholdInput.step = "0.5";
      edgeThresholdInput.value = String(minScore);
    }

    layoutAroundSelected();
  }

  function layoutAroundSelected() {
    syncCanvasSize();
    if (!graphNodes.length) {
      return;
    }

    if (!state.selectedPaperId || !paperMap.has(state.selectedPaperId)) {
      state.selectedPaperId = graphNodes[0].id;
    }

    const width = viewport.width;
    const height = viewport.height;
    const centerX = width * 0.48;
    const centerY = height * 0.43;
    const margin = 46;
    const selectedPaper = paperMap.get(state.selectedPaperId);
    const neighborIds = new Set((selectedPaper?.neighbors || []).map((item) => item.paper_id));

    graphNodes.forEach((node) => {
      node.role = "dim";
      node.radius = 5.8;
      if (node.id === state.selectedPaperId) {
        node.role = "selected";
        node.radius = 8.8;
      } else if (neighborIds.has(node.id)) {
        node.role = "neighbor";
        node.radius = 6.8;
      }
    });

    const selectedNode = graphNodes.find((node) => node.id === state.selectedPaperId);
    if (selectedNode) {
      selectedNode.x = centerX;
      selectedNode.y = centerY;
    }

    const neighbors = graphNodes
      .filter((node) => node.role === "neighbor")
      .sort((left, right) => left.label.localeCompare(right.label));

    const arcStart = -Math.PI * 0.9;
    const arcEnd = Math.PI * 0.18;
    neighbors.forEach((node, index) => {
      const t = neighbors.length <= 1 ? 0.5 : index / (neighbors.length - 1);
      const angle = arcStart + (arcEnd - arcStart) * t;
      const radiusX = 214 + (index % 2) * 16;
      const radiusY = 188 + ((index + 1) % 2) * 12;
      node.x = centerX + Math.cos(angle) * radiusX;
      node.y = centerY + Math.sin(angle) * radiusY;
    });

    graphNodes
      .filter((node) => node.role === "dim")
      .forEach((node, index) => {
        let x = margin + unitNoise(node.id, index + 13) * (width - margin * 2);
        let y = margin + unitNoise(node.id, index + 37) * (height - margin * 2);
        const dx = x - centerX;
        const dy = y - centerY;
        const dist = Math.hypot(dx, dy);
        if (dist < 175) {
          const safeRadius = 175 + unitNoise(node.id, 71) * 74;
          const scale = safeRadius / Math.max(1, dist);
          x = centerX + dx * scale;
          y = centerY + dy * scale;
        }
        node.x = clamp(x, margin, width - margin);
        node.y = clamp(y, margin, height - margin);
      });

    graphNodes.forEach((node) => {
      node.homeX = node.x;
      node.homeY = node.y;
      node.vx = 0;
      node.vy = 0;
      node.ax = 0;
      node.ay = 0;
    });
    stopGraphMotion();
  }

  function visibleEdges() {
    return graphEdges.filter((edge) => edge.score >= state.graphMinScore);
  }

  function neighborhoodIdsFor(paperId) {
    const paper = paperMap.get(paperId);
    if (!paper) {
      return new Set();
    }
    const ids = new Set([paper.paper_id]);
    (paper.neighbors || []).forEach((neighbor) => ids.add(neighbor.paper_id));
    return ids;
  }

  function focusNeighborhoodIds() {
    const ids = new Set();
    const roots = focusRootIds();
    roots.forEach((paperId) => {
      neighborhoodIdsFor(paperId).forEach((id) => ids.add(id));
    });
    return ids;
  }

  function focusRootIds() {
    const ids = new Set();
    if (state.selectedPaperId) {
      ids.add(state.selectedPaperId);
    }
    if (state.hoveredPaperId && state.hoveredPaperId !== state.selectedPaperId) {
      ids.add(state.hoveredPaperId);
    }
    return ids;
  }

  function displayEdges(rootIds) {
    const edges = visibleEdges();
    if (state.showAllLabels) {
      return edges;
    }
    return edges.filter((edge) => rootIds.has(edge.source.id) || rootIds.has(edge.target.id));
  }

  function closestNode(point, maxDistanceScreen) {
    const maxDistance = maxDistanceScreen / viewport.scale;
    let bestNode = null;
    let bestDistance = Infinity;
    graphNodes.forEach((node) => {
      const distance = Math.hypot(node.x - point.x, node.y - point.y);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestNode = node;
      }
    });
    if (!bestNode || bestDistance > maxDistance) {
      return null;
    }
    return bestNode;
  }

  function updateHover(screenPoint) {
    if (interaction.mode !== "none") {
      return;
    }
    const worldPoint = screenToWorld(screenPoint);
    const node = closestNode(worldPoint, 30);
    const nextHoveredId = node ? node.id : null;
    if (nextHoveredId !== state.hoveredPaperId) {
      state.hoveredPaperId = nextHoveredId;
      drawGraph();
    }
  }

  function clampNode(node, x, y) {
    const pad = Math.max(12, node.radius + 4);
    return {
      x: clamp(x, pad, viewport.width - pad),
      y: clamp(y, pad, viewport.height - pad),
    };
  }

  function simulateGraphStep(dt) {
    const activeDragNode = interaction.mode === "node" && interaction.node && interaction.moved ? interaction.node : null;
    if (!activeDragNode && motion.settleFrames <= 0) {
      return false;
    }

    const edges = visibleEdges();
    const scoreSpan = Math.max(0.001, scoreRange.max - scoreRange.min);
    const integration = clamp(dt * 60, 0.5, 1.7);
    const damping = 0.82;
    const springBase = 0.016;
    const repulsionBase = 640;
    const anchorBase = 0.008;

    graphNodes.forEach((node) => {
      node.ax = 0;
      node.ay = 0;
    });

    edges.forEach((edge) => {
      const dx = edge.target.x - edge.source.x;
      const dy = edge.target.y - edge.source.y;
      const dist = Math.max(0.001, Math.hypot(dx, dy));
      const ux = dx / dist;
      const uy = dy / dist;
      const scoreNorm = (edge.score - scoreRange.min) / scoreSpan;
      const restLength = 144 - scoreNorm * 52;
      const spring = springBase + scoreNorm * 0.012;
      const force = (dist - restLength) * spring;
      const fx = ux * force;
      const fy = uy * force;

      if (edge.source !== activeDragNode) {
        edge.source.ax += fx;
        edge.source.ay += fy;
      }
      if (edge.target !== activeDragNode) {
        edge.target.ax -= fx;
        edge.target.ay -= fy;
      }
    });

    for (let i = 0; i < graphNodes.length; i += 1) {
      const first = graphNodes[i];
      for (let j = i + 1; j < graphNodes.length; j += 1) {
        const second = graphNodes[j];
        const dx = second.x - first.x;
        const dy = second.y - first.y;
        const distSq = dx * dx + dy * dy + 0.01;
        if (distSq > 180000) {
          continue;
        }
        const dist = Math.sqrt(distSq);
        const force = repulsionBase / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        if (first !== activeDragNode) {
          first.ax -= fx;
          first.ay -= fy;
        }
        if (second !== activeDragNode) {
          second.ax += fx;
          second.ay += fy;
        }
      }
    }

    graphNodes.forEach((node) => {
      if (node === activeDragNode) {
        return;
      }
      node.ax += (node.homeX - node.x) * anchorBase;
      node.ay += (node.homeY - node.y) * anchorBase;
    });

    graphNodes.forEach((node) => {
      if (node === activeDragNode) {
        const clamped = clampNode(node, interaction.targetX, interaction.targetY);
        node.x = clamped.x;
        node.y = clamped.y;
        node.vx = 0;
        node.vy = 0;
        return;
      }

      node.vx = (node.vx + node.ax * integration) * damping;
      node.vy = (node.vy + node.ay * integration) * damping;
      node.x += node.vx * integration;
      node.y += node.vy * integration;

      const clamped = clampNode(node, node.x, node.y);
      if (clamped.x !== node.x) {
        node.x = clamped.x;
        node.vx *= -0.24;
      }
      if (clamped.y !== node.y) {
        node.y = clamped.y;
        node.vy *= -0.24;
      }
    });

    if (!activeDragNode) {
      motion.settleFrames = Math.max(0, motion.settleFrames - 1);
    }
    return Boolean(activeDragNode) || motion.settleFrames > 0;
  }

  function runMotionFrame(timestamp) {
    motion.rafId = null;
    motion.isAnimating = true;
    const lastTs = motion.lastTs || timestamp - 16;
    const dt = clamp((timestamp - lastTs) / 1000, 0.008, 0.034);
    motion.lastTs = timestamp;

    const active = simulateGraphStep(dt);
    drawGraph();

    if (active) {
      requestMotionFrame();
      return;
    }

    motion.isAnimating = false;
    motion.lastTs = 0;
    motion.settleFrames = 0;
    graphNodes.forEach((node) => {
      node.vx = 0;
      node.vy = 0;
    });
    drawGraph();
  }

  function drawGraphBackground(palette, width, height) {
    ctx.fillStyle = palette.graphBg;
    ctx.fillRect(0, 0, width, height);

    const haloX = width * 0.5;
    const haloY = height * 0.46;
    const halo = ctx.createRadialGradient(haloX, haloY, 24, haloX, haloY, 360);
    halo.addColorStop(0, "rgba(167, 139, 250, 0.14)");
    halo.addColorStop(1, "rgba(167, 139, 250, 0)");
    ctx.fillStyle = halo;
    ctx.fillRect(0, 0, width, height);

    const grid = 36;
    ctx.strokeStyle = palette.graphGrid;
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += grid) {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += grid) {
      ctx.beginPath();
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(width, y + 0.5);
      ctx.stroke();
    }
  }

  function drawGraph() {
    syncCanvasSize();
    const width = viewport.width;
    const height = viewport.height;
    const rootIds = focusRootIds();
    const focusIds = focusNeighborhoodIds();
    const totalEdges = visibleEdges();
    const edges = displayEdges(rootIds);
    const palette = {
      graphBg: readThemeVar("--graph-canvas-bg", "#11111b"),
      graphGrid: readThemeVar("--graph-grid", "rgba(186, 168, 255, 0.08)"),
      graphEdge: readThemeVar("--graph-edge", "rgba(170, 160, 204, 0.24)"),
      graphEdgeFocus: readThemeVar("--graph-edge-focus", "rgba(185, 156, 255, 0.9)"),
      graphNode: readThemeVar("--graph-node", "#c7c3d8"),
      graphNodeMuted: readThemeVar("--graph-node-muted", "#5f5a77"),
      graphNodeActive: readThemeVar("--graph-node-active", "#a78bfa"),
      graphNodeHalo: readThemeVar("--graph-node-halo", "rgba(167, 139, 250, 0.28)"),
      graphLabel: readThemeVar("--graph-label", "#f4f1ff"),
      graphLabelNear: readThemeVar("--graph-label-near", "#ddd6fe"),
      graphLabelMuted: readThemeVar("--graph-label-muted", "#9a92b7"),
    };

    ctx.setTransform(viewport.dpr, 0, 0, viewport.dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    drawGraphBackground(palette, width, height);

    ctx.save();
    ctx.translate(viewport.panX, viewport.panY);
    ctx.scale(viewport.scale, viewport.scale);

    edges.forEach((edge) => {
      const primaryId = state.hoveredPaperId || state.selectedPaperId;
      const focusEdge =
        edge.source.id === primaryId ||
        edge.target.id === primaryId ||
        (focusIds.has(edge.source.id) && focusIds.has(edge.target.id));
      const scoreNorm =
        scoreRange.max > scoreRange.min ? (edge.score - scoreRange.min) / (scoreRange.max - scoreRange.min) : 1;
      ctx.lineWidth = (focusEdge ? 1.05 + scoreNorm * 1.05 : 0.62) / viewport.scale;
      ctx.strokeStyle = focusEdge ? palette.graphEdgeFocus : palette.graphEdge;
      ctx.beginPath();
      ctx.moveTo(edge.source.x, edge.source.y);
      ctx.lineTo(edge.target.x, edge.target.y);
      ctx.stroke();
    });

    graphNodes.forEach((node) => {
      const isSelected = node.id === state.selectedPaperId;
      const isHovered = node.id === state.hoveredPaperId;
      const isNear = focusIds.has(node.id) && !isSelected;
      const radius = node.radius + (isSelected ? 1.2 : 0) + (isHovered ? 0.6 : 0);

      if (isSelected || isHovered) {
        ctx.beginPath();
        ctx.fillStyle = palette.graphNodeHalo;
        ctx.arc(node.x, node.y, radius + 6, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.beginPath();
      ctx.fillStyle = isSelected ? palette.graphNodeActive : isNear ? palette.graphNode : palette.graphNodeMuted;
      ctx.strokeStyle = isSelected ? "#ffffff" : "rgba(255, 255, 255, 0.14)";
      ctx.lineWidth = (isSelected ? 1.15 : 0.8) / viewport.scale;
      ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();

      const showLabel = state.showAllLabels || isSelected || isHovered || isNear;
      if (showLabel) {
        const label = shortLabel(node.label, isSelected ? 36 : 30);
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.font = `${isSelected ? 600 : 500} ${isSelected ? 13 : 11.5}px Manrope`;
        ctx.fillStyle = isSelected ? palette.graphLabel : isNear ? palette.graphLabelNear : palette.graphLabelMuted;
        ctx.fillText(label, node.x, node.y + radius + 9);
      }
    });

    ctx.restore();
    updateCanvasCursor();

    if (graphStatus) {
      const selectedTitle = paperMap.get(state.selectedPaperId)?.title || "未选中";
      const scopeLabel = state.showAllLabels ? "全图" : "聚焦";
      graphStatus.textContent = `模式 ${scopeLabel} | 连边 ${edges.length}/${totalEdges.length} | 缩放 ${viewport.scale.toFixed(2)}x | 当前 ${shortLabel(selectedTitle, 24)}`;
    }

    if (!motion.isAnimating && interaction.mode === "none") {
      renderPaperDetail(graphDetail, paperMap.get(state.selectedPaperId), { graphMode: true });
    }
  }

  function setActiveTab(tab) {
    state.activeTab = tab;
    render();
    if (tab === "graph") {
      window.requestAnimationFrame(() => {
        syncCanvasSize();
        drawGraph();
      });
    }
  }

  function selectPaper(paperId, nextTab, options = {}) {
    if (!paperMap.has(paperId)) {
      return;
    }
    stopGraphMotion();
    state.selectedPaperId = paperId;
    if (nextTab) {
      state.activeTab = nextTab;
    }
    if (options.relayout !== false) {
      layoutAroundSelected();
    }
    render();
  }

  function renderTabs() {
    tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.tab === state.activeTab);
    });
    panels.forEach((panel) => {
      panel.classList.toggle("active", panel.id === `panel-${state.activeTab}`);
    });
  }

  function renderSidebar() {
    const topics = (data.topics || []).slice(0, 10);
    chipbar.innerHTML = [
      `<button class="chip ${state.topic ? "" : "active"}" data-topic="">all</button>`,
      ...topics.map(
        (topic) =>
          `<button class="chip ${state.topic === topic.topic ? "active" : ""}" data-topic="${escapeHtml(topic.topic)}">${escapeHtml(topic.topic)} (${topic.count})</button>`,
      ),
    ].join("");

    chipbar.querySelectorAll(".chip").forEach((button) => {
      button.addEventListener("click", () => {
        state.topic = button.dataset.topic || "";
        render();
      });
    });

    const papers = filteredPapers();
    paperList.innerHTML = papers
      .map(
        (paper) => `
          <div class="paper-item ${paper.paper_id === state.selectedPaperId ? "active" : ""}" data-paper-id="${paper.paper_id}" tabindex="0" role="button" aria-label="打开 ${escapeHtml(paper.title)}">
            <h3>${escapeHtml(shortLabel(paper.title, 48))}</h3>
            <p>${escapeHtml((paper.topics || []).slice(0, 3).join(" / ") || "无 topic")}</p>
          </div>
        `,
      )
      .join("");

    if (!papers.length) {
      paperList.innerHTML = `<div class="paper-item"><p class="subtle">没有匹配结果，试试清空筛选词。</p></div>`;
    }

    paperList.querySelectorAll(".paper-item[data-paper-id]").forEach((item) => {
      const onOpen = () => selectPaper(item.dataset.paperId, "detail");
      item.addEventListener("click", onOpen);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      });
    });
  }

  function renderOverview() {
    const selectedPaper = currentPaper();
    const papers = filteredPapers().slice(0, 4);

    if (overviewHero) {
      overviewHero.innerHTML = selectedPaper
        ? `
          <div class="section-label">起点</div>
          <h3>${escapeHtml(selectedPaper.title)}</h3>
          <p class="hero-copy">当前聚焦论文。先判断它在整个库里的位置，再进入单篇工作区继续做笔记和改想法。</p>
          <div class="hero-actions">
            <button class="btn" type="button" data-switch-tab="detail">进入论文工作区</button>
            <button class="btn ghost" type="button" data-switch-tab="graph">在关系图中定位</button>
          </div>
        `
        : `
          <div class="section-label">起点</div>
          <h3>先从论文库总览开始</h3>
          <p class="hero-copy">当前还没有可选中的论文。先刷新工作区或检查 raw 目录下的 PDF 是否已被解析。</p>
        `;
    }

    if (overviewRoutes) {
      overviewRoutes.innerHTML = `
        <button class="route-card" type="button" data-switch-tab="graph">
          <strong>关系图探索</strong>
          <span>先看当前论文的直接邻居和局部结构。</span>
        </button>
        <button class="route-card" type="button" data-switch-tab="topics">
          <strong>主题浏览</strong>
          <span>按 topic 聚合浏览，快速判断方向分布。</span>
        </button>
        <button class="route-card" type="button" data-switch-tab="ideas">
          <strong>综合想法</strong>
          <span>看跨论文综合出来的前沿可执行想法。</span>
        </button>
        <button class="route-card" type="button" data-switch-tab="detail">
          <strong>单篇工作区</strong>
          <span>集中查看并编辑 note、ideas、feasibility。</span>
        </button>
      `;
    }

    if (overviewSelection) {
      overviewSelection.innerHTML = selectedPaper
        ? `
          <article class="paper-card">
            <div class="section-label">当前论文</div>
            <h3>${escapeHtml(selectedPaper.title)}</h3>
            <p class="subtle">${escapeHtml((selectedPaper.authors || []).slice(0, 5).join(", "))}${(selectedPaper.authors || []).length > 5 ? " ..." : ""}</p>
            <p class="subtle">${escapeHtml(compactText(selectedPaper.abstract_brief || selectedPaper.abstract || "暂无摘要。", 220))}</p>
            <div class="tagline">${(selectedPaper.topics || []).map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join("")}</div>
          </article>
        `
        : `<article class="paper-card"><p class="subtle">暂无当前论文。</p></article>`;
    }

    overviewPapers.innerHTML = papers
      .map(
        (paper) => `
          <article class="paper-card" data-paper-id="${paper.paper_id}">
            <div class="section-label">最近论文</div>
            <h3>${escapeHtml(paper.title)}</h3>
            <p class="subtle">${escapeHtml((paper.authors || []).slice(0, 4).join(", "))}${(paper.authors || []).length > 4 ? " ..." : ""}</p>
            <p class="subtle">${escapeHtml(compactText(paper.note_preview || paper.abstract_brief || "暂无摘要。", 180))}</p>
            <div class="tagline">${(paper.tags || []).slice(0, 5).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
          </article>
        `,
      )
      .join("");

    if (!papers.length) {
      overviewPapers.innerHTML = `<article class="paper-card"><p class="subtle">暂无可展示论文。</p></article>`;
    }

    overviewPapers.querySelectorAll(".paper-card[data-paper-id]").forEach((card) => {
      card.addEventListener("click", () => selectPaper(card.dataset.paperId, "detail"));
    });

    bindTabSwitchLinks(overviewHero || document);
    bindTabSwitchLinks(overviewRoutes || document);
  }

  function renderTopics() {
    ensureSelectedTopic();
    const topic = currentTopic();

    topicList.innerHTML = (data.topics || [])
      .map(
        (topic) => `
          <article class="topic-row ${state.selectedTopic === topic.topic ? "active" : ""}" data-topic="${escapeHtml(topic.topic)}">
            <div class="topic-row-head">
              <div>
                <div class="section-label">${escapeHtml(topic.topic)}</div>
                <p class="subtle">${escapeHtml((topic.paper_ids || []).slice(0, 3).map((paperId) => paperMap.get(paperId)?.title || paperId).join(" / "))}</p>
              </div>
              <div class="topic-count">${topic.count} papers</div>
            </div>
            <div class="path-list">
              <button class="path-link md-view-link" type="button" data-md-path="topic-maps/${escapeHtml(topic.file_name || "")}" data-md-title="${escapeHtml(topic.topic)} 主题地图">在界面中查看主题地图</button>
            </div>
          </article>
        `,
      )
      .join("");

    if (!(data.topics || []).length) {
      topicList.innerHTML = `<article class="topic-row"><p class="subtle">暂无 topic 数据。</p></article>`;
    }

    topicList.querySelectorAll(".topic-row[data-topic]").forEach((element) => {
      element.addEventListener("click", () => {
        state.selectedTopic = element.dataset.topic || "";
        renderTopics();
      });
    });

    if (topicDetailBadge) {
      topicDetailBadge.textContent = topic ? `${topic.count} papers` : "未选择";
    }

    if (topicOpenSelected) {
      if (topic?.file_name) {
        topicOpenSelected.dataset.mdPath = `topic-maps/${topic.file_name}`;
        topicOpenSelected.dataset.mdTitle = `${topic.topic} 主题地图`;
        topicOpenSelected.disabled = false;
        topicOpenSelected.setAttribute("aria-disabled", "false");
      } else {
        topicOpenSelected.dataset.mdPath = "";
        topicOpenSelected.dataset.mdTitle = "topic maps";
        topicOpenSelected.disabled = true;
        topicOpenSelected.setAttribute("aria-disabled", "true");
      }
    }

    if (topicDetail) {
      if (!topic) {
        topicDetail.innerHTML = `<p class="subtle">暂无主题详情。</p>`;
      } else {
        const topicPapers = (topic.paper_ids || [])
          .map((paperId) => paperMap.get(paperId))
          .filter(Boolean)
          .slice(0, 6);

        topicDetail.innerHTML = `
          <p class="detail-copy">当前主题 <strong>${escapeHtml(topic.topic)}</strong> 下共有 ${topic.count} 篇论文。适合先看这个聚合，再决定是否进入关系图找局部结构，或回到单篇工作区做笔记。</p>
          <div class="tagline"><span class="tag">topic: ${escapeHtml(topic.topic)}</span><span class="tag">papers: ${escapeHtml(String(topic.count))}</span></div>
          <div class="topic-detail-list">
            ${topicPapers
              .map(
                (paper) => `
                  <article class="mini-paper" data-paper-id="${escapeHtml(paper.paper_id)}">
                    <strong>${escapeHtml(shortLabel(paper.title, 68))}</strong>
                    <span>${escapeHtml((paper.tags || []).slice(0, 4).join(" / ") || "无 tag")}</span>
                  </article>
                `,
              )
              .join("") || "<p class='subtle'>暂无论文。</p>"}
          </div>
        `;
      }
    }

    if (topicDetail) {
      topicDetail.querySelectorAll("[data-paper-id]").forEach((element) => {
        element.addEventListener("click", () => {
          selectPaper(element.dataset.paperId, "detail");
        });
      });
    }

    bindMarkdownViewLinks(topicList);
    bindMarkdownViewLinks(topicDetail || document);
    bindMarkdownViewLinks(document);
  }

  function renderIdeaList() {
    const ideas = data.frontier_ideas || [];
    if (ideaSummary) {
      ideaSummary.innerHTML = `
        <div class="section-label">综合洞察</div>
        <h3 class="idea-summary-title">综合想法区</h3>
        <p class="hero-copy">这里展示的是基于整个论文库综合出来的前沿方向。建议先读这里判断值得投入的题目，再进入单篇论文工作区补证据、改实验设计。</p>
        <div class="idea-summary-meta">
          <span class="tag">ideas: ${escapeHtml(String(ideas.length))}</span>
          <span class="tag">papers: ${escapeHtml(String(data.paper_count || 0))}</span>
          <span class="tag">topics: ${escapeHtml(String(data.topic_count || 0))}</span>
        </div>
        <div class="hero-actions">
          <button class="btn ghost md-view-link" type="button" data-md-path="syntheses/frontier-ideas.md" data-md-title="综合 idea 文档">查看综合文档</button>
          <button class="btn ghost" type="button" data-switch-tab="detail">回到论文工作区</button>
        </div>
      `;
    }

    ideaList.innerHTML = ideas
      .map(
        (idea, index) => `
          <article class="idea-card">
            <div class="section-label">综合想法 ${index + 1}</div>
            <h3>${escapeHtml(idea.title || "未命名 idea")}</h3>
            <p><strong>为什么现在做：</strong>${escapeHtml(idea.why_now || "")}</p>
            <p><strong>最小可行实验：</strong>${escapeHtml(idea.minimum_viable_experiment || "")}</p>
            <p><strong>预期收益：</strong>${escapeHtml(idea.expected_gain || "")}</p>
            <p><strong>主要风险：</strong>${escapeHtml(idea.main_risk || "")}</p>
            <div class="support-list">
              ${(idea.supporting_titles || [])
                .slice(0, 3)
                .map((title) => `<span class="tag">${escapeHtml(title)}</span>`)
                .join("")}
            </div>
            <div class="tagline">
              <span class="tag">priority: ${escapeHtml(idea.priority || "n/a")}</span>
              <span class="tag">difficulty: ${escapeHtml(idea.execution_difficulty || "n/a")}</span>
              <span class="tag">topic: ${escapeHtml(idea.topic_anchor || "n/a")}</span>
            </div>
          </article>
        `,
      )
      .join("");

    if (!ideas.length) {
      ideaList.innerHTML = `<article class="idea-card"><p class="subtle">暂无综合 idea，先运行构建脚本。</p></article>`;
    }

    bindMarkdownViewLinks(ideaSummary || document);
    bindTabSwitchLinks(ideaSummary || document);
  }

  function renderPaperDetail(target, paper, options = {}) {
    if (!target) {
      return;
    }
    if (!paper) {
      target.innerHTML = `<article class="detail-block"><p class="subtle">暂无论文。</p></article>`;
      return;
    }

    const neighbors = (paper.neighbors || [])
      .map(
        (neighbor) => `
          <article class="neighbor-card" data-paper-id="${neighbor.paper_id}">
            <div class="section-label">${escapeHtml(shortLabel(neighbor.title || neighbor.paper_id, 72))}</div>
            <p class="subtle">score=${escapeHtml(String(neighbor.score || 0))} | topic=${escapeHtml((neighbor.shared_topics || []).join(" / ") || "n/a")}</p>
          </article>
        `,
      )
      .join("");

    if (options.graphMode) {
      target.innerHTML = `
        <article class="detail-block">
          <div class="section-label">图谱聚焦</div>
          <h3>${escapeHtml(paper.title)}</h3>
          <p class="detail-copy">${escapeHtml((paper.authors || []).slice(0, 6).join(", "))}${(paper.authors || []).length > 6 ? " ..." : ""}</p>
          <p class="detail-copy">${escapeHtml(compactText(paper.abstract_brief || paper.abstract || "暂无摘要。", 220))}</p>
          <div class="tagline">${(paper.topics || []).map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join("")}</div>
          <div class="path-list">
            <button class="path-link" type="button" data-switch-tab="detail">进入论文工作区</button>
            <button class="path-link md-view-link" type="button" data-md-path="${escapeHtml(paper.note_path)}" data-md-title="note.md">查看 note.md</button>
          </div>
        </article>
        <article class="detail-block">
          <div class="section-label">直接相关论文</div>
          <div class="stack">${neighbors || "<p class='subtle'>暂无近邻论文。</p>"}</div>
        </article>
      `;

      target.querySelectorAll("[data-paper-id]").forEach((element) => {
        element.addEventListener("click", () => selectPaper(element.dataset.paperId, "graph", { relayout: false }));
      });
      bindMarkdownViewLinks(target);
      bindTabSwitchLinks(target);
      return;
    }

    target.innerHTML = `
      <div class="detail-column">
        <article class="detail-block">
          <div class="section-label">论文工作区</div>
          <h3>${escapeHtml(paper.title)}</h3>
          <p class="detail-copy">${escapeHtml((paper.authors || []).join(", ") || "authors unknown")}</p>
          <p class="detail-copy">paper_id: ${escapeHtml(paper.paper_id)} | year: ${escapeHtml(String(paper.year || "n/a"))}</p>
          <p class="detail-copy">${escapeHtml(compactText(paper.abstract_brief || paper.abstract || "暂无摘要。", 360))}</p>
          <div class="tagline">${(paper.topics || []).map((topic) => `<span class="tag">${escapeHtml(topic)}</span>`).join("")}</div>
          <div class="tagline">${(paper.tags || []).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>
        </article>
        <article class="detail-block">
          <div class="section-label">编辑入口</div>
          <div class="file-grid">
            <button class="file-link md-view-link" type="button" data-md-path="${escapeHtml(paper.note_path)}" data-md-title="note.md">内嵌查看 note.md</button>
            <button class="file-link md-edit-link" type="button" data-md-path="${escapeHtml(paper.note_path)}" data-md-title="note.md">内嵌编辑 note.md</button>
            <button class="file-link md-view-link" type="button" data-md-path="${escapeHtml(paper.ideas_path)}" data-md-title="ideas.md">内嵌查看 ideas.md</button>
            <button class="file-link md-edit-link" type="button" data-md-path="${escapeHtml(paper.ideas_path)}" data-md-title="ideas.md">内嵌编辑 ideas.md</button>
            <button class="file-link md-view-link" type="button" data-md-path="${escapeHtml(paper.feasibility_path)}" data-md-title="feasibility.md">内嵌查看 feasibility.md</button>
            <button class="file-link md-edit-link" type="button" data-md-path="${escapeHtml(paper.feasibility_path)}" data-md-title="feasibility.md">内嵌编辑 feasibility.md</button>
            <a class="file-link" href="${escapeHtml(paper.ai_node_path)}" target="_blank" rel="noopener">外部打开 ai node</a>
            ${paper.source_pdf_link ? `<a class="file-link" href="${escapeHtml(paper.source_pdf_link)}" target="_blank" rel="noopener">打开 raw pdf</a>` : ""}
          </div>
        </article>
      </div>
      <div class="neighbor-stack">
        <article class="detail-block">
          <div class="section-label">预览</div>
          <p class="detail-copy">${escapeHtml(paper.note_preview || "暂无 note 预览。")}</p>
          <p class="detail-copy">${escapeHtml(paper.idea_preview || "暂无 idea 预览。")}</p>
          <p class="detail-copy">${escapeHtml(paper.feasibility_preview || "暂无 feasibility 预览。")}</p>
        </article>
        <article class="detail-block">
          <div class="section-label">相关论文</div>
          <div class="stack">${neighbors || "<p class='subtle'>暂无近邻论文。</p>"}</div>
        </article>
      </div>
    `;

    target.querySelectorAll("[data-paper-id]").forEach((element) => {
      element.addEventListener("click", () =>
        selectPaper(element.dataset.paperId, options.graphMode ? "graph" : "detail", {
          relayout: !options.graphMode,
        }),
      );
    });

    bindMarkdownViewLinks(target);
    bindMarkdownEditLinks(target);
    bindTabSwitchLinks(target);
  }

  function syncGraphControls() {
    if (edgeThresholdValue) {
      edgeThresholdValue.textContent = state.graphMinScore.toFixed(1);
    }
    if (toggleLabelsButton) {
      toggleLabelsButton.textContent = `Scope: ${state.showAllLabels ? "All" : "Focus"}`;
    }
  }

  function render() {
    renderTabs();
    bindMarkdownViewLinks(document);
    bindMarkdownEditLinks(document);
    bindTabSwitchLinks(document);
    renderSidebar();
    renderOverview();
    renderTopics();
    renderIdeaList();
    renderPaperDetail(detailPanel, paperMap.get(state.selectedPaperId));
    syncQuickActions();
    syncGraphControls();
    drawGraph();
  }

  generatedAt.textContent = data.generated_at || "";
  paperCount.textContent = String(data.paper_count || 0);
  edgeCount.textContent = String(data.edge_count || 0);
  topicCount.textContent = String(data.topic_count || 0);
  ideaCount.textContent = String(data.idea_count || 0);

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => setActiveTab(tab.dataset.tab));
  });

  searchInput.addEventListener("input", () => {
    state.query = searchInput.value;
    render();
  });

  if (edgeThresholdInput) {
    edgeThresholdInput.addEventListener("input", () => {
      state.graphMinScore = Number(edgeThresholdInput.value || state.graphMinScore);
      drawGraph();
      syncGraphControls();
    });
  }

  if (toggleLabelsButton) {
    toggleLabelsButton.addEventListener("click", () => {
      state.showAllLabels = !state.showAllLabels;
      syncGraphControls();
      drawGraph();
    });
  }

  if (resetViewButton) {
    resetViewButton.addEventListener("click", () => {
      resetViewport();
      drawGraph();
    });
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      applyTheme(state.theme === "dark" ? "light" : "dark");
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      sendHubHeartbeat("visibility");
    }
  });

  window.addEventListener("focus", () => {
    sendHubHeartbeat("focus");
  });

  window.addEventListener("pagehide", () => {
    stopHubHeartbeat();
  });

  if (mdEditorInput) {
    mdEditorInput.addEventListener("input", () => {
      if (!editor.open) {
        return;
      }
      editor.dirty = mdEditorInput.value !== editor.content;
      renderEditorPreview();
      setEditorStatus(editor.dirty ? "已修改，未保存。" : "已保存。");
    });
  }

  if (mdEditorSave) {
    mdEditorSave.addEventListener("click", () => {
      saveMarkdownEditor();
    });
  }

  if (mdEditorSwitchMode) {
    mdEditorSwitchMode.addEventListener("click", () => {
      const nextMode = editor.mode === "view" ? "edit" : "view";
      setEditorMode(nextMode);
      if (mdEditorTitle) {
        mdEditorTitle.textContent = `${editor.mode === "view" ? "查看" : "编辑"} ${editor.title || "Markdown"}`;
      }
      setEditorStatus(editor.mode === "view" ? "预览模式，可切换到编辑。" : "编辑模式。");
      if (editor.mode === "edit" && mdEditorInput) {
        window.requestAnimationFrame(() => mdEditorInput.focus());
      }
    });
  }

  if (mdEditorClose) {
    mdEditorClose.addEventListener("click", () => {
      closeMarkdownEditor();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (!editor.open) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeMarkdownEditor();
      return;
    }
    const isSaveKey = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
    if (isSaveKey) {
      event.preventDefault();
      saveMarkdownEditor();
    }
  });

  graphCanvas.addEventListener("pointerdown", (event) => {
    const point = canvasPoint(event);
    const worldPoint = screenToWorld(point);
    const node = closestNode(worldPoint, 30);

    if (node) {
      interaction.mode = "node";
      interaction.pointerId = event.pointerId;
      interaction.node = node;
      interaction.moved = false;
      interaction.startScreenX = point.x;
      interaction.startScreenY = point.y;
      interaction.offsetX = worldPoint.x - node.x;
      interaction.offsetY = worldPoint.y - node.y;
      interaction.targetX = node.x;
      interaction.targetY = node.y;
      state.hoveredPaperId = node.id;
      graphCanvas.setPointerCapture(event.pointerId);
      updateCanvasCursor();
      drawGraph();
      event.preventDefault();
      return;
    }

    interaction.mode = "pan";
    interaction.pointerId = event.pointerId;
    interaction.moved = false;
    interaction.startScreenX = point.x;
    interaction.startScreenY = point.y;
    interaction.startPanX = viewport.panX;
    interaction.startPanY = viewport.panY;
    graphCanvas.setPointerCapture(event.pointerId);
    updateCanvasCursor();
    event.preventDefault();
  });

  graphCanvas.addEventListener("pointermove", (event) => {
    const point = canvasPoint(event);

    if (interaction.mode === "none") {
      updateHover(point);
      return;
    }

    if (interaction.pointerId !== event.pointerId) {
      return;
    }

    if (interaction.mode === "pan") {
      const dx = point.x - interaction.startScreenX;
      const dy = point.y - interaction.startScreenY;
      if (Math.hypot(dx, dy) > 2) {
        interaction.moved = true;
      }
      viewport.panX = interaction.startPanX + dx;
      viewport.panY = interaction.startPanY + dy;
      drawGraph();
      event.preventDefault();
      return;
    }

    if (interaction.mode === "node" && interaction.node) {
      const dragDistance = Math.hypot(point.x - interaction.startScreenX, point.y - interaction.startScreenY);
      if (dragDistance > 2) {
        interaction.moved = true;
      }
      const worldPoint = screenToWorld(point);
      const next = clampNode(
        interaction.node,
        worldPoint.x - interaction.offsetX,
        worldPoint.y - interaction.offsetY,
      );
      interaction.targetX = next.x;
      interaction.targetY = next.y;
      state.hoveredPaperId = interaction.node.id;
      if (interaction.moved) {
        if (state.selectedPaperId !== interaction.node.id) {
          state.selectedPaperId = interaction.node.id;
        }
        requestMotionFrame();
      } else {
        drawGraph();
      }
      event.preventDefault();
    }
  });

  function clearInteraction() {
    interaction.mode = "none";
    interaction.pointerId = null;
    interaction.node = null;
    interaction.moved = false;
    interaction.startScreenX = 0;
    interaction.startScreenY = 0;
    interaction.startPanX = 0;
    interaction.startPanY = 0;
    interaction.offsetX = 0;
    interaction.offsetY = 0;
    interaction.targetX = 0;
    interaction.targetY = 0;
  }

  function finishPointer(event) {
    if (interaction.mode === "none" || interaction.pointerId !== event.pointerId) {
      return;
    }

    if (interaction.mode === "pan") {
      try {
        graphCanvas.releasePointerCapture(event.pointerId);
      } catch (error) {}
      const hadMove = interaction.moved;
      clearInteraction();
      updateCanvasCursor();
      if (!hadMove) {
        updateHover(canvasPoint(event));
      }
      drawGraph();
      return;
    }

    if (interaction.mode === "node" && interaction.node) {
      const pickedNode = interaction.node;
      const hadMove = interaction.moved;
      try {
        graphCanvas.releasePointerCapture(event.pointerId);
      } catch (error) {}
      clearInteraction();
      updateCanvasCursor();

      if (!hadMove) {
        selectPaper(pickedNode.id, "graph", { relayout: false });
        return;
      }

      state.selectedPaperId = pickedNode.id;
      state.hoveredPaperId = pickedNode.id;
      graphNodes.forEach((node) => {
        node.homeX = node.x;
        node.homeY = node.y;
      });
      startSettleMotion(22);
      drawGraph();
    }
  }

  graphCanvas.addEventListener("pointerup", finishPointer);
  graphCanvas.addEventListener("pointercancel", finishPointer);

  graphCanvas.addEventListener("pointerleave", () => {
    if (interaction.mode !== "none") {
      return;
    }
    if (state.hoveredPaperId !== null) {
      state.hoveredPaperId = null;
      drawGraph();
    }
  });

  graphCanvas.addEventListener(
    "wheel",
    (event) => {
      const point = canvasPoint(event);
      const before = screenToWorld(point);
      const zoomFactor = Math.exp(-event.deltaY * 0.0014);
      const nextScale = clamp(viewport.scale * zoomFactor, viewport.minScale, viewport.maxScale);
      if (nextScale === viewport.scale) {
        return;
      }
      viewport.scale = nextScale;
      viewport.panX = point.x - before.x * viewport.scale;
      viewport.panY = point.y - before.y * viewport.scale;
      drawGraph();
      event.preventDefault();
    },
    { passive: false },
  );

  window.addEventListener("resize", () => {
    syncCanvasSize();
    drawGraph();
  });

  initTheme();
  resetViewport();
  buildGraphData();
  startHubHeartbeat();
  render();
})();
