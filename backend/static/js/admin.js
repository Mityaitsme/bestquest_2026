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

  const CHAT_MODE_LABELS = {
    scripted: "Сценарий",
    operator: "Оператор",
    gpt: "GPT",
    muted: "Тихо",
  };

  const FETCH_RETRY_ATTEMPTS = 3;
  const FETCH_RETRY_DELAY_MS = 400;

  // См. аналогичный помощник в app.js: GET-запросы на чтение при временном
  // сбое (сеть, недоступный на секунду Supabase) тихо повторяются ещё
  // пару раз, прежде чем показать "не удалось загрузить". Только для
  // чтения — мутации (POST) так не оборачиваем.
  async function fetchJsonWithRetry(url, attempts = FETCH_RETRY_ATTEMPTS) {
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt++) {
      try {
        const response = await fetch(url);
        if (response.status === 401) {
          handleSessionExpired();
          throw new Error("session-expired");
        }
        return await response.json();
      } catch (err) {
        lastError = err;
        if (err.message === "session-expired") {
          throw err; // сессии больше нет — повторять запрос бессмысленно
        }
        if (attempt < attempts - 1) {
          await new Promise((resolve) => setTimeout(resolve, FETCH_RETRY_DELAY_MS * (attempt + 1)));
        }
      }
    }
    throw lastError;
  }

  // Cookie сессии одна на весь браузер: вход в другую роль (актёр/оператор/
  // команда) в другой вкладке того же браузера тихо разлогинивает эту —
  // запросы начинают падать с 401 без единой видимой ошибки. Вместо этого
  // показываем явное сообщение и перезагружаем страницу, чтобы попасть на
  // актуальный для этого браузера экран входа.
  let sessionExpiredHandled = false;
  function handleSessionExpired() {
    if (sessionExpiredHandled) {
      return;
    }
    sessionExpiredHandled = true;
    stopPendingItemsPolling();
    const banner = document.createElement("div");
    banner.className = "admin-banner";
    banner.textContent = "Сессия сброшена — похоже, в этом браузере вошли под другим аккаунтом. Перезагружаем…";
    bannerContainerEl.appendChild(banner);
    setTimeout(() => banner.classList.add("admin-banner--visible"), 20);
    setTimeout(() => window.location.reload(), 1800);
  }

  let currentRole = null;

  const appScreen = document.getElementById("admin-app-screen");
  const headerNameEl = document.getElementById("admin-header-name");
  const logoutButton = document.getElementById("admin-logout-button");

  const navButtons = {
    teams: document.getElementById("admin-tab-teams"),
    support: document.getElementById("admin-tab-support"),
    dialogues: document.getElementById("admin-tab-dialogues"),
    reviews: document.getElementById("admin-tab-reviews"),
    approvals: document.getElementById("admin-tab-approvals"),
  };
  const sections = {
    teams: document.getElementById("admin-panel-teams"),
    support: document.getElementById("admin-panel-support"),
    dialogues: document.getElementById("admin-panel-dialogues"),
    reviews: document.getElementById("admin-panel-reviews"),
    approvals: document.getElementById("admin-panel-approvals"),
  };

  // Красный кружок на вкладке "где-то есть неотвеченный запрос команды" —
  // Техподдержка (последнее сообщение чата — от команды), Проверка и
  // Блок-посты (есть хоть одна нерешённая заявка). Отражает текущее
  // состояние всегда, а не только "новое с момента входа" (в отличие от
  // баннеров ниже) — так что считается и обновляется отдельно от них.
  const navDots = {
    support: document.getElementById("admin-tab-support-dot"),
    dialogues: document.getElementById("admin-tab-dialogues-dot"),
    reviews: document.getElementById("admin-tab-reviews-dot"),
    approvals: document.getElementById("admin-tab-approvals-dot"),
  };

  // Техподдержка/Диалоги: точка и баннер должны гаснуть, когда оператор
  // ПРОЧИТАЛ сообщение (открыл чат), а не только когда на него ОТВЕТИЛ —
  // needs_reply с сервера отражает только "последнее сообщение от команды",
  // само по себе не знает, смотрел ли его кто-то. chat.id -> last_message_at,
  // каким он был в момент открытия чата; если к следующему опросу
  // last_message_at чата новее сохранённого - там реально новое сообщение,
  // не то же самое, что уже видели. Заявки на проверку и блок-посты этой
  // логике намеренно не подчиняются - они гаснут только решением, как и раньше.
  const readChatLastSeenAt = new Map();

  function isChatUnreadByOperator(chat) {
    if (!chat.needs_reply) {
      return false;
    }
    const lastSeenAt = readChatLastSeenAt.get(chat.id);
    return !lastSeenAt || lastSeenAt < chat.last_message_at;
  }

  function setDot(key, hasUnanswered) {
    if (navDots[key]) {
      navDots[key].hidden = !hasUnanswered;
    }
  }

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

  // ---- Teams: list + team detail (task list, actor mark-complete, graph) ----

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
      const data = await fetchJsonWithRetry("/admin/teams");
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
    showTeamTasksListView();
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
      const data = await fetchJsonWithRetry(`/admin/teams/${teamId}/tasks`);
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

    const askButton = document.createElement("button");
    askButton.type = "button";
    askButton.className = "btn-primary task-action__button";
    askButton.textContent = "Отметить выполненным";
    wrap.appendChild(askButton);

    const confirmRow = document.createElement("div");
    confirmRow.className = "task-action__confirm-row";
    confirmRow.hidden = true;

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "btn-primary task-action__button task-action__confirm-button";
    confirmButton.textContent = "Да, точно";
    confirmRow.appendChild(confirmButton);

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "btn-secondary task-action__button task-action__confirm-button";
    cancelButton.textContent = "Отмена";
    confirmRow.appendChild(cancelButton);

    wrap.appendChild(confirmRow);

    const error = document.createElement("p");
    error.className = "form-error";
    wrap.appendChild(error);

    function showAsk() {
      askButton.hidden = false;
      confirmRow.hidden = true;
      error.textContent = "";
    }

    askButton.addEventListener("click", () => {
      askButton.hidden = true;
      confirmRow.hidden = false;
    });

    cancelButton.addEventListener("click", showAsk);

    confirmButton.addEventListener("click", async () => {
      confirmButton.disabled = true;
      cancelButton.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(
          `/admin/teams/${currentTeam.team_id}/stages/${task.stage_id}/complete`,
          { method: "POST" }
        );
        const data = await response.json();
        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось отметить";
          confirmButton.disabled = false;
          cancelButton.disabled = false;
          // Не выходим сразу: сервер мог успеть закоммитить сам статус
          // раньше, чем упал на одном из следующих шагов (разблокировка,
          // автотриггер сценария) - loadTasks() покажет как оно на самом
          // деле, а не то, что этап якобы остался прежним.
          loadTasks();
          return;
        }
        loadTasks();
      } catch (err) {
        error.textContent = "Не удалось связаться с сервером";
        confirmButton.disabled = false;
        cancelButton.disabled = false;
        loadTasks();
      }
    });

    return wrap;
  }

  backButton.addEventListener("click", showTeamsListView);

  // ---- Team graph: secondary, desktop-oriented view of the full stage graph ----
  // (requirements.md calls this optional — "второй, не основной экран")

  const STATUS_LABELS = { locked: "заблокировано", available: "доступно", completed: "выполнено" };
  const GRAPH_NODE_WIDTH = 170;
  const GRAPH_NODE_HEIGHT = 56;
  const GRAPH_COL_GAP = 24;
  const GRAPH_ROW_GAP = 56;
  const GRAPH_PADDING = 20;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const teamTasksListView = document.getElementById("admin-team-tasks-list-view");
  const teamGraphView = document.getElementById("admin-team-graph-view");
  const graphOpenButton = document.getElementById("admin-graph-open-button");
  const graphBackButton = document.getElementById("admin-graph-back-button");
  const graphEmptyEl = document.getElementById("admin-team-graph-empty");
  const graphSvgEl = document.getElementById("admin-team-graph");

  function showTeamTasksListView() {
    teamGraphView.hidden = true;
    teamTasksListView.hidden = false;
  }

  function showTeamGraphView() {
    teamTasksListView.hidden = true;
    teamGraphView.hidden = false;
    loadTeamGraph();
  }

  graphOpenButton.addEventListener("click", showTeamGraphView);
  graphBackButton.addEventListener("click", showTeamTasksListView);

  async function loadTeamGraph() {
    if (!currentTeam) {
      return;
    }
    graphEmptyEl.hidden = true;
    graphSvgEl.innerHTML = "";
    try {
      const data = await fetchJsonWithRetry(`/admin/teams/${currentTeam.team_id}/graph`);
      if (data.status !== "ok") {
        graphEmptyEl.hidden = false;
        graphEmptyEl.textContent = "Не удалось загрузить граф";
        return;
      }
      renderTeamGraph(data.stages, data.edges);
    } catch (err) {
      graphEmptyEl.hidden = false;
      graphEmptyEl.textContent = "Не удалось загрузить граф";
    }
  }

  function renderTeamGraph(stages, edges) {
    if (stages.length === 0) {
      graphEmptyEl.hidden = false;
      graphEmptyEl.textContent = "У команды пока нет ни одного этапа";
      return;
    }

    const incoming = new Map(stages.map((s) => [s.stage_id, []]));
    for (const edge of edges) {
      if (incoming.has(edge.to_stage_id) && incoming.has(edge.from_stage_id)) {
        incoming.get(edge.to_stage_id).push(edge.from_stage_id);
      }
    }

    const levels = new Map();
    function levelOf(stageId, seen) {
      if (levels.has(stageId)) {
        return levels.get(stageId);
      }
      if (seen.has(stageId)) {
        return 0; // защита от цикла в данных — на такое граф не рассчитан
      }
      seen.add(stageId);
      const prereqs = incoming.get(stageId) || [];
      const level = prereqs.length === 0 ? 0 : 1 + Math.max(...prereqs.map((p) => levelOf(p, seen)));
      levels.set(stageId, level);
      return level;
    }
    for (const stage of stages) {
      levelOf(stage.stage_id, new Set());
    }

    const rows = [];
    for (const stage of stages) {
      const level = levels.get(stage.stage_id);
      rows[level] = rows[level] || [];
      rows[level].push(stage);
    }

    const rowWidths = rows.map((row) => row.length * (GRAPH_NODE_WIDTH + GRAPH_COL_GAP) - GRAPH_COL_GAP);
    const canvasWidth = Math.max(...rowWidths) + GRAPH_PADDING * 2;
    const canvasHeight =
      rows.length * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP) - GRAPH_ROW_GAP + GRAPH_PADDING * 2;

    const positions = new Map();
    rows.forEach((row, level) => {
      const rowWidth = rowWidths[level];
      const xOffset = GRAPH_PADDING + (canvasWidth - GRAPH_PADDING * 2 - rowWidth) / 2;
      const y = GRAPH_PADDING + level * (GRAPH_NODE_HEIGHT + GRAPH_ROW_GAP);
      row.forEach((stage, index) => {
        const x = xOffset + index * (GRAPH_NODE_WIDTH + GRAPH_COL_GAP);
        positions.set(stage.stage_id, { x, y });
      });
    });

    graphSvgEl.setAttribute("viewBox", `0 0 ${canvasWidth} ${canvasHeight}`);
    graphSvgEl.setAttribute("width", canvasWidth);
    graphSvgEl.setAttribute("height", canvasHeight);

    for (const edge of edges) {
      const from = positions.get(edge.from_stage_id);
      const to = positions.get(edge.to_stage_id);
      if (!from || !to) {
        continue;
      }
      const line = document.createElementNS(SVG_NS, "line");
      line.setAttribute("class", "admin-graph__edge");
      line.setAttribute("x1", from.x + GRAPH_NODE_WIDTH / 2);
      line.setAttribute("y1", from.y + GRAPH_NODE_HEIGHT);
      line.setAttribute("x2", to.x + GRAPH_NODE_WIDTH / 2);
      line.setAttribute("y2", to.y);
      graphSvgEl.appendChild(line);
    }

    for (const stage of stages) {
      const pos = positions.get(stage.stage_id);
      const group = document.createElementNS(SVG_NS, "g");
      group.setAttribute("class", `admin-graph__node admin-graph__node--${stage.status}`);

      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("x", pos.x);
      rect.setAttribute("y", pos.y);
      rect.setAttribute("width", GRAPH_NODE_WIDTH);
      rect.setAttribute("height", GRAPH_NODE_HEIGHT);
      rect.setAttribute("rx", 10);
      group.appendChild(rect);

      const title = document.createElementNS(SVG_NS, "title");
      title.textContent = `${stage.title} — ${STATUS_LABELS[stage.status] || stage.status}`;
      group.appendChild(title);

      const text = document.createElementNS(SVG_NS, "text");
      text.setAttribute("x", pos.x + GRAPH_NODE_WIDTH / 2);
      text.setAttribute("y", pos.y + GRAPH_NODE_HEIGHT / 2);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("dominant-baseline", "middle");
      const label = stage.title.length > 20 ? `${stage.title.slice(0, 19)}…` : stage.title;
      text.textContent = label;
      group.appendChild(text);

      graphSvgEl.appendChild(group);
    }
  }

  // ---- Shared chat-browser: list of chats (across all teams) -> thread + mode select ----
  // Used both by "Техподдержка" (one chat per team, all same persona) and
  // "Диалоги" (one chat per team, for whichever character is picked) — the
  // two tabs never show at the same time, but each gets its own instance
  // (own DOM subtree) since duplicating a few small elements is simpler and
  // safer here than reparenting one shared subtree between two panels.
  function createChatBrowser(refs) {
    let currentChat = null;

    function showList() {
      currentChat = null;
      refs.detailView.hidden = true;
      refs.listView.hidden = false;
    }

    function renderList(chats, emptyText) {
      refs.listEl.innerHTML = "";

      if (chats.length === 0) {
        refs.listEmptyEl.hidden = false;
        refs.listEmptyEl.textContent = emptyText;
        return;
      }
      refs.listEmptyEl.hidden = true;

      for (const chat of chats) {
        const item = document.createElement("div");
        item.className = "chat-list-item";

        const avatar = document.createElement("div");
        avatar.className = "chat-list-item__avatar";
        avatar.textContent = chat.team_name.charAt(0).toUpperCase();
        item.appendChild(avatar);

        const info = document.createElement("div");
        info.className = "chat-list-item__info";

        const nameEl = document.createElement("div");
        nameEl.className = "chat-list-item__name";
        nameEl.textContent = chat.team_name;
        info.appendChild(nameEl);

        const modeEl = document.createElement("div");
        modeEl.className = "chat-list-item__mode";
        modeEl.textContent = CHAT_MODE_LABELS[chat.mode] || chat.mode;
        info.appendChild(modeEl);

        item.appendChild(info);
        item.addEventListener("click", () => openChat(chat));
        refs.listEl.appendChild(item);
      }
    }

    function openChat(chat) {
      currentChat = chat;
      readChatLastSeenAt.set(chat.id, chat.last_message_at);
      refs.titleEl.textContent = chat.team_name;
      refs.modeErrorEl.textContent = "";
      refs.modeSelect.value = chat.mode;
      refs.inputRowEl.hidden = chat.mode !== "operator";
      refs.listView.hidden = true;
      refs.detailView.hidden = false;
      loadMessages();
    }

    async function loadMessages() {
      if (!currentChat) {
        return;
      }
      const chatId = currentChat.id;
      refs.messagesEl.textContent = "Загрузка…";
      try {
        const data = await fetchJsonWithRetry(`/admin/chats/${chatId}/messages`);
        if (!currentChat || currentChat.id !== chatId) {
          return;
        }
        if (data.status !== "ok") {
          refs.messagesEl.textContent = "Не удалось загрузить сообщения";
          return;
        }
        renderMessages(data.messages);
      } catch (err) {
        if (!currentChat || currentChat.id !== chatId) {
          return;
        }
        refs.messagesEl.textContent = "Не удалось загрузить сообщения";
      }
    }

    function renderMessages(messages) {
      refs.messagesEl.innerHTML = "";
      for (const message of messages) {
        const bubble = document.createElement("div");
        const isOwn =
          message.sender_type === "character" ||
          message.sender_type === "admin" ||
          message.sender_type === "system";
        bubble.className = "chat-bubble " + (isOwn ? "chat-bubble--team" : "chat-bubble--other");
        if (message.message_kind === "support_comment") {
          bubble.classList.add("chat-bubble--support");
        }
        bubble.textContent = message.content;
        refs.messagesEl.appendChild(bubble);
      }
      refs.messagesEl.scrollTop = refs.messagesEl.scrollHeight;
    }

    refs.modeSelect.addEventListener("change", async () => {
      if (!currentChat) {
        return;
      }
      const chatId = currentChat.id;
      const newMode = refs.modeSelect.value;
      refs.modeErrorEl.textContent = "";
      refs.modeSelect.disabled = true;
      try {
        const response = await fetch(`/admin/chats/${chatId}/mode`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: newMode }),
        });
        const data = await response.json();
        if (data.status !== "ok") {
          refs.modeErrorEl.textContent = data.detail || "Не получилось сменить режим";
          refs.modeSelect.value = currentChat.mode;
          return;
        }
        currentChat.mode = newMode;
        refs.inputRowEl.hidden = newMode !== "operator";
      } catch (err) {
        refs.modeErrorEl.textContent = "Не удалось связаться с сервером";
        refs.modeSelect.value = currentChat.mode;
      } finally {
        refs.modeSelect.disabled = false;
      }
    });

    async function sendMessage() {
      const content = refs.inputEl.value.trim();
      if (!content || !currentChat) {
        return;
      }
      const chatId = currentChat.id;
      refs.sendButton.disabled = true;
      refs.inputEl.disabled = true;
      try {
        const response = await fetch(`/admin/chats/${chatId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        });
        const data = await response.json();
        if (data.status === "ok") {
          refs.inputEl.value = "";
          await loadMessages();
        }
      } catch (err) {
        // сообщение просто не появится - можно попробовать отправить ещё раз
      } finally {
        refs.sendButton.disabled = false;
        refs.inputEl.disabled = false;
        refs.inputEl.focus();
      }
    }

    refs.sendButton.addEventListener("click", sendMessage);
    refs.inputEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendMessage();
      }
    });
    refs.backButton.addEventListener("click", showList);

    return { renderList, showList };
  }

  // ---- Техподдержка: support chats across all teams (operator only) ----

  const supportBrowser = createChatBrowser({
    listView: document.getElementById("admin-support-list-view"),
    listEl: document.getElementById("admin-support-chat-list"),
    listEmptyEl: document.getElementById("admin-support-list-empty"),
    detailView: document.getElementById("admin-support-chat-detail-view"),
    backButton: document.getElementById("admin-support-chat-back-button"),
    titleEl: document.getElementById("admin-support-chat-detail-title"),
    modeSelect: document.getElementById("admin-support-chat-mode-select"),
    modeErrorEl: document.getElementById("admin-support-chat-mode-error"),
    messagesEl: document.getElementById("admin-support-chat-messages"),
    inputRowEl: document.getElementById("admin-support-chat-input-row"),
    inputEl: document.getElementById("admin-support-chat-input"),
    sendButton: document.getElementById("admin-support-chat-send-button"),
  });

  async function loadSupportChats() {
    supportBrowser.showList();
    try {
      const data = await fetchJsonWithRetry("/admin/support-chats");
      if (data.status !== "ok") {
        supportBrowser.renderList([], "Не удалось загрузить чаты");
        return;
      }
      supportBrowser.renderList(data.chats, "Чатов техподдержки пока нет");
      setDot("support", data.chats.some(isChatUnreadByOperator));
    } catch (err) {
      supportBrowser.renderList([], "Не удалось загрузить чаты");
    }
  }

  // ---- Диалоги: chats with a chosen game-bot character, across all teams (operator only) ----

  const dialoguesBrowser = createChatBrowser({
    listView: document.getElementById("admin-dialogues-list-view"),
    listEl: document.getElementById("admin-persona-chat-list"),
    listEmptyEl: document.getElementById("admin-persona-list-empty"),
    detailView: document.getElementById("admin-dialogues-chat-detail-view"),
    backButton: document.getElementById("admin-dialogues-chat-back-button"),
    titleEl: document.getElementById("admin-dialogues-chat-detail-title"),
    modeSelect: document.getElementById("admin-dialogues-chat-mode-select"),
    modeErrorEl: document.getElementById("admin-dialogues-chat-mode-error"),
    messagesEl: document.getElementById("admin-dialogues-chat-messages"),
    inputRowEl: document.getElementById("admin-dialogues-chat-input-row"),
    inputEl: document.getElementById("admin-dialogues-chat-input"),
    sendButton: document.getElementById("admin-dialogues-chat-send-button"),
  });

  const personaSelect = document.getElementById("admin-persona-select");

  async function loadCharactersAndChats() {
    dialoguesBrowser.showList();
    try {
      const data = await fetchJsonWithRetry("/admin/characters");
      if (data.status !== "ok" || data.characters.length === 0) {
        personaSelect.innerHTML = "";
        dialoguesBrowser.renderList([], "Персонажей пока нет");
        return;
      }
      personaSelect.innerHTML = "";
      for (const character of data.characters) {
        const option = document.createElement("option");
        option.value = character.id;
        option.textContent = character.name;
        personaSelect.appendChild(option);
      }
      await loadChatsForSelectedPersona();
    } catch (err) {
      dialoguesBrowser.renderList([], "Не удалось загрузить персонажей");
    }
  }

  async function loadChatsForSelectedPersona() {
    dialoguesBrowser.showList();
    const characterId = personaSelect.value;
    if (!characterId) {
      return;
    }
    try {
      const data = await fetchJsonWithRetry(`/admin/characters/${characterId}/chats`);
      if (data.status !== "ok") {
        dialoguesBrowser.renderList([], "Не удалось загрузить чаты");
        return;
      }
      dialoguesBrowser.renderList(data.chats, "У этого персонажа пока нет чатов");
    } catch (err) {
      dialoguesBrowser.renderList([], "Не удалось загрузить чаты");
    }
  }

  personaSelect.addEventListener("change", loadChatsForSelectedPersona);

  // ---- Reviews: manual-review queue (actor + operator) ----

  const reviewListEl = document.getElementById("admin-review-list");
  const reviewListEmptyEl = document.getElementById("admin-review-list-empty");

  async function loadReviews() {
    try {
      const data = await fetchJsonWithRetry("/admin/reviews");
      if (data.status !== "ok") {
        reviewListEmptyEl.hidden = false;
        reviewListEmptyEl.textContent = "Не удалось загрузить заявки";
        return;
      }
      renderReviews(data.reviews);
      setDot("reviews", data.reviews.length > 0);
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
        removePendingBanner(`review:${review.id}`);
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

  // ---- Блок-посты: команда ждёт, оператор выбирает или пишет реплику ----

  const approvalListEl = document.getElementById("admin-approval-list");
  const approvalListEmptyEl = document.getElementById("admin-approval-list-empty");

  async function loadBlockPosts() {
    try {
      const data = await fetchJsonWithRetry("/admin/dialogue/block-posts");
      if (data.status !== "ok") {
        approvalListEmptyEl.hidden = false;
        approvalListEmptyEl.textContent = "Не удалось загрузить блок-посты";
        return;
      }
      renderBlockPosts(data.block_posts);
      setDot("approvals", data.block_posts.length > 0);
    } catch (err) {
      approvalListEmptyEl.hidden = false;
      approvalListEmptyEl.textContent = "Не удалось загрузить блок-посты";
    }
  }

  function renderBlockPosts(blockPosts) {
    approvalListEl.innerHTML = "";

    if (blockPosts.length === 0) {
      approvalListEmptyEl.hidden = false;
      approvalListEmptyEl.textContent = "Блок-постов нет";
      return;
    }
    approvalListEmptyEl.hidden = true;

    for (const blockPost of blockPosts) {
      approvalListEl.appendChild(buildBlockPostCard(blockPost));
    }
  }

  function buildBlockPostCard(blockPost) {
    const card = document.createElement("div");
    card.className = "approval-card";

    const team = document.createElement("div");
    team.className = "approval-card__team";
    team.textContent = `${blockPost.team_name} — ${blockPost.character_name}`;
    card.appendChild(team);

    if (blockPost.intro_message) {
      const intro = document.createElement("p");
      intro.className = "approval-card__text approval-card__text--muted";
      intro.textContent = blockPost.intro_message;
      card.appendChild(intro);
    }

    const groupName = `block-post-${blockPost.team_id}-${blockPost.character_id}`;
    const optionInputs = [];

    for (const option of blockPost.options) {
      const label = document.createElement("label");
      label.className = "block-post-option";

      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = groupName;
      radio.value = option.id;
      optionInputs.push(radio);
      label.appendChild(radio);

      const text = document.createElement("span");
      text.className = "block-post-option__text";

      const smallLabel = document.createElement("span");
      smallLabel.className = "block-post-option__label";
      smallLabel.textContent = option.text;
      text.appendChild(smallLabel);

      const replyText = document.createElement("span");
      replyText.className = "block-post-option__reply";
      replyText.textContent = option.reply;
      text.appendChild(replyText);

      label.appendChild(text);
      card.appendChild(label);
    }

    const customInput = document.createElement("textarea");
    customInput.className = "task-review__textarea block-post-custom";
    customInput.rows = 2;
    customInput.placeholder = "Свой вариант реплики";
    card.appendChild(customInput);

    // Выбор готового варианта и свой текст - взаимоисключающие: набор текста
    // сбрасывает выбранный радио-вариант и наоборот, чтобы не было неясности,
    // что именно уйдёт команде при отправке.
    customInput.addEventListener("input", () => {
      if (customInput.value.trim()) {
        for (const radio of optionInputs) {
          radio.checked = false;
        }
      }
    });
    for (const radio of optionInputs) {
      radio.addEventListener("change", () => {
        customInput.value = "";
      });
    }

    const sendButton = document.createElement("button");
    sendButton.type = "button";
    sendButton.className = "btn-primary approval-card__action";
    sendButton.textContent = "Отправить как есть";
    card.appendChild(sendButton);

    const error = document.createElement("p");
    error.className = "form-error";
    card.appendChild(error);

    sendButton.addEventListener("click", async () => {
      const selected = optionInputs.find((radio) => radio.checked);
      const customText = customInput.value.trim();
      if (!selected && !customText) {
        error.textContent = "Выберите готовый вариант или напишите свой текст";
        return;
      }
      sendButton.disabled = true;
      error.textContent = "";
      try {
        const response = await fetch(
          `/admin/dialogue/block-posts/${blockPost.team_id}/${blockPost.character_id}/resolve`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(
              selected ? { option_id: selected.value } : { custom_text: customText }
            ),
          }
        );
        const data = await response.json();
        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось отправить";
          sendButton.disabled = false;
          return;
        }
        removePendingBanner(`approval:${blockPost.team_id}:${blockPost.character_id}`);
        loadBlockPosts();
      } catch (err) {
        error.textContent = "Не удалось связаться с сервером";
        sendButton.disabled = false;
      }
    });

    return card;
  }

  // ---- Persistent notification banners for new reviews/approvals (operator only) ----
  // Отличие от команды: тост команды сам гаснет через несколько секунд, а
  // здесь баннер обязан "висеть", пока оператор реально не примет решение —
  // поэтому снимаем его только когда элемент пропал из списка ожидающих
  // (решён этим или другим оператором) или сразу после успешного decide().
  //
  // Баннер показывается для ЛЮБОЙ заявки, которая сейчас в очереди, включая
  // самый первый опрос сразу после входа — то есть и в ситуации "заявка
  // появилась, пока оператор ещё не был залогинен, и он входит уже после
  // этого" (стандартный сценарий при тестировании с одного устройства
  // поочерёдным входом то командой, то админом). Раньше первый опрос после
  // входа был специально исключён (чтобы не "заваливать" оператора баннерами
  // про давно висящую очередь) — но это на практике означало, что баннер
  // почти никогда не появлялся при таком сценарии тестирования, что
  // противоречило самой идее "висит, пока не ответят". showPendingBanner
  // сам не создаёт дубликат для уже показанного баннера, так что повторные
  // опросы не заваливают экран.

  const bannerContainerEl = document.getElementById("admin-banner-container");
  const PENDING_POLL_INTERVAL_MS = 10000;

  let pendingPollTimer = null;
  const knownPendingReviewIds = new Set();
  const knownPendingApprovalIds = new Set();
  const knownNeedsReplySupportChatIds = new Set();
  const knownNeedsReplyDialogueChatIds = new Set();
  const bannerElByKey = new Map();

  function startPendingItemsPolling() {
    stopPendingItemsPolling();
    knownPendingReviewIds.clear();
    knownPendingApprovalIds.clear();
    knownNeedsReplySupportChatIds.clear();
    knownNeedsReplyDialogueChatIds.clear();
    pollPendingItems();
    pendingPollTimer = setInterval(pollPendingItems, PENDING_POLL_INTERVAL_MS);
  }

  function stopPendingItemsPolling() {
    if (pendingPollTimer) {
      clearInterval(pendingPollTimer);
      pendingPollTimer = null;
    }
  }

  async function pollPendingItems() {
    // Актёру доступна только "Проверка" — опрашиваем только её. Оператору
    // ещё "Блок-посты", "Техподдержка" и "Диалоги" (у всех троих теперь и
    // точка, и баннер на новое непрочитанное — раньше баннер был только у
    // заявок/блок-постов, а у чатов только точка, безо всякого уведомления
    // о том, что именно появилось новое сообщение).
    const isOperator = currentRole === "operator";
    try {
      const requests = [fetch("/admin/reviews")];
      if (isOperator) {
        requests.push(
          fetch("/admin/dialogue/block-posts"),
          fetch("/admin/support-chats"),
          fetch("/admin/dialogue-chats")
        );
      }
      const responses = await Promise.all(requests);
      if (responses.some((response) => response.status === 401)) {
        handleSessionExpired();
        return;
      }
      const reviewsData = await responses[0].json();

      if (reviewsData.status === "ok") {
        syncPendingBanners("review", reviewsData.reviews, knownPendingReviewIds, (review) => ({
          text: `Новая заявка на проверку: ${review.teams ? review.teams.name : "команда"}`,
          onClick: () => {
            setSection("reviews");
            loadReviews();
          },
        }));
        setDot("reviews", reviewsData.reviews.length > 0);
      }

      if (isOperator) {
        const blockPostsData = await responses[1].json();
        if (blockPostsData.status === "ok") {
          // У блок-поста нет собственного стабильного id (это не отдельная
          // строка в таблице, а производное от team_dialogue_state) -
          // используем team_id+character_id как синтетический ключ.
          const blockPostsWithId = blockPostsData.block_posts.map((bp) => ({
            ...bp,
            id: `${bp.team_id}:${bp.character_id}`,
          }));
          syncPendingBanners("approval", blockPostsWithId, knownPendingApprovalIds, (bp) => ({
            text: `Новый блок-пост: ${bp.team_name} — ${bp.character_name}`,
            onClick: () => {
              setSection("approvals");
              loadBlockPosts();
            },
          }));
          setDot("approvals", blockPostsWithId.length > 0);
        }

        const supportData = await responses[2].json();
        if (supportData.status === "ok") {
          const needsReplyChats = supportData.chats.filter(isChatUnreadByOperator);
          setDot("support", needsReplyChats.length > 0);
          syncPendingBanners("support-chat", needsReplyChats, knownNeedsReplySupportChatIds, (chat) => ({
            text: `Новое сообщение в техподдержку: ${chat.team_name}`,
            onClick: () => {
              setSection("support");
              loadSupportChats();
            },
          }));
        }

        const dialogueChatsData = await responses[3].json();
        if (dialogueChatsData.status === "ok") {
          const needsReplyChats = dialogueChatsData.chats.filter(isChatUnreadByOperator);
          setDot("dialogues", needsReplyChats.length > 0);
          syncPendingBanners("dialogue-chat", needsReplyChats, knownNeedsReplyDialogueChatIds, (chat) => ({
            text: `Новое сообщение в диалоге: ${chat.team_name}`,
            onClick: () => {
              setSection("dialogues");
              loadCharactersAndChats();
            },
          }));
        }
      }
    } catch (err) {
      // пропускаем цикл опроса - следующий тик попробует снова
    }
  }

  function syncPendingBanners(kind, items, knownIds, describe) {
    const currentIds = new Set(items.map((item) => item.id));

    // Баннер для каждой заявки, которая сейчас в очереди — включая самый
    // первый опрос после входа (см. комментарий выше). showPendingBanner не
    // создаёт дубликат, если баннер для этого ключа уже показан.
    for (const item of items) {
      if (!knownIds.has(item.id)) {
        const { text, onClick } = describe(item);
        showPendingBanner(`${kind}:${item.id}`, text, onClick);
      }
    }

    for (const id of knownIds) {
      if (!currentIds.has(id)) {
        removePendingBanner(`${kind}:${id}`);
      }
    }

    knownIds.clear();
    for (const id of currentIds) {
      knownIds.add(id);
    }
  }

  function showPendingBanner(key, text, onClick) {
    if (bannerElByKey.has(key)) {
      return;
    }
    const banner = document.createElement("div");
    banner.className = "admin-banner";
    banner.textContent = text;
    banner.addEventListener("click", onClick);
    bannerContainerEl.appendChild(banner);
    setTimeout(() => banner.classList.add("admin-banner--visible"), 20);
    bannerElByKey.set(key, banner);
  }

  function removePendingBanner(key) {
    const banner = bannerElByKey.get(key);
    if (!banner) {
      return;
    }
    bannerElByKey.delete(key);
    banner.classList.remove("admin-banner--visible");
    setTimeout(() => banner.remove(), 300);
  }

  // ---- Nav wiring ----

  navButtons.teams.addEventListener("click", () => {
    setSection("teams");
    showTeamsListView();
  });

  navButtons.support.addEventListener("click", () => {
    setSection("support");
    loadSupportChats();
  });

  navButtons.dialogues.addEventListener("click", () => {
    setSection("dialogues");
    loadCharactersAndChats();
  });

  navButtons.reviews.addEventListener("click", () => {
    setSection("reviews");
    loadReviews();
  });

  navButtons.approvals.addEventListener("click", () => {
    setSection("approvals");
    loadBlockPosts();
  });

  logoutButton.addEventListener("click", async () => {
    await fetch("/auth/logout", { method: "POST" });
    window.location.reload();
  });

  window.AdminApp = {
    show(username, role) {
      currentRole = role;
      headerNameEl.textContent = `${username} (${ROLE_LABELS[role] || role})`;
      appScreen.hidden = false;
      navButtons.support.hidden = role !== "operator";
      navButtons.dialogues.hidden = role !== "operator";
      navButtons.approvals.hidden = role !== "operator";
      setSection("teams");
      showTeamsListView();
      startPendingItemsPolling();
    },
  };
})();
