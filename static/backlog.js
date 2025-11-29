// Backlog CRUD, filters, drag with resource support
(function () {
  const backlogColumns = {
    todo: "To do",
    "in-progress": "In Progress",
    later: "Later Development",
  };
  const state = { items: [], filters: { status: "", priority: "", tag: "" } };
  // Single-user mode: no resources/assignees
  let resources = [];

  async function loadBacklogs() {
    try {
      const items = await window.api(`/api/backlogs/${window.PROJECT_ID}`);
      state.items = items;
      renderBacklogs();
    } catch (err) {
      const list = document.getElementById("backlog-list");
      if (list) list.innerHTML = `<p class="error">Failed to load backlogs: ${err.message}</p>`;
    }
  }

  function renderBacklogs() {
    const list = document.getElementById("backlog-list");
    if (!list) return;
    list.innerHTML = "";
    const { status, priority, tag } = state.filters;
    const tagLower = tag.trim().toLowerCase();
    const filtered = state.items.filter((item) => {
      if (status && item.status !== status) return false;
      if (priority && item.priority !== priority) return false;
      if (tagLower) {
        const tags = (item.tags || "").toLowerCase();
        if (!tags.split(",").some((t) => t.trim() === tagLower)) return false;
      }
      return true;
    });
    if (!filtered.length) {
      list.innerHTML = '<p class="muted">No backlog items yet.</p>';
      return;
    }
    filtered.forEach((item) => {
      const card = document.createElement("div");
      card.className = "backlog-item";
      card.draggable = true;
      card.dataset.id = item.id;
      card.dataset.status = item.status;

      const header = document.createElement("header");
      const title = document.createElement("div");
      title.textContent = item.title;
      const actions = document.createElement("div");
      actions.className = "backlog-actions";
      const editBtn = document.createElement("button");
      editBtn.className = "pill ghost";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => editBacklog(item));
      const delBtn = document.createElement("button");
      delBtn.className = "pill danger";
      delBtn.textContent = "✕";
      delBtn.title = "Delete";
      delBtn.addEventListener("click", () => deleteBacklog(item.id));
      actions.append(editBtn, delBtn);
      header.append(title, actions);

      const meta = document.createElement("div");
      meta.className = "backlog-meta";
      const pBadge = document.createElement("span");
      pBadge.className = `badge priority-${item.priority}`;
      pBadge.textContent = item.priority;
      const sBadge = document.createElement("span");
      sBadge.className = `badge status-${item.status}`;
      sBadge.textContent = backlogColumns[item.status] || item.status;
      meta.append(pBadge, sBadge);

      const prioritySel = document.createElement("select");
      ["high", "medium", "low"].forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        if (p === item.priority) opt.selected = true;
        prioritySel.append(opt);
      });
      prioritySel.addEventListener("change", () => quickUpdate(item.id, { priority: prioritySel.value }));

      const statusSel = document.createElement("select");
      [
        { value: "todo", label: "To do" },
        { value: "in-progress", label: "In Progress" },
        { value: "later", label: "Later Development" },
      ].forEach(({ value, label }) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        if (value === item.status) opt.selected = true;
        statusSel.append(opt);
      });
      statusSel.addEventListener("change", () => quickUpdate(item.id, { status: statusSel.value }));

      const resWrap = document.createElement("div");
      resWrap.className = "backlog-meta";
      const resLabel = document.createElement("span");
      resLabel.className = "badge";
      resLabel.textContent = "Owner: You";
      resWrap.append(resLabel);

      const tagsWrap = document.createElement("div");
      tagsWrap.className = "backlog-meta";
      const tags = (item.tags || "").split(",").map((t) => t.trim()).filter(Boolean);
      if (tags.length) {
        tags.forEach((t) => {
          const tagEl = document.createElement("span");
          tagEl.className = "tag";
          tagEl.textContent = t;
          tagsWrap.append(tagEl);
        });
      } else {
        const noTag = document.createElement("span");
        noTag.className = "muted";
        noTag.textContent = "No tags";
        tagsWrap.append(noTag);
      }

      const tagInput = document.createElement("input");
      tagInput.type = "text";
      tagInput.placeholder = "Tags (comma)";
      tagInput.value = item.tags || "";
      tagInput.addEventListener("change", () => quickUpdate(item.id, { tags: tagInput.value }));

      const parentInfo = document.createElement("div");
      parentInfo.className = "muted";
      parentInfo.textContent = item.parent_id ? `Parent #${item.parent_id}` : "No parent";
      const parentInput = document.createElement("input");
      parentInput.type = "number";
      parentInput.min = "1";
      parentInput.placeholder = "Parent ID";
      parentInput.value = item.parent_id || "";
      parentInput.addEventListener("change", () => quickUpdate(item.id, { parent_id: parentInput.value || null }));

      card.append(header, meta, prioritySel, statusSel, resWrap, tagsWrap, tagInput, parentInfo, parentInput);

      card.addEventListener("dragstart", () => {
        card.classList.add("dragging");
        card.dataset.dragging = "true";
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("dragging");
        delete card.dataset.dragging;
      });

      list.append(card);
    });
  }

  async function addBacklog(data) {
    const payload = Object.fromEntries(data.entries());
    try {
      await window.api(`/api/backlogs/${window.PROJECT_ID}`, { method: "POST", body: JSON.stringify(payload) });
      await loadBacklogs();
    } catch (err) {
      alert(`Unable to add backlog: ${err.message}`);
    }
  }

  async function quickUpdate(id, payload) {
    try {
      await window.api(`/api/backlog/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      await loadBacklogs();
    } catch (err) {
      alert(`Unable to update backlog: ${err.message}`);
    }
  }

  async function editBacklog(item) {
    const title = prompt("Title", item.title);
    if (title === null || !title.trim()) return;
    const priority = prompt("Priority (high/medium/low)", item.priority) || item.priority;
    const status = prompt("Status (todo/in-progress/later)", item.status) || item.status;
    const tags = prompt("Tags (comma-separated)", item.tags || "") || item.tags;
    await quickUpdate(item.id, { title, priority, status, tags });
  }

  async function deleteBacklog(id) {
    if (!confirm("Delete this backlog item?")) return;
    try {
      await fetch(`/api/backlog/${id}`, { method: "DELETE" });
      await loadBacklogs();
    } catch (err) {
      alert(`Unable to delete: ${err.message}`);
    }
  }

  function setupFilters() {
    const statusSel = document.getElementById("backlog-filter-status");
    const prioritySel = document.getElementById("backlog-filter-priority");
    const tagInput = document.getElementById("backlog-filter-tag");
    if (!statusSel || !prioritySel || !tagInput) return;
    statusSel.addEventListener("change", () => {
      state.filters.status = statusSel.value;
      renderBacklogs();
    });
    prioritySel.addEventListener("change", () => {
      state.filters.priority = prioritySel.value;
      renderBacklogs();
    });
    tagInput.addEventListener("input", () => {
      state.filters.tag = tagInput.value;
      renderBacklogs();
    });
  }

  function setupDnD() {
    const list = document.getElementById("backlog-list");
    if (!list) return;
    list.addEventListener("dragover", (e) => e.preventDefault());
    list.addEventListener("drop", (e) => {
      e.preventDefault();
      const dragging = list.querySelector('[data-dragging="true"]');
      if (!dragging) return;
      const rect = list.getBoundingClientRect();
      const dropY = e.clientY - rect.top;
      const items = Array.from(list.children).filter((c) => c !== dragging);
      const insertBefore = items.find((card) => dropY < card.offsetTop - list.offsetTop + card.offsetHeight / 2);
      if (insertBefore) {
        list.insertBefore(dragging, insertBefore);
      } else {
        list.appendChild(dragging);
      }
    });
  }

  function setupForm() {
    const backlogForm = document.getElementById("backlog-form");
    if (!backlogForm) return;
    const resSelect = document.getElementById("backlog-resource-select");
    if (resSelect) {
      resSelect.classList.add("hidden");
    }
    backlogForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = new FormData(backlogForm);
      if (!data.get("title")) return;
      await addBacklog(data);
      backlogForm.reset();
    });
  }

  function setResourceOptions() { /* no-op single-user */ }

  function resourceName() { return "You"; }

  function onResourcesUpdate() {
    renderBacklogs();
  }

  window.addEventListener("resources:update", (e) => onResourcesUpdate(e.detail));

  window.initBacklogs = function initBacklogs() {
    loadBacklogs();
    setupFilters();
    setupForm();
    setupDnD();
  };
})();
