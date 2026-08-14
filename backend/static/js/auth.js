(() => {
  "use strict";

  const authScreen = document.getElementById("auth-screen");

  const tabLogin = document.getElementById("tab-login");
  const tabRegister = document.getElementById("tab-register");
  const form = document.getElementById("auth-form");
  const submitButton = document.getElementById("auth-submit");
  const errorEl = document.getElementById("auth-error");

  let mode = "login";

  function showAuthScreen() {
    authScreen.hidden = false;
    document.title = "BestQuest — вход";
  }

  function hideAuthScreen() {
    authScreen.hidden = true;
    document.title = "BestQuest";
  }

  function setMode(newMode) {
    mode = newMode;
    tabLogin.setAttribute("aria-selected", String(mode === "login"));
    tabRegister.setAttribute("aria-selected", String(mode === "register"));
    submitButton.textContent = mode === "login" ? "Войти" : "Создать команду";
    errorEl.textContent = "";
  }

  tabLogin.addEventListener("click", () => setMode("login"));
  tabRegister.addEventListener("click", () => setMode("register"));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    submitButton.disabled = true;

    const name = document.getElementById("team-name").value.trim();
    const password = document.getElementById("team-password").value;
    const endpoint = mode === "login" ? "/auth/team/login" : "/auth/team/register";

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, password }),
      });
      const data = await response.json();

      if (!response.ok || data.status !== "ok") {
        errorEl.textContent = data.detail || "Что-то пошло не так";
        return;
      }

      hideAuthScreen();
      window.QuestApp.show(data.name);
    } catch (err) {
      errorEl.textContent = "Не удалось связаться с сервером";
    } finally {
      submitButton.disabled = false;
    }
  });

  async function init() {
    try {
      const response = await fetch("/auth/me");
      const data = await response.json();
      if (data.identity === "team") {
        document.title = "BestQuest";
        window.QuestApp.show(data.name);
        return;
      }
    } catch (err) {
      // сервер недоступен — просто показываем экран входа
    }
    setMode("login");
    showAuthScreen();
  }

  init();
})();
