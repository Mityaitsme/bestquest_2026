(() => {
  "use strict";

  const COMPLETION_TYPE_LABELS = {
    actor: "отмечает актёр",
    answer: "введите ответ",
    checkbox: "подтвердите",
    manual_review: "на проверку",
  };

  const CHAT_MODE_LABELS = {
    scripted: "сценарий",
    operator: "онлайн",
    gpt: "онлайн",
    muted: "тихо",
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
  let tasksRequestId = 0;

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
  const chatReadonlyNote = document.getElementById("chat-readonly-note");

  let currentChat = null;

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
      wrap.dataset.loaded = "false";

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
    if (container.dataset.loaded === "true") {
      return;
    }
    container.dataset.loaded = "true";
    container.textContent = "Загрузка…";

    try {
      const response = await fetch(`/tasks/${stageId}/fields`);
      const data = await response.json();
      if (data.status !== "ok") {
        container.textContent = data.detail || "Не удалось загрузить поля";
        return;
      }

      container.innerHTML = "";
      const fields = [...data.fields].sort((a, b) => a.order_position - b.order_position);
      for (const field of fields) {
        renderAnswerField(stageId, field, container);
      }
    } catch (err) {
      container.textContent = "Не удалось загрузить поля";
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

  async function loadChats() {
    try {
      const response = await fetch("/chats");
      const data = await response.json();
      if (data.status !== "ok") {
        chatListEmptyEl.hidden = false;
        chatListEmptyEl.textContent = "Не удалось загрузить чаты";
        return;
      }
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
      const isSupport = chat.chat_type === "support";
      const name = isSupport ? "Техподдержка" : (chat.characters ? chat.characters.name : "Персонаж");

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
      item.addEventListener("click", () => openChat(chat, name));
      chatListEl.appendChild(item);
    }
  }

  function openChat(chat, name) {
    currentChat = chat;
    chatDetailTitle.textContent = name;
    chatListViewEl.hidden = true;
    chatDetailViewEl.hidden = false;

    const canSend = chat.mode === "operator" || chat.mode === "gpt";
    chatInputRow.hidden = !canSend;
    chatReadonlyNote.hidden = canSend;
    if (!canSend) {
      chatReadonlyNote.textContent =
        chat.mode === "scripted"
          ? "В этом чате пока доступны только варианты ответа (появятся на следующем этапе)."
          : "Сейчас в этом чате нельзя писать.";
    }

    loadMessages();
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
      const response = await fetch(`/chats/${chatId}/messages`);
      const data = await response.json();
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
      const response = await fetch("/tasks");
      const data = await response.json();
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
