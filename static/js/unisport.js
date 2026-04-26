(function () {
  "use strict";

  var STORAGE_KEY = "unisport-theme";

  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setStoredTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {}
  }

  function getPreferredTheme() {
    var stored = getStoredTheme();
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return "dark";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    var btn = document.getElementById("usThemeToggle");
    if (btn) {
      var icon = btn.querySelector("i");
      if (icon) {
        icon.className = theme === "dark" ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
      }
      btn.setAttribute("aria-label", theme === "dark" ? "Светлая тема" : "Тёмная тема");
      btn.title = theme === "dark" ? "Светлая тема" : "Тёмная тема";
    }
  }

  function initTheme() {
    applyTheme(getPreferredTheme());
  }

  function toggleTheme() {
    var current = document.documentElement.getAttribute("data-bs-theme") || "dark";
    var next = current === "dark" ? "light" : "dark";
    setStoredTheme(next);
    applyTheme(next);
  }

  function initScrollTop() {
    var btn = document.getElementById("usScrollTop");
    if (!btn) return;

    function update() {
      if (window.scrollY > 400) {
        btn.classList.add("is-visible");
      } else {
        btn.classList.remove("is-visible");
      }
    }

    window.addEventListener("scroll", update, { passive: true });
    update();

    btn.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();

    var themeBtn = document.getElementById("usThemeToggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", toggleTheme);
    }

    initScrollTop();
  });
})();
