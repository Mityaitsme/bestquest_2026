(() => {
  "use strict";

  const authScreen = document.getElementById("admin-auth-screen");
  const form = document.getElementById("admin-auth-form");
  const submitButton = document.getElementById("admin-auth-submit");
  const errorEl = document.getElementById("admin-auth-error");

  function showAuthScreen() {
    authScreen.hidden = false;
  }

  function hideAuthScreen() {
    authScreen.hidden = true;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.textContent = "";
    submitButton.disabled = true;

    const username = document.getElementById("admin-username").value.trim();
    const password = document.getElementById("admin-password").value;

    try {
      const response = await fetch("/auth/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json();

      if (!response.ok || data.status !== "ok") {
        errorEl.textContent = data.detail || "Что-то пошло не так";
        return;
      }

      hideAuthScreen();
      window.AdminApp.show(data.username, data.role);
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
      if (data.identity === "admin") {
        window.AdminApp.show(data.username, data.role);
        return;
      }
    } catch (err) {
      // сервер недоступен — просто показываем экран входа
    }
    showAuthScreen();
  }

  init();
})();
