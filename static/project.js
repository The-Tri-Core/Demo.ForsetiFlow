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
    const quickTaskBtn = document.getElementById("quick-task-btn");
    const chips = [document.getElementById("tool-list"), document.getElementById("tool-list-top")];
    const toolOptions = [
      { key: "tasks", label: "Task form" },
      { key: "kanban", label: "Kanban board" },
      { key: "roadmap", label: "Roadmap" },
      { key: "backlog", label: "Backlog" },
      { key: "sprints", label: "Sprints" },
      { key: "resources", label: "Resources" },
    ];

    let activeTools = [];
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
      } else {
        if (emptyState) emptyState.classList.remove("hidden");
        if (sections) sections.classList.add("hidden");
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
          activeTools.forEach((t) => {
            if (!t.archived) instantiateTool(t);
          });
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

    function showTools() {
      refreshVisibility();
      if (window.initTasks) window.initTasks();
      if (window.initBacklogs) window.initBacklogs();
      if (window.initSprints) window.initSprints();
      if (window.initResources) window.initResources();
    }

    function removeTool(idx) {
      const removed = activeTools.splice(idx, 1)[0];
      renderChips();
      if (removed) {
        const stillExists = activeTools.some((t) => t.key === removed.key && !t.archived);
        if (!stillExists) {
          const target = sections?.querySelector(`[data-tool="${removed.key}"]`);
          if (target) target.classList.add("hidden-tool");
        }
      }
      refreshVisibility();
      saveTools();
    }

    function archiveTool(idx) {
      const tool = activeTools[idx];
      if (!tool) return;
      tool.archived = true;
      renderChips();
      const hasActiveForKey = activeTools.some((t) => t.key === tool.key && !t.archived);
      if (!hasActiveForKey) {
        const target = sections?.querySelector(`[data-tool="${tool.key}"]`);
        if (target) target.classList.add("hidden-tool");
      }
      refreshVisibility();
      saveTools();
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
        instantiateTool(tool);
        refreshVisibility();
        saveTools();
        close();
      });
    }

    function instantiateTool(tool) {
      if (!tool || tool.archived) return;
      const { key, label } = tool;
      if (!sections) return;
      const target = sections.querySelector(`[data-tool="${key}"]`);
      if (!target) return;
      if (target.classList.contains("hidden-tool")) {
        target.classList.remove("hidden-tool");
      }
      const headerTitle = target.querySelector(".panel-head h2");
      if (headerTitle && !target.dataset.named) {
        headerTitle.textContent = label;
        target.dataset.named = "true";
      }

      const head = target.querySelector(".panel-head") || target;
      if (head && !head.querySelector(".tool-close")) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "tool-close";
        btn.dataset.toolKey = key;
        btn.textContent = "×";
        head.appendChild(btn);
        btn.addEventListener("click", () => {
          const idx = getFirstIndexForKey(key);
          if (idx >= 0) confirmToolAction(idx);
        });
      }

      // Only initialize each module once
      if (!instantiated.has(key)) {
        if (key === "tasks" && window.initTasks) window.initTasks();
        if (key === "kanban" && window.initTasks) window.initTasks();
        if (key === "backlog" && window.initBacklogs) window.initBacklogs();
        if (key === "sprints" && window.initSprints) window.initSprints();
        if (key === "resources" && window.initResources) window.initResources();
        // roadmap static
        instantiated.add(key);
      }
    }

    if (addToolBtn) addToolBtn.addEventListener("click", addToolSelection);
    if (addToolBtnTop) addToolBtnTop.addEventListener("click", addToolSelection);
    loadSavedTools();
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
      if (!activeTools.length) {
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

      activeTools.forEach((tool) => {
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

  function openQuickTaskModal() {
    const triggerStatus = openQuickTaskModal.targetStatus || "todo";
    openQuickTaskModal.targetStatus = null;

    const modal = document.createElement("div");
    modal.className = "modal-backdrop";
    modal.innerHTML = `
      <div class="modal">
        <header>
          <h3>Add task</h3>
          <button class="pill ghost tiny" type="button" id="quick-task-close">Close</button>
        </header>
        <form id="quick-task-form" class="form-grid">
          <label>
            <span>Name</span>
            <input type="text" name="title" required placeholder="Task name" />
          </label>
          <label>
            <span>Status</span>
            <input type="text" name="status" value="${triggerStatus}" readonly />
          </label>
          <label>
            <span>Description</span>
            <textarea name="description" rows="3" placeholder="Optional description"></textarea>
          </label>
          <label>
            <span>Assignee</span>
            <select name="resource_id" id="quick-task-resource">
              <option value="">Unassigned</option>
            </select>
          </label>
          <label>
            <span>Due date</span>
            <input type="date" name="due_date" />
          </label>
          <div class="actions">
            <button type="button" class="pill ghost" id="quick-task-discard">Discard</button>
            <button type="submit" class="pill primary">Save</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(modal);

    function close() {
      modal.remove();
    }

    modal.addEventListener("click", (e) => {
      if (e.target === modal) close();
    });
    modal.querySelector("#quick-task-close")?.addEventListener("click", close);
    modal.querySelector("#quick-task-discard")?.addEventListener("click", close);

    populateQuickTaskResources(modal.querySelector("#quick-task-resource"));

    const form = modal.querySelector("#quick-task-form");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = new FormData(form);
        const title = (data.get("title") || "").trim();
        if (!title) return;
        const payload = Object.fromEntries(data.entries());
        if (!payload.resource_id) payload.resource_id = null;
        try {
          await window.api(`/api/projects/${window.PROJECT_ID}/tasks`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
          close();
        } catch (err) {
          alert(`Unable to add task: ${err.message}`);
        }
      });
    }
  }

  async function populateQuickTaskResources(selectEl) {
    if (!selectEl) return;
    try {
      const resources = await window.api(`/api/resources/${window.PROJECT_ID}`);
      selectEl.innerHTML = '<option value="">Unassigned</option>';
      resources.forEach((r) => {
        const opt = document.createElement("option");
        opt.value = r.id;
        opt.textContent = `${r.name} (${r.status})`;
        selectEl.append(opt);
      });
    } catch (e) {
      // ignore
    }
  }

  // Default legacy initializer
  window.initProjectPage = window.initProjectDashboard;
})();








    document.querySelectorAll(".add-task-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const status = btn.dataset.status || "todo";
        openQuickTaskModal.targetStatus = status;
        openQuickTaskModal();
      });
    });


