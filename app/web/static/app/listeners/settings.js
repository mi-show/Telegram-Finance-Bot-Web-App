var App = window.App || (window.App = {});

function bindSettingsEvents() {
  const settingsForm = document.getElementById("settingsForm");
  if (!settingsForm) {
    return;
  }

  if (!App.actions || !App.actions.settings || typeof App.actions.settings.saveSettings !== "function") {
    console.error("Settings save handler is not available.");
    return;
  }

  settingsForm.addEventListener("submit", App.actions.settings.saveSettings);
}

App.listeners = App.listeners || {};
App.listeners.settings = {
  bindSettingsEvents,
};
