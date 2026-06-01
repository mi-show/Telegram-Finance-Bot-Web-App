var App = window.App || (window.App = {});

function loadPageData(page) {
  const dashboard = App.actions.dashboard;
  const records = App.actions.records;
  const budget = App.actions.budget;
  const pageLoaded = App.state.pageLoaded || {};

  if (page === "dashboard" && !pageLoaded.dashboard) {
    pageLoaded.dashboard = true;
    void dashboard.loadDashboard();
    return;
  }

  if (page === "operations" && !pageLoaded.operations) {
    pageLoaded.operations = true;
    void records.loadRecords(true);
    return;
  }

  if (page === "analytics" && !pageLoaded.analytics) {
    pageLoaded.analytics = true;
    void budget.loadAnalytics();
    return;
  }

  if (page === "budget" && !pageLoaded.budget) {
    pageLoaded.budget = true;
    void Promise.all([budget.loadBudget(), budget.loadRecurring()]);
  }
}

function bindNavigationEvents() {
  const dashboard = App.actions.dashboard;
  const records = App.actions.records;
  const budget = App.actions.budget;

  document.querySelectorAll(".bottom-nav button").forEach((button) => {
    button.addEventListener("click", () => {
      const page = button.dataset.page;
      dashboard.setActivePage(page);
      requestAnimationFrame(() => loadPageData(page));
    });
  });

  document.querySelectorAll("#periodSwitch button").forEach((button) => {
    button.addEventListener("click", async () => {
      App.state.period = dashboard.normalizePeriod(button.dataset.period);
      budget.clearAnalyticsRange();
      dashboard.updatePeriodButtons();
      dashboard.saveLocalState();
      await Promise.all([dashboard.loadDashboard(), budget.loadAnalytics()]);
    });
  });

  document.getElementById("refreshAllBtn").addEventListener("click", async () => {
    await records.refreshAllData();
    App.utils.showToast(App.utils.t("toast.dataRefreshed"));
  });
}

function bindCategorySelectorEvents() {
  const dashboard = App.actions.dashboard;

  document.getElementById("createCategory").addEventListener("change", (event) => {
    dashboard.populateSubcategorySelect(document.getElementById("createSubcategory"), event.target.value || "", "");
  });
  document.getElementById("modalCategory").addEventListener("change", (event) => {
    dashboard.populateSubcategorySelect(document.getElementById("modalSubcategory"), event.target.value || "", "");
  });
  document.getElementById("recurringCategory").addEventListener("change", (event) => {
    dashboard.populateSubcategorySelect(document.getElementById("recurringSubcategory"), event.target.value || "", "");
  });
}

function bindModalCloseEvents() {
  const records = App.actions.records;

  document.querySelectorAll(".modal-backdrop").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target !== modal) return;
      if (modal.id === "recordEditModal") {
        records.closeRecordEditModal();
      } else if (modal.id === "recordDeleteModal") {
        records.closeRecordDeleteModal();
      }
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    records.closeRecordEditModal();
    records.closeRecordDeleteModal();
  });
}

function bindFilterQueryInput() {
  const dashboard = App.actions.dashboard;
  const records = App.actions.records;

  document.getElementById("filterQuery").addEventListener("input", async () => {
    clearTimeout(App.runtime.queryDebounceTimer);
    App.runtime.queryDebounceTimer = setTimeout(async () => {
      dashboard.readFilterFormValues();
      dashboard.saveLocalState();
      await records.loadRecords(true);
    }, 320);
  });
}

function bindExportEvents() {
  const records = App.actions.records;

  document.getElementById("exportCsvBtn").addEventListener("click", async () => {
    await records.downloadReport("csv");
  });

  document.getElementById("exportPdfBtn").addEventListener("click", async () => {
    await records.downloadReport("pdf");
  });
}

App.listeners = App.listeners || {};
App.listeners.common = {
  bindNavigationEvents,
  bindCategorySelectorEvents,
  bindModalCloseEvents,
  bindFilterQueryInput,
  bindExportEvents,
};
