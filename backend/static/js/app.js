(() => {
  "use strict";

  const COMPLETION_TYPE_LABELS = {
    actor: "отмечает актёр",
    answer: "введите ответ",
    checkbox: "подтвердите",
    manual_review: "на проверку",
  };

  const appScreen = document.getElementById("app-screen");
  const teamNameEl = document.getElementById("app-team-name");
  const logoutButton = document.getElementById("logout-button");

  const navButtons = {
    tasks: document.getElementById("tab-tasks"),
    chat: document.getElementById("tab-chat"),
    calls: document.getElementById("tab-calls"),
  };
  const panels = {
    tasks: document.getElementById("panel-tasks"),
    chat: document.getElementById("panel-chat"),
    calls: document.getElementById("panel-calls"),
  };

  const taskViewButtons = {
    available: document.getElementById("tasks-view-available"),
    completed: document.getElementById("tasks-view-completed"),
  };
  const taskListEl = document.getElementById("task-list");
  const taskEmptyEl = document.getElementById("task-empty");

  let allTasks = [];
  let taskView = "available";

  function setTab(tab) {
    for (const key of Object.keys(panels)) {
      panels[key].hidden = key !== tab;
      navButtons[key].setAttribute("aria-selected", String(key === tab));
    }
  }

  for (const [tab, button] of Object.entries(navButtons)) {
    button.addEventListener("click", () => setTab(tab));
  }

  function setTaskView(view) {
    taskView = view;
    taskViewButtons.available.setAttribute("aria-selected", String(view === "available"));
    taskViewButtons.completed.setAttribute("aria-selected", String(view === "completed"));
    renderTasks();
  }

  taskViewButtons.available.addEventListener("click", () => setTaskView("available"));
  taskViewButtons.completed.addEventListener("click", () => setTaskView("completed"));

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

      card.addEventListener("click", () => {
        const isOpen = card.dataset.open === "true";
        card.dataset.open = isOpen ? "false" : "true";
      });

      taskListEl.appendChild(card);
    }
  }

  async function loadTasks() {
    try {
      const response = await fetch("/tasks");
      const data = await response.json();
      if (data.status === "ok") {
        allTasks = data.tasks;
        renderTasks();
      }
    } catch (err) {
      taskEmptyEl.hidden = false;
      taskEmptyEl.textContent = "Не удалось загрузить задачи";
    }
  }

  logoutButton.addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    window.location.reload();
  });

  window.QuestApp = {
    show(teamName) {
      teamNameEl.textContent = teamName || "";
      appScreen.hidden = false;
      setTab("tasks");
      setTaskView("available");
      loadTasks();
    },
  };
})();
