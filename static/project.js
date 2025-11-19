// Orchestrator for project pages (overview + dashboard)
(function () {
  const selectors = {
    tasks: document.getElementById("overview-tasks"),
    done: document.getElementById("overview-done"),
    backlog: document.getElementById("overview-backlog"),
    sprints: document.getElementById("overview-sprints"),
    activeSprints: document.getElementById("overview-active"),
    resources: document.getElementById("overview-resources"),
    health: document.getElementById("overview-health"),
  };

  function setText(el, value) {
    if (el) el.textContent = value;
  }

  async function loadOverview() {
    try {
      const [tasks, backlogs, sprints, resources] = await Promise.all([
        window.api(`/api/projects/${window.PROJECT_ID}/tasks`).catch(() => []),
        window.api(`/api/backlogs/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/sprints/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/resources/${window.PROJECT_ID}`).catch(() => []),
      ]);

      const totalTasks = tasks.length;
      const doneTasks = tasks.filter((t) => t.status === "done").length;
      const progressPct = totalTasks ? Math.round((doneTasks / totalTasks) * 100) : 0;
      const activeSprintCount = sprints.filter((s) => s.status === "active").length;

      setText(selectors.tasks, totalTasks);
      setText(selectors.done, `${doneTasks} done (${progressPct}% )`);
      setText(selectors.backlog, backlogs.length);
      setText(selectors.sprints, sprints.length);
      setText(selectors.activeSprints, activeSprintCount);
      setText(selectors.resources, resources.length || "0");
      setText(selectors.health, progressPct >= 70 ? "On track" : progressPct >= 30 ? "Progressing" : "Getting started");
    } catch (err) {
      setText(selectors.tasks, "-");
      setText(selectors.done, "-");
      setText(selectors.backlog, "-");
      setText(selectors.sprints, "-");
      setText(selectors.activeSprints, "-");
      setText(selectors.resources, "-");
      setText(selectors.health, "Unknown");
    }
  }

  // Dashboard keeps full toolset: tasks, backlogs, sprints, resources
  window.initProjectDashboard = function initProjectDashboard() {
    const addToolBtn = document.getElementById("add-tool-btn");
    const addToolBtnTop = document.getElementById("add-tool-btn-top");
    const emptyState = document.getElementById("tools-empty");
    const sections = document.getElementById("tool-sections");
    const cardPanel = document.getElementById("tool-card-panel");
    const cardList = document.getElementById("tool-card-list");
    const inlineWrapper = document.getElementById("inline-tool-wrapper");
    const chips = [document.getElementById("tool-list"), document.getElementById("tool-list-top")];
    const flowMode = new URLSearchParams(window.location.search).get("flow") || "min";
    const isFullFlow = flowMode === "full";
    const toolOptions = [
      { key: "tasks", label: "Task form" },
      { key: "kanban", label: "Kanban board" },
      { key: "roadmap", label: "Roadmap" },
      { key: "backlog", label: "Backlog" },
      { key: "sprints", label: "Sprints" },
      { key: "resources", label: "Resources" },
    ];
    const toolDescriptions = {
      tasks: "Capture tasks quickly and assign an owner.",
      kanban: "Visualise progress across swimlanes.",
      roadmap: "Outline upcoming quarters and initiatives.",
      backlog: "Collect ideas and future features.",
      sprints: "Plan focused iterations and track velocity.",
      resources: "Monitor availability across the team.",
    };

    let activeTools = [];
    let renderNonce = 0;
    const instantiated = new Set();
    const toolStorageKey = window.PROJECT_ID ? `pm_tools_${window.PROJECT_ID}` : null;

    function saveTools() {
      if (!toolStorageKey) return;
      try {
        localStorage.setItem(toolStorageKey, JSON.stringify(activeTools));
      } catch (e) {
        // ignore storage errors
      }
    }

    function refreshVisibility() {
      const hasVisible = activeTools.some((t) => !t.archived);
      if (hasVisible) {
        if (emptyState) emptyState.classList.add("hidden");
        if (sections) sections.classList.remove("hidden");
        if (isFullFlow) {
          cardPanel?.classList.remove("hidden");
          inlineWrapper?.classList.add("hidden");
        } else {
          cardPanel?.classList.add("hidden");
          inlineWrapper?.classList.remove("hidden");
        }
      } else {
        if (emptyState) emptyState.classList.remove("hidden");
        if (sections) sections.classList.add("hidden");
        cardPanel?.classList.add("hidden");
        inlineWrapper?.classList.add("hidden");
      }
    }

    function loadSavedTools() {
      if (!toolStorageKey) return;
      try {
        const raw = localStorage.getItem(toolStorageKey);
        if (!raw) return;
        const list = JSON.parse(raw);
        if (Array.isArray(list) && list.length) {
          activeTools = list.filter((t) => t && t.key).map((t) => ({ ...t, archived: !!t.archived }));
          renderChips();
          refreshVisibility();
          if (isFullFlow) {
            renderToolCards();
          } else {
            activeTools.forEach((t) => {
              if (!t.archived) instantiateTool(t);
            });
          }
        }
      } catch (e) {
        // ignore parse errors
      }
    }

    function displayLabel(tool) {
      return tool.archived ? `${tool.label} (Archived)` : tool.label;
    }

    function renderChips() {
      const visible = activeTools.filter((t) => !t.archived);
      const template = (tool, idx) =>
        `<span class="tool-chip" data-idx="${idx}">
          <strong>${displayLabel(tool)}</strong>
          <button class="tool-close" type="button" aria-label="Remove ${displayLabel(tool)}" data-key="${tool.key}">X</button>
        </span>`;
      chips.forEach((list) => {
        if (!list) return;
        list.innerHTML = visible.map((t, i) => template(t, i)).join("");
        list.querySelectorAll(".tool-close").forEach((btn) =>
          btn.addEventListener("click", () => confirmToolAction(Number(btn.closest(".tool-chip").dataset.idx)))
        );
      });
    }

    function removeTool(idx) {
      const removed = activeTools.splice(idx, 1)[0];
      renderChips();
      refreshVisibility();
      saveTools();
      if (isFullFlow) {
        renderToolCards();
      } else if (removed) {
        hideToolSectionIfUnused(removed.key);
      }
    }

    function archiveTool(idx) {
      const tool = activeTools[idx];
      if (!tool) return;
      tool.archived = true;
      renderChips();
      refreshVisibility();
      saveTools();
      if (isFullFlow) {
        renderToolCards();
      } else {
        hideToolSectionIfUnused(tool.key);
      }
    }

    function getFirstIndexForKey(key) {
      let idx = activeTools.findIndex((t) => t.key === key && !t.archived);
      if (idx === -1) idx = activeTools.findIndex((t) => t.key === key);
      return idx;
    }

    function confirmToolAction(idx) {
      const tool = activeTools[idx];
      if (!tool) return;
      const toast = document.createElement("div");
      toast.className = "modal-backdrop";
      toast.innerHTML = `
        <div class="modal">
          <header><h3>Tool action</h3></header>
          <p class="muted">What would you like to do with ${displayLabel(tool)}?</p>
          <div class="actions">
            <button class="pill ghost" type="button" id="tool-archive">Archive</button>
            <button class="pill danger" type="button" id="tool-delete">Delete</button>
          </div>
        </div>`;
      document.body.appendChild(toast);

      function closeToast() {
        toast.remove();
      }

      toast.addEventListener("click", (e) => {
        if (e.target === toast) closeToast();
      });
      toast.querySelector("#tool-archive")?.addEventListener("click", () => {
        archiveTool(idx);
        closeToast();
      });
      toast.querySelector("#tool-delete")?.addEventListener("click", () => {
        closeToast();
        confirmDelete(idx);
      });
    }

    function confirmDelete(idx) {
      const tool = activeTools[idx];
      const modal = document.createElement("div");
      modal.className = "modal-backdrop";
      modal.innerHTML = `
        <div class="modal">
          <header><h3>Confirm delete</h3></header>
          <p class="muted">This cannot be undone. Delete ${tool ? displayLabel(tool) : "this tool"}?</p>
          <div class="actions">
            <button class="pill ghost" type="button" id="cancel-delete">Cancel</button>
            <button class="pill danger" type="button" id="confirm-delete">Delete forever</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      modal.addEventListener("click", (e) => {
        if (e.target === modal) modal.remove();
      });
      modal.querySelector("#cancel-delete")?.addEventListener("click", () => modal.remove());
      modal.querySelector("#confirm-delete")?.addEventListener("click", () => {
        removeTool(idx);
        modal.remove();
      });
    }

    function hideToolSectionIfUnused(key) {
      const stillExists = activeTools.some((t) => t.key === key && !t.archived);
      if (stillExists || !sections) return;
      const target = sections.querySelector(`[data-tool="${key}"]`);
      if (target) target.classList.add("hidden-tool");
    }

    function addToolSelection() {
      const modal = document.createElement("div");
      modal.className = "modal-backdrop";
      modal.innerHTML = `
        <div class="modal">
          <header>
            <div>
              <p class="eyebrow">Add tool</p>
              <h3>Select and name your tool</h3>
            </div>
            <button class="pill ghost tiny" type="button" id="close-modal">×</button>
          </header>
          <form id="tool-form">
            <label>
              <span>Custom name (optional)</span>
              <input type="text" name="label" placeholder="My Kanban, Roadmap 2, etc." />
            </label>
            <div class="tool-grid">
              ${toolOptions
                .map(
                  (opt, i) => `
                <label class="tool-option" data-key="${opt.key}">
                  <input type="radio" name="tool" value="${opt.key}" ${i === 0 ? "checked" : ""}/>
                  <strong>${opt.label}</strong>
                  <span class="muted small">Add another instance of ${opt.label.toLowerCase()}.</span>
                </label>`
                )
                .join("")}
            </div>
            <div class="actions">
              <button type="button" class="pill ghost" id="cancel-modal">Cancel</button>
              <button type="submit" class="pill primary">Add tool</button>
            </div>
          </form>
        </div>`;

      document.body.appendChild(modal);
      modal.querySelectorAll(".tool-option").forEach((opt) =>
        opt.addEventListener("click", () => {
          modal.querySelectorAll(".tool-option").forEach((o) => o.classList.remove("selected"));
          opt.classList.add("selected");
          const radio = opt.querySelector("input[type=radio]");
          if (radio) radio.checked = true;
        })
      );

      function close() {
        modal.remove();
      }

      modal.querySelector("#close-modal")?.addEventListener("click", close);
      modal.querySelector("#cancel-modal")?.addEventListener("click", close);
      modal.addEventListener("click", (e) => {
        if (e.target === modal) close();
      });

      modal.querySelector("#tool-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const data = new FormData(e.target);
        const key = data.get("tool") || "kanban";
        const label = (data.get("label") || "").trim() || toolOptions.find((o) => o.key === key)?.label || "Tool";
        const tool = { key, label, archived: false };
        activeTools.push(tool);
        renderChips();
        refreshVisibility();
        if (isFullFlow) {
          renderToolCards();
        } else {
          instantiateTool(tool);
        }
        saveTools();
        close();
      });
    }

    async function renderToolCards() {
      if (!cardList || !isFullFlow) return;
      const visible = activeTools.filter((t) => !t.archived);
      cardList.innerHTML = "";
      if (!visible.length) return;

      const loading = document.createElement("p");
      loading.className = "muted small";
      loading.textContent = "Loading tool insights…";
      cardList.appendChild(loading);

      const token = ++renderNonce;
      let metrics = null;
      try {
        metrics = await fetchToolMetrics();
      } catch (err) {
        metrics = null;
      }
      if (token !== renderNonce) return;
      cardList.innerHTML = "";

      activeTools.forEach((tool, idx) => {
        if (tool.archived) return;
        cardList.appendChild(createToolCard(tool, metrics, idx));
      });
    }

    async function fetchToolMetrics() {
      const [tasks, backlogs, sprints, resources] = await Promise.all([
        window.api(`/api/projects/${window.PROJECT_ID}/tasks`).catch(() => []),
        window.api(`/api/backlogs/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/sprints/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/resources/${window.PROJECT_ID}`).catch(() => []),
      ]);
      return {
        tasks: summarizeTasks(tasks),
        backlog: summarizeBacklog(backlogs),
        sprints: summarizeSprints(sprints),
        resources: summarizeResources(resources),
      };
    }

    function summarizeTasks(tasks) {
      const summary = { total: tasks.length, done: 0, inProgress: 0, todo: 0, later: 0 };
      tasks.forEach((task) => {
        const status = (task.status || "").toLowerCase();
        if (status === "done") summary.done += 1;
        else if (status === "in-progress") summary.inProgress += 1;
        else if (status === "later") summary.later += 1;
        else summary.todo += 1;
      });
      return summary;
    }

    function summarizeBacklog(backlogs) {
      const result = { total: backlogs.length, ready: 0 };
      backlogs.forEach((item) => {
        if ((item.status || "").toLowerCase() === "todo") result.ready += 1;
      });
      return result;
    }

    function summarizeSprints(sprints) {
      const result = { total: sprints.length, active: 0 };
      sprints.forEach((sprint) => {
        if ((sprint.status || "").toLowerCase() === "active") result.active += 1;
      });
      return result;
    }

    function summarizeResources(resources) {
      const result = { total: resources.length, free: 0 };
      resources.forEach((res) => {
        if ((res.status || "").toLowerCase() === "free") result.free += 1;
      });
      return result;
    }

    function getToolCardSummary(key, metrics) {
      const fallback = {
        detail: toolDescriptions[key] || "Open tool for deeper work.",
        metricLabel: "",
        metricValue: "",
      };
      if (!metrics) return fallback;

      switch (key) {
        case "tasks":
          return {
            detail: metrics.tasks.total
              ? `${metrics.tasks.todo} waiting • ${metrics.tasks.inProgress} in progress`
              : "No tasks captured yet.",
            metricLabel: "Total tasks",
            metricValue: String(metrics.tasks.total),
          };
        case "kanban":
          return {
            detail: metrics.tasks.total
              ? `${metrics.tasks.done} done • ${metrics.tasks.inProgress} in progress`
              : "No work on the board.",
            metricLabel: "Done",
            metricValue: metrics.tasks.total ? `${metrics.tasks.done}/${metrics.tasks.total}` : "0",
          };
        case "backlog":
          return {
            detail: metrics.backlog.total
              ? `${metrics.backlog.ready} ready for prioritising`
              : "No backlog items yet.",
            metricLabel: "Ideas",
            metricValue: String(metrics.backlog.total),
          };
        case "sprints":
          return {
            detail: metrics.sprints.total
              ? `${metrics.sprints.active} active sprint${metrics.sprints.active === 1 ? "" : "s"}`
              : "No sprints created.",
            metricLabel: "Total",
            metricValue: String(metrics.sprints.total),
          };
        case "resources":
          return {
            detail: metrics.resources.total
              ? `${metrics.resources.free} available right now`
              : "No resources added.",
            metricLabel: "People",
            metricValue: String(metrics.resources.total),
          };
        case "roadmap":
          return fallback;
        default:
          return fallback;
      }
    }

    function createToolCard(tool, metrics, idx) {
      const card = document.createElement("article");
      card.className = "tool-card glass";
      const summary = getToolCardSummary(tool.key, metrics);

      const info = document.createElement("div");
      info.className = "tool-card-info";

      const titleRow = document.createElement("div");
      titleRow.className = "tool-card-title";

      const heading = document.createElement("h3");
      heading.textContent = tool.label;

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "tool-card-remove";
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", () => confirmToolAction(idx));

      titleRow.append(heading, removeBtn);

      const desc = document.createElement("p");
      desc.textContent = summary.detail;

      info.append(titleRow, desc);

      const meta = document.createElement("div");
      meta.className = "tool-card-meta";

      if (summary.metricValue) {
        const number = document.createElement("div");
        number.className = "tool-card-number";
        const strong = document.createElement("strong");
        strong.textContent = summary.metricValue;
        const label = document.createElement("span");
        label.textContent = summary.metricLabel;
        number.append(strong, label);
        meta.append(number);
      }

      const openLink = document.createElement("a");
      openLink.className = "pill primary";
      openLink.href = `/projects/${window.PROJECT_ID}/tool/${tool.key}`;
      openLink.textContent = "Open tool";
      meta.append(openLink);

      card.append(info, meta);
      return card;
    }

    function instantiateTool(tool) {
      if (!tool || tool.archived || isFullFlow) return;
      if (!sections) return;
      const target = sections.querySelector(`[data-tool="${tool.key}"]`);
      if (!target) return;
      if (target.classList.contains("hidden-tool")) {
        target.classList.remove("hidden-tool");
      }
      const headerTitle = target.querySelector(".panel-head h2");
      if (headerTitle && !target.dataset.named) {
        headerTitle.textContent = tool.label;
        target.dataset.named = "true";
      }
      const head = target.querySelector(".panel-head") || target;
      if (head && !head.querySelector(".tool-close")) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tool-close";
        btn.dataset.toolKey = tool.key;
        btn.textContent = "×";
        head.appendChild(btn);
        btn.addEventListener("click", () => {
          const idx = getFirstIndexForKey(tool.key);
          if (idx >= 0) confirmToolAction(idx);
        });
      }
      if (!instantiated.has(tool.key)) {
        if (tool.key === "tasks" && window.initTasks) window.initTasks();
        if (tool.key === "kanban" && window.initTasks) window.initTasks();
        if (tool.key === "backlog" && window.initBacklogs) window.initBacklogs();
        if (tool.key === "sprints" && window.initSprints) window.initSprints();
        if (tool.key === "resources" && window.initResources) window.initResources();
        instantiated.add(tool.key);
      }
    }

    if (addToolBtn) addToolBtn.addEventListener("click", addToolSelection);
    if (addToolBtnTop) addToolBtnTop.addEventListener("click", addToolSelection);
    loadSavedTools();
    if (isFullFlow) {
      renderToolCards();
    }
  };

  // Overview shows high-level metrics only
  window.initProjectOverview = function initProjectOverview() {
    loadOverview();
    loadToolSummaries();
    setupArchiveViewer();
  };

  // Dedicated tool page initializer (shows one tool with summaries)
  window.initToolPage = function initToolPage() {
    const key = (window.TOOL_KEY || "").toLowerCase();
    const sections = document.querySelectorAll("[data-tool]");
    sections.forEach((section) => {
      const tool = section.dataset.tool;
      const shouldShow =
        key === tool ||
        (key === "kanban" && tool === "tasks") || // show task form with kanban
        (key === "tasks" && tool === "kanban");
      section.classList.toggle("hidden-tool", !shouldShow);
    });

    if (key === "tasks" || key === "kanban") {
      if (window.initTasks) window.initTasks();
      if (window.initResources) window.initResources();
    } else if (key === "backlog") {
      if (window.initResources) window.initResources();
      if (window.initBacklogs) window.initBacklogs();
    } else if (key === "sprints") {
      if (window.initSprints) window.initSprints();
    } else if (key === "resources") {
      if (window.initResources) window.initResources();
    } else if (key === "roadmap") {
      // static content only
    } else {
      // fallback: show all
      sections.forEach((section) => section.classList.remove("hidden-tool"));
      if (window.initTasks) window.initTasks();
      if (window.initBacklogs) window.initBacklogs();
      if (window.initSprints) window.initSprints();
      if (window.initResources) window.initResources();
    }
  };

  async function loadToolSummaries() {
    const grid = document.getElementById("tool-summary-grid");
    const empty = document.getElementById("tool-summary-empty");
    if (!grid || !empty) return;
    grid.innerHTML = "";

    try {
      const [tasks, backlogs, sprints, resources] = await Promise.all([
        window.api(`/api/projects/${window.PROJECT_ID}/tasks`).catch(() => []),
        window.api(`/api/backlogs/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/sprints/${window.PROJECT_ID}`).catch(() => []),
        window.api(`/api/resources/${window.PROJECT_ID}`).catch(() => []),
      ]);

      const stored = readStoredTools();
      const active = (stored || []).filter((t) => t && t.key && !t.archived);
      if (!active.length) {
        empty.style.display = "";
        return;
      }
      empty.style.display = "none";

      // Kanban summary
      const total = tasks.length;
      const done = tasks.filter((t) => t.status === "done").length;
      const pct = total ? Math.round((done / total) * 100) : 0;

      // Backlog summary
      const backlogTodo = backlogs.filter((b) => b.status === "todo").length;

      // Sprint summary
      const activeSprints = sprints.filter((s) => s.status === "active").length;

      // Resource summary
      const free = resources.filter((r) => r.status === "free").length;

      const summaryBuilders = {
        kanban: () => ({
          title: "Kanban",
          href: `/projects/${window.PROJECT_ID}/tool/kanban`,
          body: `${done} done of ${total}`,
          progress: pct,
          count: total,
        }),
        backlog: () => ({
          title: "Backlog",
          href: `/projects/${window.PROJECT_ID}/tool/backlog`,
          body: `Items ready: ${backlogTodo}`,
          progress: backlogs.length ? Math.round((backlogTodo / Math.max(backlogs.length, 1)) * 100) : 0,
          count: backlogs.length,
        }),
        sprints: () => ({
          title: "Sprints",
          href: `/projects/${window.PROJECT_ID}/tool/sprints`,
          body: `Active / total: ${activeSprints}/${sprints.length}`,
          progress: sprints.length ? Math.round((activeSprints / sprints.length) * 100) : 0,
          count: activeSprints,
        }),
        resources: () => ({
          title: "Resources",
          href: `/projects/${window.PROJECT_ID}/tool/resources`,
          body: `Available: ${free}`,
          progress: resources.length ? Math.round((free / resources.length) * 100) : 0,
          count: resources.length,
        }),
      };

      active.forEach((tool) => {
        const builder = summaryBuilders[tool.key];
        if (!builder) return;
        const info = builder();
        const card = document.createElement("div");
        card.className = "tool-summary-card";
        card.innerHTML = `
          <header><span class="pill badge">${info.title}</span><strong>${info.count}</strong></header>
          <p class="muted small">${info.body}</p>
          <div class="progress-bar"><div style="width:${info.progress}%;"></div></div>
          <a class="pill ghost" href="${info.href}">Open tool</a>
        `;
        grid.appendChild(card);
      });
    } catch (err) {
      // Keep defaults if fetch fails
      empty.style.display = "";
    }
  }

  function readStoredTools() {
    const key = window.PROJECT_ID ? `pm_tools_${window.PROJECT_ID}` : null;
    if (!key) return [];
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return [];
      const list = JSON.parse(raw);
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  function setupArchiveViewer() {
    const btn = document.getElementById("show-archived-tools");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const stored = readStoredTools();
      const archived = stored.filter((t) => t && t.archived);
      const modal = document.createElement("div");
      modal.className = "modal-backdrop";
      modal.innerHTML = `
        <div class="modal">
          <header>
            <h3>Archived tools</h3>
            <button class="pill ghost tiny" type="button" id="close-archived">Close</button>
          </header>
          ${archived.length ? `<ul class="feature-list compact">${archived.map((t) => `<li>${t.label || t.key}</li>`).join("")}</ul>` : `<p class="muted">No archived tools.</p>`}
        </div>`;
      document.body.appendChild(modal);
      modal.addEventListener("click", (e) => {
        if (e.target === modal || e.target.id === "close-archived") modal.remove();
      });
    });
  }

  // Default legacy initializer
  window.initProjectPage = window.initProjectDashboard;
})();
