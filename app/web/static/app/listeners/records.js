var App = window.App || (window.App = {});

function bindRecordsEvents() {
  const records = App.actions.records;
  const dashboard = App.actions.dashboard;

  document.getElementById("filtersForm").addEventListener("submit", records.submitFilters);
  document.getElementById("resetFiltersBtn").addEventListener("click", records.resetFilters);
  document.getElementById("createRecordForm").addEventListener("submit", dashboard.submitCreateRecord);
  document.getElementById("recordsBody").addEventListener("click", records.handleRecordTableClick);
  document.getElementById("loadMoreRecordsBtn").addEventListener("click", () => records.loadRecords(false));
  document.getElementById("recordEditForm").addEventListener("submit", records.submitRecordEdit);
  document.getElementById("recordEditCancelBtn").addEventListener("click", records.closeRecordEditModal);
  document.getElementById("recordDeleteCancelBtn").addEventListener("click", records.closeRecordDeleteModal);
  document.getElementById("recordDeleteConfirmBtn").addEventListener("click", records.confirmRecordDelete);

  document.getElementById("createType").addEventListener("change", dashboard.syncCreateRecordIncomeMode);
  document.getElementById("filterType").addEventListener("change", dashboard.syncFilterIncomeMode);
  document.getElementById("createCategory").addEventListener("change", () => {
    if (document.getElementById("createType").value !== "expense") {
      return;
    }
    dashboard.populateSubcategorySelect(
      document.getElementById("createSubcategory"),
      document.getElementById("createCategory").value,
      ""
    );
  });

  document.getElementById("modalType").addEventListener("change", records.syncRecordEditIncomeMode);
  document.getElementById("modalCategory").addEventListener("change", () => {
    if (document.getElementById("modalType").value !== "expense") {
      return;
    }
    dashboard.populateSubcategorySelect(
      document.getElementById("modalSubcategory"),
      document.getElementById("modalCategory").value,
      ""
    );
  });

  dashboard.syncCreateRecordIncomeMode();
  dashboard.syncFilterIncomeMode();
  records.syncRecordEditIncomeMode();
}

App.listeners = App.listeners || {};
App.listeners.records = {
  bindRecordsEvents,
};
