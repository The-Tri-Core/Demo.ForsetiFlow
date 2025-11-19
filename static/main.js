const projectsEl = document.getElementById("projects");
const projectTemplate = document.getElementById("project-template");
const statProjects = document.getElementById("stat-projects");
const statTasks = document.getElementById("stat-tasks");
const statProgress = document.getElementById("stat-progress");
const projectForm = document.getElementById("project-form");

if (projectForm) {
  projectForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(projectForm).entries());
    if (!data.name) return;
    try {
      await api("/api/projects", { method: "POST", body: JSON.stringify(data) });
      projectForm.reset();
      await loadProjects();
    } catch (err) {
      alert(`Unable to create project: ${err.message}`);
    }
  });
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || res.statusText);
  }
  return res.json();
}

function updateHeroStats(projectCount, taskCount, doneCount) {
  if (statProjects) statProjects.textContent = projectCount;
  if (statTasks) statTasks.textContent = taskCount;
  if (statProgress) {
    if (!taskCount) {
      statProgress.textContent = "-";
    } else {
      const pct = Math.round((doneCount / taskCount) * 100);
      statProgress.textContent = `${pct}%`;
    }
  }
}

async function loadProjects() {
  projectsEl.innerHTML = "";
  const stats = { tasks: 0, done: 0 };
  try {
    const projects = await api("/api/projects");
    updateHeroStats(projects.length, 0, 0);
    if (!projects.length) {
      projectsEl.innerHTML = '<p class="muted">No projects yet. Add one above.</p>';
      return;
    }
    for (const project of projects) {
      await renderProject(project, stats);
    }
    updateHeroStats(projects.length, stats.tasks, stats.done);
  } catch (err) {
    console.error(err);
    projectsEl.innerHTML = `<p class="error">Failed to load projects: ${err.message}</p>`;
  }
}

async function renderProject(project, stats) {
  const node = projectTemplate.content.cloneNode(true);
  const link = node.querySelector(".project-link");
  if (link) {
    link.textContent = project.name;
  }
  node.querySelector(".project-desc").textContent = project.description || "No description";
  node.querySelector(".project-id").textContent = `ID ${project.id}`;

  const metrics = await loadTaskMetrics(project.id, stats);
  const { total, done, todo, pct } = metrics;
  node.querySelector(".metric-total").textContent = total;
  node.querySelector(".metric-done").textContent = done;
  node.querySelector(".metric-todo").textContent = todo;
  node.querySelector(".metric-pct").textContent = pct;

  const flowSelect = node.querySelector(".flow-select");
  const flows = {
    min: `/projects/${project.id}/dashboard?flow=min`,
    full: `/projects/${project.id}`,
  };
  const prefKey = `pm_flow_pref_${project.id}`;
  const saved = localStorage.getItem(prefKey) || "min";
  if (flowSelect) {
    flowSelect.value = flows[saved] ? saved : "min";
    flowSelect.addEventListener("change", () => {
      const choice = flowSelect.value;
      localStorage.setItem(prefKey, choice);
      if (link) link.href = flows[choice] || flows.min;
    });
  }
  if (link) {
    const initialChoice = flowSelect ? flowSelect.value : saved;
    link.href = flows[initialChoice] || flows.min;
  }

  projectsEl.appendChild(node);
}

async function loadTaskMetrics(projectId, stats) {
  try {
    const tasks = await api(`/api/projects/${projectId}/tasks`);
    if (stats) {
      stats.tasks += tasks.length;
      stats.done += tasks.filter((t) => t.status === "done").length;
    }
    let doneCount = 0;
    for (const task of tasks) {
      if (task.status === "done") doneCount++;
    }
    const total = tasks.length;
    const todo = total - doneCount;
    const pct = total ? `${Math.round((doneCount / total) * 100)}%` : "0%";
    return { total, done: doneCount, todo, pct };
  } catch (err) {
    console.error(err);
    return { total: 0, done: 0, todo: 0, pct: "-" };
  }
}

document.getElementById("reload").addEventListener("click", loadProjects);

loadProjects();
