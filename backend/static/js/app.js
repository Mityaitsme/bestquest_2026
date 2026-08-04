(() => {
  "use strict";

  const COMPLETION_TYPE_LABELS = {
    actor: "автоматически",
    answer: "ответ",
    checkbox: "подтвердите",
    manual_review: "на проверку",
  };

  const CHAT_MODE_LABELS = {
    scripted: "сценарий",
    operator: "онлайн",
    gpt: "онлайн",
    muted: "тихо",
  };

  const FETCH_RETRY_ATTEMPTS = 3;
  const FETCH_RETRY_DELAY_MS = 400;

  // Обёртка над fetch для GET-запросов на чтение: если запрос не долетел или
  // ответ не распарсился как JSON (сетевой сбой, временная ошибка сервера) —
  // тихо повторяет попытку ещё пару раз с небольшой паузой, прежде чем
  // отдать ошибку вызывающему коду. Только для чтения — запросы, меняющие
  // данные (POST), так не оборачиваем, чтобы не повторить одно и то же
  // действие дважды.
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

  // Если в этом же браузере (в другой вкладке) вошли под другой командой
  // или админом — сессия (cookie) на весь браузер одна, и эта вкладка
  // молча перестаёт быть залогинена. Раньше это выглядело как "всё вдруг
  // перестало грузиться без единой ошибки на экране" — теперь вместо
  // молчаливого провала показываем понятное сообщение и перезагружаем
  // страницу, чтобы попасть на актуальный для этого браузера экран входа.
  let sessionExpiredHandled = false;
  function handleSessionExpired() {
    if (sessionExpiredHandled) {
      return;
    }
    sessionExpiredHandled = true;
    stopMessagePolling();
    showToast("Сессия сброшена — похоже, в этом браузере вошли под другим аккаунтом. Перезагружаем…");
    setTimeout(() => window.location.reload(), 1800);
  }

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
  let tasksRequestId = 0;
  let knownAvailableStageIds = new Set();
  let hasRenderedTasksOnce = false;

  const TASK_CARD_EXIT_MS = 260;

  function animateTaskCardExit(card) {
    return new Promise((resolve) => {
      if (!card) {
        resolve();
        return;
      }
      card.classList.add("task-card--exit");
      setTimeout(resolve, TASK_CARD_EXIT_MS);
    });
  }

  const chatListViewEl = document.getElementById("chat-list-view");
  const chatDetailViewEl = document.getElementById("chat-detail-view");
  const chatListEl = document.getElementById("chat-list");
  const chatListEmptyEl = document.getElementById("chat-list-empty");
  const chatBackButton = document.getElementById("chat-back-button");
  const chatDetailTitle = document.getElementById("chat-detail-title");
  const chatMessagesEl = document.getElementById("chat-messages");
  const chatInputRow = document.getElementById("chat-input-row");
  const chatInput = document.getElementById("chat-input");
  const chatSendButton = document.getElementById("chat-send-button");
  const chatOptionsEl = document.getElementById("chat-options");
  const chatReadonlyNote = document.getElementById("chat-readonly-note");
  const toastContainerEl = document.getElementById("toast-container");

  let currentChat = null;
  let allChats = [];
  const unreadChatIds = new Set();

  function setTab(tab) {
    for (const key of Object.keys(panels)) {
      panels[key].hidden = key !== tab;
      navButtons[key].setAttribute("aria-selected", String(key === tab));
    }
  }

  for (const [tab, button] of Object.entries(navButtons)) {
    button.addEventListener("click", () => setTab(tab));
  }

  navButtons.chat.addEventListener("click", () => {
    chatDetailViewEl.hidden = true;
    chatListViewEl.hidden = false;
    loadChats();
  });

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

    // Разблокированные задачи должны появляться плавно, а не резким скачком —
    // отслеживаем, какие stage_id из "актуальных" уже показывались раньше, и
    // анимируем только по-настоящему новые (не при первой загрузке и не при
    // простом переключении вкладок Актуальные/Выполненные без новых данных).
    let newlyAvailableIds = new Set();
    if (taskView === "available") {
      const currentIds = new Set(items.map((task) => task.stage_id));
      if (hasRenderedTasksOnce) {
        newlyAvailableIds = new Set(
          [...currentIds].filter((id) => !knownAvailableStageIds.has(id))
        );
      }
      knownAvailableStageIds = currentIds;
      hasRenderedTasksOnce = true;
    }

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
      if (newlyAvailableIds.has(task.stage_id)) {
        card.classList.add("task-card--enter");
      }

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

      const action = buildActionArea(task, stage);
      if (action) {
        description.appendChild(action.element);
      }

      card.addEventListener("click", () => {
        const isOpen = card.dataset.open === "true";
        card.dataset.open = isOpen ? "false" : "true";
        if (!isOpen && action && action.onOpen) {
          action.onOpen();
        }
      });

      taskListEl.appendChild(card);
    }

    if (newlyAvailableIds.size > 0) {
      // Небольшая задержка вместо requestAnimationFrame — нужно только
      // отдать браузеру один тик, чтобы он успел применить начальное
      // (невидимое) состояние карточки, прежде чем убрать класс и запустить
      // CSS-переход к конечному виду. rAF для этого не годится: колбэки
      // requestAnimationFrame не выполняются, пока вкладка не композит кадры
      // (например, скрыта/свёрнута), а setTimeout работает всегда.
      setTimeout(() => {
        for (const enteringCard of taskListEl.querySelectorAll(".task-card--enter")) {
          enteringCard.classList.remove("task-card--enter");
        }
      }, 20);
    }
  }

  function buildActionArea(task, stage) {
    if (task.status !== "available") {
      return null;
    }

    if (stage.completion_type === "checkbox") {
      const wrap = document.createElement("div");
      wrap.className = "task-action";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn-primary task-action__button";
      button.textContent = "Подтвердить";

      const error = document.createElement("p");
      error.className = "form-error";

      button.addEventListener("click", async (event) => {
        event.stopPropagation();
        button.disabled = true;
        error.textContent = "";
        try {
          const response = await fetch(`/tasks/${task.stage_id}/checkbox-complete`, {
            method: "POST",
          });
          const data = await response.json();
          if (data.status !== "ok") {
            error.textContent = data.detail || "Не получилось подтвердить";
            button.disabled = false;
            return;
          }
          await animateTaskCardExit(wrap.closest(".task-card"));
          loadTasks();
        } catch (err) {
          error.textContent = "Не удалось связаться с сервером";
          button.disabled = false;
        }
      });

      wrap.appendChild(button);
      wrap.appendChild(error);
      return { element: wrap };
    }

    if (stage.completion_type === "answer") {
      const wrap = document.createElement("div");
      wrap.className = "task-action task-fields";
      wrap.dataset.loadState = "idle";

      return {
        element: wrap,
        onOpen: () => loadAnswerFields(task.stage_id, wrap),
      };
    }

    if (stage.completion_type === "manual_review") {
      return { element: buildManualReviewForm(task) };
    }

    return null;
  }

  function buildManualReviewForm(task) {
    const wrap = document.createElement("div");
    wrap.className = "task-action task-review";
    wrap.addEventListener("click", (event) => event.stopPropagation());

    const status = document.createElement("p");
    status.className = "task-review__status";
    wrap.appendChild(status);

    const textarea = document.createElement("textarea");
    textarea.className = "task-review__textarea";
    textarea.rows = 3;
    textarea.placeholder = "Опишите ваш ответ";
    wrap.appendChild(textarea);

    const fileLabel = document.createElement("label");
    fileLabel.className = "task-review__file-label";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.className = "task-review__file";
    const fileNameSpan = document.createElement("span");
    fileNameSpan.textContent = "Прикрепить фото";
    fileInput.addEventListener("change", () => {
      fileNameSpan.textContent = fileInput.files[0] ? fileInput.files[0].name : "Прикрепить фото";
    });
    fileLabel.appendChild(fileInput);
    fileLabel.appendChild(fileNameSpan);
    wrap.appendChild(fileLabel);

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "btn-primary task-action__button";
    submitBtn.textContent = "Отправить на проверку";
    wrap.appendChild(submitBtn);

    const error = document.createElement("p");
    error.className = "form-error";
    wrap.appendChild(error);

    submitBtn.addEventListener("click", async () => {
      const text = textarea.value.trim();
      const file = fileInput.files[0];
      error.textContent = "";
      if (!text && !file) {
        error.textContent = "Напишите ответ или прикрепите фото";
        return;
      }

      submitBtn.disabled = true;
      status.textContent = "";

      const formData = new FormData();
      formData.append("text", text);
      if (file) {
        formData.append("photo", file);
      }

      try {
        const response = await fetch(`/tasks/${task.stage_id}/manual-review`, {
          method: "POST",
          body: formData,
        });
        const data = await response.json();
        submitBtn.disabled = false;

        if (data.status !== "ok") {
          error.textContent = data.detail || "Не получилось отправить";
          return;
        }

        status.textContent = "Отправлено на проверку — ждите решения оператора.";
        textarea.value = "";
        fileInput.value = "";
        fileNameSpan.textContent = "Прикрепить фото";
      } catch (err) {
        submitBtn.disabled = false;
        error.textContent = "Не удалось связаться с сервером";
      }
    });

    return wrap;
  }

  async function loadAnswerFields(stageId, container) {
    // Состояние загрузки хранится отдельно от результата: если запрос
    // сорвался (временный сбой сети/сервера), состояние должно вернуться в
    // "idle", а не застрять в "уже загружено" навсегда — иначе повторное
    // открытие/закрытие той же карточки просто молча показывало бы старую
    // ошибку и никогда не пробовало бы загрузить поля ещё раз.
    if (container.dataset.loadState === "loading" || container.dataset.loadState === "loaded") {
      return;
    }
    container.dataset.loadState = "loading";
    container.textContent = "Загрузка…";

    try {
      const data = await fetchJsonWithRetry(`/tasks/${stageId}/fields`);
      if (data.status !== "ok") {
        container.dataset.loadState = "idle";
        container.textContent = (data.detail || "Не удалось загрузить поля") + " — откройте задачу ещё раз, чтобы повторить";
        return;
      }

      container.dataset.loadState = "loaded";
      container.innerHTML = "";
      const fields = [...data.fields].sort((a, b) => a.order_position - b.order_position);
      for (const field of fields) {
        renderAnswerField(stageId, field, container);
      }
    } catch (err) {
      container.dataset.loadState = "idle";
      container.textContent = "Не удалось загрузить поля — откройте задачу ещё раз, чтобы повторить";
    }
  }

  function renderAnswerField(stageId, field, container) {
    const row = document.createElement("div");
    row.className = "answer-field" + (field.correct ? " answer-field--correct" : "");

    const label = document.createElement("label");
    label.className = "answer-field__label";
    label.textContent = field.hint ? `${field.label} (${field.hint})` : field.label;
    row.appendChild(label);

    const inputRow = document.createElement("div");
    inputRow.className = "answer-field__row";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "answer-field__input";
    input.autocomplete = "off";
    if (field.correct) {
      input.value = field.submitted_value || "";
      input.disabled = true;
    }
    inputRow.appendChild(input);

    const submitBtn = document.createElement("button");
    submitBtn.type = "button";
    submitBtn.className = "answer-field__submit";
    submitBtn.textContent = "✓";
    submitBtn.disabled = field.correct;
    inputRow.appendChild(submitBtn);

    row.appendChild(inputRow);
    container.appendChild(row);

    async function submit() {
      const value = input.value.trim();
      if (!value) {
        return;
      }
      input.disabled = true;
      submitBtn.disabled = true;
      row.classList.remove("answer-field--error");

      try {
        const response = await fetch(`/tasks/${stageId}/fields/${field.id}/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value }),
        });
        const data = await response.json();

        if (data.status !== "ok") {
          row.classList.add("answer-field--error");
          input.disabled = false;
          submitBtn.disabled = false;
          return;
        }

        if (data.correct) {
          row.classList.add("answer-field--correct");
          input.value = value;
          if (data.stage_completed) {
            await animateTaskCardExit(container.closest(".task-card"));
            loadTasks();
          }
        } else {
          row.classList.add("answer-field--error");
          input.value = "";
          input.disabled = false;
          submitBtn.disabled = false;
        }
      } catch (err) {
        row.classList.add("answer-field--error");
        input.disabled = false;
        submitBtn.disabled = false;
      }
    }

    submitBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      submit();
    });
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });
  }

  function getChatDisplayName(chat) {
    if (chat.chat_type === "support") {
      return "Техподдержка";
    }
    return chat.characters ? chat.characters.name : "Персонаж";
  }

  async function loadChats() {
    try {
      const data = await fetchJsonWithRetry("/chats");
      if (data.status !== "ok") {
        chatListEmptyEl.hidden = false;
        chatListEmptyEl.textContent = "Не удалось загрузить чаты";
        return;
      }
      allChats = data.chats;
      renderChatList(data.chats);
    } catch (err) {
      chatListEmptyEl.hidden = false;
      chatListEmptyEl.textContent = "Не удалось загрузить чаты";
    }
  }

  function renderChatList(chats) {
    chatListEl.innerHTML = "";

    if (chats.length === 0) {
      chatListEmptyEl.hidden = false;
      chatListEmptyEl.textContent = "Чатов пока нет";
      return;
    }
    chatListEmptyEl.hidden = true;

    for (const chat of chats) {
      const name = getChatDisplayName(chat);

      const item = document.createElement("div");
      item.className = "chat-list-item";

      const avatar = document.createElement("div");
      avatar.className = "chat-list-item__avatar";
      avatar.textContent = name.charAt(0).toUpperCase();
      item.appendChild(avatar);

      const info = document.createElement("div");
      info.className = "chat-list-item__info";

      const nameEl = document.createElement("div");
      nameEl.className = "chat-list-item__name";
      nameEl.textContent = name;
      info.appendChild(nameEl);

      const modeEl = document.createElement("div");
      modeEl.className = "chat-list-item__mode";
      modeEl.textContent = CHAT_MODE_LABELS[chat.mode] || chat.mode;
      info.appendChild(modeEl);

      item.appendChild(info);

      if (unreadChatIds.has(chat.id)) {
        const unreadDot = document.createElement("span");
        unreadDot.className = "chat-list-item__unread-dot";
        unreadDot.setAttribute("aria-label", "Есть непрочитанное сообщение");
        item.appendChild(unreadDot);
      }

      item.addEventListener("click", () => openChat(chat, name));
      chatListEl.appendChild(item);
    }
  }

  function openChat(chat, name) {
    currentChat = chat;
    unreadChatIds.delete(chat.id);
    chatDetailTitle.textContent = name;
    chatListViewEl.hidden = true;
    chatDetailViewEl.hidden = false;

    chatInputRow.hidden = true;
    chatOptionsEl.hidden = true;
    chatReadonlyNote.hidden = true;

    if (chat.mode === "operator" || chat.mode === "gpt") {
      chatInputRow.hidden = false;
    } else if (chat.mode === "scripted") {
      chatOptionsEl.hidden = false;
      loadDialogue();
    } else {
      chatReadonlyNote.hidden = false;
      chatReadonlyNote.textContent = "Сейчас в этом чате нельзя писать.";
    }

    loadMessages();
  }

  const TOAST_VISIBLE_MS = 4000;

  function showToast(text, onClick) {
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = text;
    if (onClick) {
      toast.addEventListener("click", onClick);
    }
    toastContainerEl.appendChild(toast);

    // Небольшая задержка вместо requestAnimationFrame — тик, чтобы браузер
    // успел отрисовать начальное (невидимое) состояние тоста, прежде чем
    // запустить CSS-переход; rAF не годится, см. известную особенность
    // непоказанной вкладки браузера в памяти проекта.
    setTimeout(() => toast.classList.add("toast--visible"), 20);
    setTimeout(() => {
      toast.classList.remove("toast--visible");
      setTimeout(() => toast.remove(), 300);
    }, TOAST_VISIBLE_MS);
  }

  const MESSAGE_POLL_INTERVAL_MS = 10000;
  let messagePollTimer = null;
  let lastMessagePollAt = null;

  function startMessagePolling() {
    stopMessagePolling();
    lastMessagePollAt = new Date().toISOString();
    messagePollTimer = setInterval(pollNewMessages, MESSAGE_POLL_INTERVAL_MS);
  }

  function stopMessagePolling() {
    if (messagePollTimer) {
      clearInterval(messagePollTimer);
      messagePollTimer = null;
    }
  }

  async function pollNewMessages() {
    const since = lastMessagePollAt;
    try {
      const response = await fetch(`/chats/new-messages?since=${encodeURIComponent(since)}`);
      if (response.status === 401) {
        handleSessionExpired();
        return;
      }
      const data = await response.json();
      if (data.status !== "ok" || data.messages.length === 0) {
        return;
      }
      lastMessagePollAt = data.messages[data.messages.length - 1].created_at;

      const chatIdsWithNewMessages = new Set(data.messages.map((m) => m.chat_id));

      if (currentChat && chatIdsWithNewMessages.has(currentChat.id)) {
        loadMessages();
        chatIdsWithNewMessages.delete(currentChat.id);
      }

      for (const chatId of chatIdsWithNewMessages) {
        unreadChatIds.add(chatId);
        const chat = allChats.find((c) => c.id === chatId);
        const name = chat ? getChatDisplayName(chat) : "Чат";
        showToast(`Новое сообщение: ${name}`, () => {
          setTab("chat");
          chatListViewEl.hidden = true;
          chatDetailViewEl.hidden = false;
          if (chat) {
            openChat(chat, name);
          } else {
            loadChats();
          }
        });
      }

      // Если список чатов сейчас на экране — сразу перерисовать, чтобы
      // значок непрочитанного появился без ожидания следующего открытия
      // вкладки "Чат".
      if (chatIdsWithNewMessages.size > 0 && !chatListViewEl.hidden) {
        renderChatList(allChats);
      }
    } catch (err) {
      // пропускаем один цикл опроса - следующий тик попробует снова
    }
  }

  async function loadDialogue() {
    if (!currentChat) {
      return;
    }
    const chatId = currentChat.id;
    chatOptionsEl.textContent = "Загрузка…";
    try {
      const data = await fetchJsonWithRetry(`/chats/${chatId}/dialogue`);
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      if (data.status !== "ok") {
        chatOptionsEl.textContent = data.detail || "Не удалось загрузить варианты ответа";
        return;
      }
      renderDialogueOptions(data);
    } catch (err) {
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      chatOptionsEl.textContent = "Не удалось загрузить варианты ответа";
    }
  }

  function renderDialogueOptions(state, note) {
    chatOptionsEl.innerHTML = "";

    if (note) {
      const noteEl = document.createElement("p");
      noteEl.className = "chat-options__note";
      noteEl.textContent = note;
      chatOptionsEl.appendChild(noteEl);
    }

    if (state.finished || !state.options || state.options.length === 0) {
      const empty = document.createElement("p");
      empty.className = "chat-options__note";
      empty.textContent = "Пока новых реплик нет.";
      chatOptionsEl.appendChild(empty);
      return;
    }

    for (const option of state.options) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-option-btn";
      button.textContent = option.text;
      button.addEventListener("click", () => chooseDialogueOption(option.id));
      chatOptionsEl.appendChild(button);
    }
  }

  async function chooseDialogueOption(optionId) {
    if (!currentChat) {
      return;
    }
    const chatId = currentChat.id;
    for (const button of chatOptionsEl.querySelectorAll(".chat-option-btn")) {
      button.disabled = true;
    }

    try {
      const response = await fetch(`/chats/${chatId}/dialogue/options/${optionId}/choose`, {
        method: "POST",
      });
      const data = await response.json();
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      if (data.status !== "ok") {
        for (const button of chatOptionsEl.querySelectorAll(".chat-option-btn")) {
          button.disabled = false;
        }
        return;
      }
      await loadMessages();
      renderDialogueOptions(
        data.state,
        data.pending_approval ? "Ответ отправлен — ждите одобрения оператора." : null
      );
    } catch (err) {
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      for (const button of chatOptionsEl.querySelectorAll(".chat-option-btn")) {
        button.disabled = false;
      }
    }
  }

  chatBackButton.addEventListener("click", () => {
    currentChat = null;
    chatDetailViewEl.hidden = true;
    chatListViewEl.hidden = false;
    loadChats();
  });

  async function loadMessages() {
    if (!currentChat) {
      return;
    }
    const chatId = currentChat.id;
    chatMessagesEl.textContent = "Загрузка…";
    try {
      const data = await fetchJsonWithRetry(`/chats/${chatId}/messages`);
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      if (data.status !== "ok") {
        chatMessagesEl.textContent = "Не удалось загрузить сообщения";
        return;
      }
      renderMessages(data.messages);
    } catch (err) {
      if (!currentChat || currentChat.id !== chatId) {
        return;
      }
      chatMessagesEl.textContent = "Не удалось загрузить сообщения";
    }
  }

  function renderMessages(messages) {
    chatMessagesEl.innerHTML = "";
    for (const message of messages) {
      const bubble = document.createElement("div");
      const isTeam = message.sender_type === "team";
      bubble.className = "chat-bubble " + (isTeam ? "chat-bubble--team" : "chat-bubble--other");
      if (message.message_kind === "support_comment") {
        bubble.classList.add("chat-bubble--support");
      }
      bubble.textContent = message.content;
      chatMessagesEl.appendChild(bubble);
    }
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  }

  async function sendChatMessage() {
    const content = chatInput.value.trim();
    if (!content || !currentChat) {
      return;
    }
    const chatId = currentChat.id;
    chatSendButton.disabled = true;
    chatInput.disabled = true;

    try {
      const response = await fetch(`/chats/${chatId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      const data = await response.json();
      if (data.status === "ok") {
        chatInput.value = "";
        await loadMessages();
      }
    } catch (err) {
      // сообщение просто не появится - можно попробовать отправить ещё раз
    } finally {
      chatSendButton.disabled = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  chatSendButton.addEventListener("click", sendChatMessage);
  chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      sendChatMessage();
    }
  });

  async function loadTasks() {
    // Несколько вызовов loadTasks() могут оказаться в полёте одновременно
    // (повторная загрузка после отправки ответа, ручное переключение и т.п.).
    // Без этой защиты более ранний, но медленнее ответивший запрос мог бы
    // перезаписать экран уже устаревшими данными, придя позже нового.
    const requestId = ++tasksRequestId;
    try {
      const data = await fetchJsonWithRetry("/tasks");
      if (requestId !== tasksRequestId) {
        return;
      }
      if (data.status === "ok") {
        allTasks = data.tasks;
        renderTasks();
      }
    } catch (err) {
      if (requestId !== tasksRequestId) {
        return;
      }
      taskEmptyEl.hidden = false;
      taskEmptyEl.textContent = "Не удалось загрузить задачи";
    }
  }

  const dialerViewEl = document.getElementById("dialer-view");
  const dialerDisplayEl = document.getElementById("dialer-display");
  const dialerKeypadEl = document.getElementById("dialer-keypad");
  const dialerBackspaceBtn = document.getElementById("dialer-backspace");
  const dialerCallBtn = document.getElementById("dialer-call");

  const callViewEl = document.getElementById("call-view");
  const callStatusEl = document.getElementById("call-status");
  const callAudioEl = document.getElementById("call-audio");
  const passwordSectionEl = document.getElementById("call-password-section");
  const passwordDisplayEl = document.getElementById("password-display");
  const passwordKeypadEl = document.getElementById("password-keypad");
  const passwordSubmitBtn = document.getElementById("password-submit");
  const callEndButton = document.getElementById("call-end");

  const KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];
  const CALL_OUTCOME_MESSAGES = {
    nonexistent: "Такого номера не существует.",
    unavailable: "Абонент недоступен.",
    prank: "…что-то пошло не так с этим номером.",
  };

  let dialedNumber = "";
  let currentPhaseId = null;

  function buildKeypad(container, onPress) {
    container.innerHTML = "";
    for (const key of KEYPAD_KEYS) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "keypad__btn";
      btn.textContent = key;
      btn.addEventListener("click", () => onPress(key));
      container.appendChild(btn);
    }
  }

  buildKeypad(dialerKeypadEl, (key) => {
    dialedNumber += key;
    dialerDisplayEl.textContent = dialedNumber;
  });

  dialerBackspaceBtn.addEventListener("click", () => {
    dialedNumber = dialedNumber.slice(0, -1);
    dialerDisplayEl.textContent = dialedNumber;
  });

  function resetToDialer() {
    dialedNumber = "";
    dialerDisplayEl.textContent = "";
    currentPhaseId = null;
    callViewEl.hidden = true;
    dialerViewEl.hidden = false;
  }

  function renderCallAudio(audioUrl) {
    callAudioEl.innerHTML = "";
    if (!audioUrl) {
      return;
    }
    // Реальная аудиозапись хранится в Storage и приходит настоящей ссылкой;
    // для фаз, для которых контент-автор ещё не записал звук, audio_url —
    // просто произвольная строка, показываем её как текст-заглушку.
    if (/^https?:\/\//.test(audioUrl)) {
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.autoplay = true;
      audio.src = audioUrl;
      callAudioEl.appendChild(audio);
    } else {
      callAudioEl.textContent = `🔊 ${audioUrl}`;
    }
  }

  function showCallResult(data) {
    dialerViewEl.hidden = true;
    callViewEl.hidden = false;
    passwordSectionEl.hidden = true;
    passwordDisplayEl.value = "";

    if (!data.connected) {
      callStatusEl.textContent = data.outcome
        ? CALL_OUTCOME_MESSAGES[data.outcome] || "Звонок сброшен."
        : "Звонок сброшен.";
      renderCallAudio("");
      currentPhaseId = null;
      return;
    }

    currentPhaseId = data.phase_id;
    callStatusEl.textContent = "Воспроизводится аудио:";
    renderCallAudio(data.audio_url);

    if (data.requires_password) {
      passwordSectionEl.hidden = false;
    }
  }

  dialerCallBtn.addEventListener("click", async () => {
    if (!dialedNumber) {
      return;
    }
    dialerCallBtn.disabled = true;
    try {
      const response = await fetch("/calls/dial", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ number: dialedNumber }),
      });
      const data = await response.json();
      if (data.status === "ok") {
        showCallResult(data);
      }
    } catch (err) {
      // остаёмся на наборе номера - можно попробовать ещё раз
    } finally {
      dialerCallBtn.disabled = false;
    }
  });

  buildKeypad(passwordKeypadEl, (key) => {
    passwordDisplayEl.value += key;
  });

  passwordSubmitBtn.addEventListener("click", async () => {
    const password = passwordDisplayEl.value.trim();
    if (!currentPhaseId || !password) {
      return;
    }
    passwordSubmitBtn.disabled = true;
    try {
      const response = await fetch(`/calls/phases/${currentPhaseId}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await response.json();
      if (data.status === "ok") {
        showCallResult(data);
      }
    } catch (err) {
      // остаёмся на текущем экране - можно попробовать ввести пароль ещё раз
    } finally {
      passwordSubmitBtn.disabled = false;
    }
  });

  passwordDisplayEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      passwordSubmitBtn.click();
    }
  });

  callEndButton.addEventListener("click", resetToDialer);
  navButtons.calls.addEventListener("click", resetToDialer);

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
      loadChats(); // заранее знаем имена чатов для тостов, даже если команда ещё не открывала вкладку "Чат"
      startMessagePolling();
    },
  };
})();
