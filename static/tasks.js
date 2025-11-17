// Task kanban + project header
(function () {
  const columns = {
    todo: document.getElementById("col-todo"),
    "in-progress": document.getElementById("col-in-progress"),
    done: document.getElementById("col-done"),
    later: document.getElementById("col-later"),
  };
  const cardTemplate = document.getElementById("kanban-card-template");
  const form = document.getElementById("task-form");
  const metricTotal = document.getElementById("metric-total");
  const metricDone = document.getElementById("metric-done");
  const metricTodo = document.getElementById("metric-todo");
  const metricPct = document.getElementById("metric-pct");
  const nameEl = document.getElementById("project-name");
  const descEl = document.getElementById("project-desc");
  const taskResourceFormSelect = document.getElementById("task-resource-select");
  const collapsedState = new Map();
  let draggingTaskId = null;
  let resources = [];

  async function loadProject() {
    try {
      const project = await window.api(`/api/projects/${window.PROJECT_ID}`);
      nameEl.textContent = project.name;
      descEl.textContent = project.description || "";
    } catch (err) {
      nameEl.textContent = "Project not found";
      descEl.textContent = err.message;
    }
  }

  async function loadTasks() {
    Object.values(columns).forEach((col) => (col.innerHTML = ""));
    try {
      const tasks = await window.api(`/api/projects/${window.PROJECT_ID}/tasks`);
      if (!tasks.length) {
        Object.values(columns).forEach((col) => (col.innerHTML = '<p class="muted">No tasks yet.</p>'));
      }
      let doneCount = 0;
      for (const task of tasks) {
        if (task.status === "done") doneCount++;
        renderTask(task);
      }
      const total = tasks.length;
      const todo = total - doneCount;
      const pct = total ? `${Math.round((doneCount / total) * 100)}%` : "0%";
      metricTotal.textContent = total;
      metricDone.textContent = doneCount;
      metricTodo.textContent = todo;
      metricPct.textContent = pct;
    } catch (err) {
      metricTotal.textContent = "0";
      metricDone.textContent = "0";
      metricTodo.textContent = "0";
      metricPct.textContent = "-";
    }
  }

  function formatAssignee(resourceId) {
    if (!resourceId) return "Unassigned";
    const res = resources.find((r) => String(r.id) === String(resourceId));
    if (res) return `${res.name} (${res.status})`;
    return `Resource #${resourceId}`;
  }

  function renderTask(task) {
    const node = cardTemplate.content.cloneNode(true);
    const card = node.querySelector(".kanban-card");
    const collapseToggle = node.querySelector(".collapse-toggle");
    const collapsedDue = node.querySelector(".collapsed-due");
    const title = node.querySelector(".kanban-title");
    const parent = node.querySelector(".kanban-parent");
    const resourceSel = node.querySelector(".task-resource");
    const desc = node.querySelector(".task-desc");
    const due = node.querySelector(".task-due");
    const assigneeDisplay = node.querySelector(".task-assignee-display");
    const descDisplay = node.querySelector(".task-desc-display");
    const saveBtn = node.querySelector(".task-save");
    const deleteBtn = node.querySelector(".task-delete");
    const dueField = node.querySelector(".due-field");
    const dueEmpty = node.querySelector(".due-empty");
    const setDueBtn = node.querySelector(".set-due");
    const metaPanel = node.querySelector(".meta-panel");
    const metaToggle = node.querySelector(".meta-toggle");

    title.textContent = task.title;
    parent.textContent = task.parent_id ? `Parent #${task.parent_id}` : "";
    setResourceOptions(resourceSel, task.resource_id);
    if (desc) desc.value = task.description || "";
    if (assigneeDisplay) assigneeDisplay.textContent = formatAssignee(task.resource_id);
    if (descDisplay) descDisplay.textContent = (task.description || "").trim() || "No description";
    if (resourceSel && assigneeDisplay) {
      resourceSel.addEventListener("change", () => {
        assigneeDisplay.textContent = formatAssignee(resourceSel.value || "");
      });
    }

    if (desc && descDisplay) {
      desc.addEventListener("input", () => {
        descDisplay.textContent = desc.value.trim() || "No description";
      });
    }
    if (task.due_date) {
      due.value = task.due_date;
      due.classList.remove("no-due");
      dueField.style.display = "grid";
      dueEmpty.style.display = "none";
      if (collapsedDue) {
        collapsedDue.textContent = task.due_date;
        collapsedDue.hidden = false;
      }
    } else {
      due.value = "";
      due.classList.add("no-due");
      dueField.style.display = "none";
      dueEmpty.style.display = "flex";
      if (collapsedDue) collapsedDue.hidden = true;
    }

    saveBtn.addEventListener("click", async () => {
      try {
        const payload = {
          due_date: due.value,
          resource_id: resourceSel.value || null,
          description: desc ? desc.value : "",
        };
        await window.api(`/api/tasks/${task.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        saveBtn.textContent = "Saved";
        await loadTasks();
        setTimeout(() => (saveBtn.textContent = "Save"), 1200);
      } catch (err) {
        alert(`Unable to update: ${err.message}`);
      }
    });

    setDueBtn.addEventListener("click", () => {
      dueField.style.display = "grid";
      dueEmpty.style.display = "none";
      due.focus();
    });

    deleteBtn.addEventListener("click", async () => {
      if (!confirm("Delete this task?")) return;
      try {
        await fetch(`/api/tasks/${task.id}`, { method: "DELETE" });
        await loadTasks();
      } catch (err) {
        alert(`Unable to delete: ${err.message}`);
      }
    });

    card.dataset.taskId = task.id;
    if (metaToggle && metaPanel) {
      metaToggle.addEventListener("click", () => {
        const isOpen = metaPanel.classList.toggle("open");
        metaToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      });
    }

    const initialCollapsed = collapsedState.get(task.id) || false;
    applyCollapsedState(card, collapseToggle, metaPanel, metaToggle, initialCollapsed);

    if (collapseToggle) {
      collapseToggle.addEventListener("click", () => {
        const next = !card.classList.contains("collapsed");
        collapsedState.set(task.id, next);
        applyCollapsedState(card, collapseToggle, metaPanel, metaToggle, next);
      });
    }

    card.addEventListener("dragstart", () => {
      draggingTaskId = task.id;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      draggingTaskId = null;
      card.classList.remove("dragging");
      clearDragOver();
    });

    const col = columns[task.status] || columns.todo;
    col.appendChild(node);
  }

  function setResourceOptions(selectEl, selectedId) {
    if (!selectEl) return;
    selectEl.innerHTML = "";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Unassigned";
    selectEl.append(opt);
    resources.forEach((res) => {
      const o = document.createElement("option");
      o.value = res.id;
      o.textContent = `${res.name} (${res.status})`;
      if (String(selectedId || "") === String(res.id)) o.selected = true;
      selectEl.append(o);
    });
    if (!selectEl.value) {
      const admin = resources.find((r) => (r.name || "").toLowerCase() === "admin");
      if (admin) selectEl.value = String(admin.id);
    }
  }

  Object.entries(columns).forEach(([status, col]) => {
    col.addEventListener("dragover", (e) => {
      e.preventDefault();
      col.classList.add("drag-over");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drag-over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drag-over");
      if (!draggingTaskId) return;
      try {
        await window.api(`/api/tasks/${draggingTaskId}`, { method: "PATCH", body: JSON.stringify({ status }) });
        await loadTasks();
      } catch (err) {
        alert(`Unable to move task: ${err.message}`);
      }
    });
  });

  function clearDragOver() {
    Object.values(columns).forEach((col) => col.classList.remove("drag-over"));
  }

  function applyCollapsedState(card, collapseToggle, metaPanel, metaToggle, collapsed) {
    card.classList.toggle("collapsed", collapsed);
    if (collapseToggle) {
      collapseToggle.textContent = collapsed ? "+" : "−";
      collapseToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      collapseToggle.title = collapsed ? "Expand card" : "Collapse card";
    }
    if (collapsed && metaPanel) {
      metaPanel.classList.remove("open");
      if (metaToggle) metaToggle.setAttribute("aria-expanded", "false");
    }
  }

  function setupTaskForm() {
    if (!form) return;
    setResourceOptions(taskResourceFormSelect, "");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      if (!data.title) return;
      try {
        await window.api(`/api/projects/${window.PROJECT_ID}/tasks`, { method: "POST", body: JSON.stringify(data) });
        form.reset();
        await loadTasks();
      } catch (err) {
        alert(`Unable to add task: ${err.message}`);
      }
    });
  }

  function handleResourceUpdate(list) {
    resources = list || [];
    setResourceOptions(taskResourceFormSelect, "");
    // Refresh cards to reflect names/status in dropdowns
    loadTasks();
  }

  window.addEventListener("resources:update", (e) => handleResourceUpdate(e.detail));

  window.initTasks = function initTasks() {
    loadProject();
    loadTasks();
    setupTaskForm();
  };
})();
