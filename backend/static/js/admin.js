(() => {
  "use strict";

  const ROLE_LABELS = {
    actor: "актёр",
    operator: "оператор",
  };

  const COMPLETION_TYPE_LABELS = {
    actor: "отмечает актёр",
    answer: "вводит команда",
    checkbox: "подтверждает команда",
    manual_review: "на проверке у оператора",
  };

  const appScreen = document.getElementById("admin-app-screen");
  const headerNameEl = document.getElementById("admin-header-name");
  const logoutButton = document.getElementById("admin-logout-button");

  const panelTeams = document.getElementById("admin-panel-teams");
  const panelDetail = document.getElementById("admin-panel-team-detail");

  const teamListEl = document.getElementById("admin-team-list");
  const teamListEmptyEl = document.getElementById("admin-team-list-empty");

  const backButton = document.getElementById("admin-team-back-button");
  const detailTitleEl = document.getElementById("admin-team-detail-title");

  const taskViewButtons = {
    available: document.getElementById("admin-tasks-view-available"),
    completed: document.getElementById("admin-tasks-view-completed"),
  };
  const taskListEl = document.getElementById("admin-task-list");
  const taskEmptyEl = document.getElementById("admin-task-empty");

  let currentTeam = null;
  let allTasks = [];
  let taskView = "available";
  let tasksRequestId = 0;

  function formatLastActivity(iso) {
    if (!iso) {
      return "ещё нет активности";
    }
    const date = new Date(iso);
    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function showTeamsPanel() {
    currentTeam = null;
    panelDetail.hidden = true;
    panelTeams.hidden = false;
    loadTeams();
  }

  async function loadTeams() {
    try {
      const response = await fetch("/admin/teams");
      const data = await response.json();
      if (data.status !== "ok") {
        teamListEmptyEl.hidden = false;
        teamListEmptyEl.textContent = "Не удалось загрузить команды";
        return;
      }
      renderTeamList(data.teams);
    } catch (err) {
      teamListEmptyEl.hidden = false;
      teamListEmptyEl.textContent = "Не удалось загрузить команды";
    }
  }

  function renderTeamList(teams) {
    teamListEl.innerHTML = "";

    if (teams.length === 0) {
      teamListEmptyEl.hidden = false;
      teamListEmptyEl.textContent = "Команд пока нет";
      return;
    }
    teamListEmptyEl.hidden = true;

    for (const team of teams) {
      const item = document.createElement("div");
      item.className = "team-list-item";

      const top = document.createElement("div");
      top.className = "team-list-item__top";

      const name = document.createElement("span");
      name.className = "team-list-item__name";
      name.textContent = team.name;
      top.appendChild(name);

      const progress = document.createElement("span");
      progress.className = "team-list-item__progress";
      progress.textContent = `${team.progress_percent}%`;
      top.appendChild(progress);

      item.appendChild(top);

      const meta = document.createElement("div");
      meta.className = "team-list-item__meta";
      meta.textContent = `Последняя активность: ${formatLastActivity(team.last_task_completed_at)}`;
      item.appendChild(meta);

      item.addEventListener("click", () => openTeam(team));
      teamListEl.appendChild(item);
    }
  }

  function openTeam(team) {
    currentTeam = team;
    detailTitleEl.textContent = team.name;
    panelTeams.hidden = true;
    panelDetail.hidden = false;
    setTaskView("available");
  }

  function setTaskView(view) {
    taskView = view;
    taskViewButtons.available.setAttribute("aria-selected", String(view === "available"));
    taskViewButtons.completed.setAttribute("aria-selected", String(view === "completed"));
    loadTasks();
  }

  taskViewButtons.available.addEventListener("click", () => setTaskView("available"));
  taskViewButtons.completed.addEventListener("click", () => setTaskView("completed"));

  async function loadTasks() {
    if (!currentTeam) {
      return;
    }
    const teamId = currentTeam.team_id;
    const requestId = ++tasksRequestId;
    try {
      const response = await fetch(`/admin/teams/${teamId}/tasks`);
      const data = await response.json();
      if (requestId !== tasksRequestId) {
        return;
      }
      if (data.status !== "ok") {
        taskEmptyEl.hidden = false;
        taskEmptyEl.textContent = "Не удалось загрузить задачи";
        return;
      }
      allTasks = data.tasks;
      renderTasks();
    } catch (err) {
      if (requestId !== tasksRequestId) {
        return;
      }
      taskEmptyEl.hidden = false;
      taskEmptyEl.textContent = "Не удалось загрузить задачи";
    }
  }

  function renderTasks() {
    const items = allTasks.filter((task) => task.status === taskView);
    taskListEl.innerHTML = "";

    if (items.length === 0) {
      taskEmptyEl.hidden = false;
      taskEmptyEl.textContent =
        taskView === "available" ? "Пока нет доступных задач" : "Пока ничего не выполнено";
      return;
    }
    taskEmptyEl.hidden = true;

    for (const task of items) {
      const stage = task.stages || {};
      const card = document.createElement("div");
      card.className = "task-card";
      card.dataset.open = "false";

      const top = document.createElement("div");
      top.className = "task-card__top";

      const title = document.createElement("div");
      title.className = "task-card__title";
      title.textContent = stage.title || "Без названия";
      top.appendChild(title);

      const badge = document.createElement("span");
      badge.className = "task-card__badge" + (task.status === "completed" ? " task-card__badge--done" : "");
      badge.textContent =
        task.status === "completed" ? "выполнено" : COMPLETION_TYPE_LABELS[stage.completion_type] || "";
      top.appendChild(badge);

      card.appendChild(top);

      const description = document.createElement("div");
      description.className = "task-card__description";
      description.textContent = stage.description || "";
      card.appendChild(description);

      if (task.status === "available" && stage.completion_type === "actor") {
        description.appendChild(buildCompleteAction(task));
      }

      card.addEventListener("click", () => {
        card.dataset.open = card.dataset.open === "true" ? "false" : "true";
      });

      taskListEl.appendChild(card);
    }
  }

  function buildCompleteAction(task) {
    const wrap = document.createElement("div");
    wrap.className = "task-action";
    wrap.addEventListener("click", (event) => event.stopPropagation());

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-primary task-action__button";
    button.textContent = "Отметить выполненным";
    wrap.appendChild(button);

    const error = document.createElement("p");
    error.className = "form-error";
    wrap.appendChild(error);

    button.addEventListener("click", async () => {
      button.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(
          `/admin/teams/${currentTeam.team_id}/stages/${task.stage_id}/complete`,
          { method: "POST" }
        );
        const data = await response.json();
        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось отметить";
          button.disabled = false;
          return;
        }
        loadTasks();
      } catch (err) {
        error.textContent = "Не удалось связаться с сервером";
        button.disabled = false;
      }
    });

    return wrap;
  }

  backButton.addEventListener("click", showTeamsPanel);

  logoutButton.addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    window.location.reload();
  });

  window.AdminApp = {
    show(username, role) {
      headerNameEl.textContent = `${username} (${ROLE_LABELS[role] || role})`;
      appScreen.hidden = false;
      showTeamsPanel();
    },
  };
})();
