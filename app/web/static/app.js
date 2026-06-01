var App = window.App || (window.App = {});

function isMobileDevice() {
  const ua = navigator.userAgent || "";
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Windows Phone|Mobile/i.test(ua);
}

function lockMobileZoom() {
  if (!isMobileDevice()) return;

  const viewportMeta = document.querySelector('meta[name="viewport"]');
  if (!viewportMeta) return;

  viewportMeta.setAttribute(
    "content",
    "width=device-width, initial-scale=1.0, minimum-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover"
  );

  document.addEventListener(
    "gesturestart",
    (event) => {
      event.preventDefault();
    },
    { passive: false }
  );
}

function bindEvents() {
  if (App.listeners && App.listeners.common) {
    if (typeof App.listeners.common.bindNavigationEvents === "function") {
      App.listeners.common.bindNavigationEvents();
    }
    if (typeof App.listeners.common.bindCategorySelectorEvents === "function") {
      App.listeners.common.bindCategorySelectorEvents();
    }
    if (typeof App.listeners.common.bindModalCloseEvents === "function") {
      App.listeners.common.bindModalCloseEvents();
    }
    if (typeof App.listeners.common.bindFilterQueryInput === "function") {
      App.listeners.common.bindFilterQueryInput();
    }
    if (typeof App.listeners.common.bindExportEvents === "function") {
      App.listeners.common.bindExportEvents();
    }
  }

  if (App.listeners && App.listeners.records && typeof App.listeners.records.bindRecordsEvents === "function") {
    App.listeners.records.bindRecordsEvents();
  }

  if (App.listeners && App.listeners.budget && typeof App.listeners.budget.bindBudgetEvents === "function") {
    App.listeners.budget.bindBudgetEvents();
  }

  if (App.listeners && App.listeners.settings && typeof App.listeners.settings.bindSettingsEvents === "function") {
    App.listeners.settings.bindSettingsEvents();
  }
}

class FinanceWebApp {
  initTelegram() {
    const adapter = App.adapters && App.adapters.telegram;
    if (!adapter) return;

    const snapshot = adapter.init();
    if (!snapshot) return;

    App.state.tg = snapshot.webApp;
    App.state.initData = snapshot.initData;
  }

  async bootstrap() {
    const dashboard = App.actions.dashboard;

    try {
      this.initTelegram();
      bindEvents();
      dashboard.updatePeriodButtons();

      await dashboard.loadBootstrap();
      await dashboard.loadDashboard();
      App.state.pageLoaded = {
        dashboard: true,
        operations: false,
        analytics: false,
        budget: false,
        settings: true,
      };
      dashboard.restoreLocalState();
      dashboard.restoreDesktopWindowState();
      dashboard.bindDesktopWindowPersistence();
      App.state.period = dashboard.normalizePeriod(App.state.period);
      dashboard.updatePeriodButtons();
      dashboard.applyFilterFormValues();

      App.utils.showToast(App.utils.t("toast.appReady"));
    } catch (error) {
      App.utils.showToast(error.message || App.utils.t("toast.initFailed"), true);
    }
  }
}

const financeWebApp = new FinanceWebApp();

function initTelegram() {
  financeWebApp.initTelegram();
}

async function bootstrapApp() {
  await financeWebApp.bootstrap();
}

document.addEventListener("DOMContentLoaded", () => {
  lockMobileZoom();
  void bootstrapApp();
});


