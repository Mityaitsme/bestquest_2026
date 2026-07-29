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

  const navButtons = {
    teams: document.getElementById("admin-tab-teams"),
    reviews: document.getElementById("admin-tab-reviews"),
    approvals: document.getElementById("admin-tab-approvals"),
  };
  const sections = {
    teams: document.getElementById("admin-panel-teams"),
    reviews: document.getElementById("admin-panel-reviews"),
    approvals: document.getElementById("admin-panel-approvals"),
  };

  function setSection(section) {
    for (const key of Object.keys(sections)) {
      sections[key].hidden = key !== section;
      navButtons[key].setAttribute("aria-selected", String(key === section));
    }
  }

  function formatDateTime(iso) {
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

  // ---- Teams: list + team detail (task list, actor mark-complete) ----

  const teamsListView = document.getElementById("admin-teams-list-view");
  const teamDetailView = document.getElementById("admin-team-detail-view");
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

  function showTeamsListView() {
    currentTeam = null;
    teamDetailView.hidden = true;
    teamsListView.hidden = false;
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
      meta.textContent = `Последняя активность: ${formatDateTime(team.last_task_completed_at)}`;
      item.appendChild(meta);

      item.addEventListener("click", () => openTeam(team));
      teamListEl.appendChild(item);
    }
  }

  function openTeam(team) {
    currentTeam = team;
    detailTitleEl.textContent = team.name;
    teamsListView.hidden = true;
    teamDetailView.hidden = false;
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

  backButton.addEventListener("click", showTeamsListView);

  // ---- Reviews: manual-review queue (operator only) ----

  const reviewListEl = document.getElementById("admin-review-list");
  const reviewListEmptyEl = document.getElementById("admin-review-list-empty");

  async function loadReviews() {
    try {
      const response = await fetch("/admin/reviews");
      const data = await response.json();
      if (data.status !== "ok") {
        reviewListEmptyEl.hidden = false;
        reviewListEmptyEl.textContent = "Не удалось загрузить заявки";
        return;
      }
      renderReviews(data.reviews);
    } catch (err) {
      reviewListEmptyEl.hidden = false;
      reviewListEmptyEl.textContent = "Не удалось загрузить заявки";
    }
  }

  function renderReviews(reviews) {
    reviewListEl.innerHTML = "";

    if (reviews.length === 0) {
      reviewListEmptyEl.hidden = false;
      reviewListEmptyEl.textContent = "Заявок на проверку нет";
      return;
    }
    reviewListEmptyEl.hidden = true;

    for (const review of reviews) {
      reviewListEl.appendChild(buildReviewCard(review));
    }
  }

  function buildReviewCard(review) {
    const card = document.createElement("div");
    card.className = "review-card";

    const team = document.createElement("div");
    team.className = "review-card__team";
    team.textContent = review.teams ? review.teams.name : "Команда";
    card.appendChild(team);

    const meta = document.createElement("div");
    meta.className = "review-card__meta";
    const stageTitle = review.stages ? review.stages.title : "";
    meta.textContent = `${stageTitle} · ${formatDateTime(review.created_at)}`;
    card.appendChild(meta);

    if (review.submitted_text) {
      const text = document.createElement("p");
      text.className = "review-card__text";
      text.textContent = review.submitted_text;
      card.appendChild(text);
    }

    if (review.photo_path) {
      card.appendChild(buildPhotoToggle(review));
    }

    const commentInput = document.createElement("textarea");
    commentInput.className = "task-review__textarea review-card__comment";
    commentInput.rows = 2;
    commentInput.placeholder = "Комментарий (необязательно)";
    card.appendChild(commentInput);

    const actions = document.createElement("div");
    actions.className = "review-card__actions";

    const acceptButton = document.createElement("button");
    acceptButton.type = "button";
    acceptButton.className = "btn-primary review-card__action";
    acceptButton.textContent = "Принять";
    actions.appendChild(acceptButton);

    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "btn-secondary review-card__action";
    rejectButton.textContent = "Отклонить";
    actions.appendChild(rejectButton);

    card.appendChild(actions);

    const error = document.createElement("p");
    error.className = "form-error";
    card.appendChild(error);

    async function decide(accept) {
      acceptButton.disabled = true;
      rejectButton.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(`/admin/reviews/${review.id}/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accept, comment: commentInput.value.trim() || null }),
        });
        const data = await response.json();
        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось сохранить решение";
          acceptButton.disabled = false;
          rejectButton.disabled = false;
          return;
        }
        loadReviews();
      } catch (err) {
        error.textContent = "Не удалось связаться с сервером";
        acceptButton.disabled = false;
        rejectButton.disabled = false;
      }
    }

    acceptButton.addEventListener("click", () => decide(true));
    rejectButton.addEventListener("click", () => decide(false));

    return card;
  }

  function buildPhotoToggle(review) {
    const wrap = document.createElement("div");
    wrap.className = "review-card__photo-wrap";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn-secondary review-card__photo-button";
    button.textContent = "Показать фото";
    wrap.appendChild(button);

    const img = document.createElement("img");
    img.className = "review-card__photo";
    img.hidden = true;
    img.alt = "Фото заявки";
    wrap.appendChild(img);

    button.addEventListener("click", async () => {
      if (!img.hidden) {
        img.hidden = true;
        button.textContent = "Показать фото";
        return;
      }

      button.disabled = true;
      try {
        const response = await fetch(`/admin/reviews/${review.id}/photo-url`);
        const data = await response.json();
        if (data.status === "ok") {
          img.src = data.url;
          img.hidden = false;
          button.textContent = "Скрыть фото";
        }
      } finally {
        button.disabled = false;
      }
    });

    return wrap;
  }

  // ---- Dialogue approvals: scripted-dialogue options awaiting sign-off (operator only) ----

  const approvalListEl = document.getElementById("admin-approval-list");
  const approvalListEmptyEl = document.getElementById("admin-approval-list-empty");

  async function loadApprovals() {
    try {
      const response = await fetch("/admin/dialogue/approvals");
      const data = await response.json();
      if (data.status !== "ok") {
        approvalListEmptyEl.hidden = false;
        approvalListEmptyEl.textContent = "Не удалось загрузить заявки";
        return;
      }
      renderApprovals(data.approvals);
    } catch (err) {
      approvalListEmptyEl.hidden = false;
      approvalListEmptyEl.textContent = "Не удалось загрузить заявки";
    }
  }

  function renderApprovals(approvals) {
    approvalListEl.innerHTML = "";

    if (approvals.length === 0) {
      approvalListEmptyEl.hidden = false;
      approvalListEmptyEl.textContent = "Заявок на одобрение нет";
      return;
    }
    approvalListEmptyEl.hidden = true;

    for (const approval of approvals) {
      approvalListEl.appendChild(buildApprovalCard(approval));
    }
  }

  function buildApprovalCard(approval) {
    const card = document.createElement("div");
    card.className = "approval-card";

    const team = document.createElement("div");
    team.className = "approval-card__team";
    team.textContent = approval.teams ? approval.teams.name : "Команда";
    card.appendChild(team);

    const meta = document.createElement("div");
    meta.className = "approval-card__meta";
    meta.textContent = formatDateTime(approval.created_at);
    card.appendChild(meta);

    const option = approval.dialogue_options || {};

    const chosen = document.createElement("p");
    chosen.className = "approval-card__text";
    chosen.textContent = `Команда выбрала: ${option.option_text || ""}`;
    card.appendChild(chosen);

    const reply = document.createElement("p");
    reply.className = "approval-card__text approval-card__text--muted";
    reply.textContent = `Ответ персонажа: ${option.reply_message || ""}`;
    card.appendChild(reply);

    const actions = document.createElement("div");
    actions.className = "approval-card__actions";

    const approveButton = document.createElement("button");
    approveButton.type = "button";
    approveButton.className = "btn-primary approval-card__action";
    approveButton.textContent = "Одобрить";
    actions.appendChild(approveButton);

    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "btn-secondary approval-card__action";
    rejectButton.textContent = "Отклонить";
    actions.appendChild(rejectButton);

    card.appendChild(actions);

    const error = document.createElement("p");
    error.className = "form-error";
    card.appendChild(error);

    async function decide(approve) {
      approveButton.disabled = true;
      rejectButton.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(`/admin/dialogue/approvals/${approval.id}/decision`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve }),
        });
        const data = await response.json();
        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось сохранить решение";
          approveButton.disabled = false;
          rejectButton.disabled = false;
          return;
        }
        loadApprovals();
      } catch (err) {
        error.textContent = "Не удалось связаться с сервером";
        approveButton.disabled = false;
        rejectButton.disabled = false;
      }
    }

    approveButton.addEventListener("click", () => decide(true));
    rejectButton.addEventListener("click", () => decide(false));

    return card;
  }

  navButtons.teams.addEventListener("click", () => {
    setSection("teams");
    showTeamsListView();
  });

  navButtons.reviews.addEventListener("click", () => {
    setSection("reviews");
    loadReviews();
  });

  navButtons.approvals.addEventListener("click", () => {
    setSection("approvals");
    loadApprovals();
  });

  logoutButton.addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    window.location.reload();
  });

  window.AdminApp = {
    show(username, role) {
      headerNameEl.textContent = `${username} (${ROLE_LABELS[role] || role})`;
      appScreen.hidden = false;
      navButtons.reviews.hidden = role !== "operator";
      navButtons.approvals.hidden = role !== "operator";
      setSection("teams");
      showTeamsListView();
    },
  };
})();
