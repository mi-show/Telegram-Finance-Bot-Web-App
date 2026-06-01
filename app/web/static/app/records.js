var App = window.App || (window.App = {});

const RECORDS_LIMIT_ALERT_MODES = new Set(["always", "threshold_50", "threshold_70"]);

function normalizeRecordsLimitAlertMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return RECORDS_LIMIT_ALERT_MODES.has(normalized) ? normalized : "threshold_70";
}

function limitItemKey(item) {
  const category = String(item.category || "").trim();
  const subcategory = String(item.subcategory || "").trim();
  return `${category}::${subcategory}`;
}

function appendRecordRows(items) {
  const body = document.getElementById("recordsBody");

  if (items.length === 0 && state.records.offset === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = t("messages.noRecords");
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  for (const record of items) {
    state.records.map.set(record.id, record);
    const typeLabel = record.type === "income" ? t("filters.income") : t("filters.expense");
    const row = document.createElement("tr");

    const dateCell = document.createElement("td");
    dateCell.textContent = record.happened_on;

    const descriptionCell = document.createElement("td");
    descriptionCell.textContent = record.description || "-";

    const categoryCell = document.createElement("td");
    categoryCell.textContent = `${record.category}${record.subcategory ? ` (${record.subcategory})` : ""}`;

    const typeCell = document.createElement("td");
    typeCell.textContent = typeLabel;

    const amountCell = document.createElement("td");
    amountCell.textContent = formatAmount(record.amount);

    const sourceCell = document.createElement("td");
    sourceCell.textContent = t("record.sourceManual");

    const actionsCell = document.createElement("td");
    const actionsWrap = document.createElement("div");
    actionsWrap.className = "row-actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.dataset.editId = String(record.id);
    editButton.textContent = t("actions.edit");

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.dataset.deleteId = String(record.id);
    deleteButton.textContent = t("actions.delete");

    actionsWrap.append(editButton, deleteButton);
    actionsCell.appendChild(actionsWrap);

    row.append(dateCell, descriptionCell, categoryCell, typeCell, amountCell, sourceCell, actionsCell);
    body.appendChild(row);
  }
}

async function loadRecords(reset = false) {
  if (reset) {
    state.records.offset = 0;
    state.records.map.clear();
    document.getElementById("recordsBody").textContent = "";
  }

  const params = buildFilterQueryParams();
  params.set("limit", String(state.records.limit));
  params.set("offset", String(state.records.offset));

  const data = await apiJson(`/api/webapp/records?${params.toString()}`);
  appendRecordRows(data.items || []);

  state.records.offset += (data.items || []).length;
  state.records.hasMore = Boolean(data.paging && data.paging.has_more);

  const moreButton = document.getElementById("loadMoreRecordsBtn");
  moreButton.style.display = state.records.hasMore ? "inline-block" : "none";
}

function openModal(modalElement) {
  if (!modalElement) return;
  modalElement.hidden = false;
  modalElement.classList.add("show");
}

function closeModal(modalElement) {
  if (!modalElement) return;
  modalElement.classList.remove("show");
  modalElement.hidden = true;
}

function getIncomeDefaults() {
  const defaults = (App.config && App.config.incomeDefaults) || {};
  return {
    category: String(defaults.category || "Salary"),
    subcategory: String(defaults.subcategory || "Main"),
  };
}

function ensureSelectOption(selectElement, value) {
  if (!selectElement) return;
  const normalizedValue = String(value || "").trim();
  if (!normalizedValue) return;

  let option = Array.from(selectElement.options).find((item) => item.value === normalizedValue);
  if (!option) {
    option = document.createElement("option");
    option.value = normalizedValue;
    option.textContent = normalizedValue;
    selectElement.appendChild(option);
  }

  selectElement.value = normalizedValue;
}

function syncRecordEditIncomeMode() {
  const typeSelect = document.getElementById("modalType");
  const categorySelect = document.getElementById("modalCategory");
  const subcategorySelect = document.getElementById("modalSubcategory");
  if (!typeSelect || !categorySelect || !subcategorySelect) {
    return;
  }

  const defaults = getIncomeDefaults();
  const isIncome = typeSelect.value === "income";

  if (isIncome) {
    ensureSelectOption(categorySelect, defaults.category);
    populateSubcategorySelect(subcategorySelect, defaults.category, defaults.subcategory);
    ensureSelectOption(subcategorySelect, defaults.subcategory);

    categorySelect.disabled = true;
    categorySelect.required = false;
    subcategorySelect.disabled = true;
    return;
  }

  categorySelect.disabled = false;
  categorySelect.required = true;
  subcategorySelect.disabled = false;

  if (categorySelect.value === defaults.category && !state.categoryOrder.includes(defaults.category)) {
    categorySelect.value = "";
  }

  populateSubcategorySelect(subcategorySelect, categorySelect.value || "", subcategorySelect.value || "");
}

function openRecordEditModal(record) {
  state.records.editingRecordId = record.id;

  fillCategorySelect(document.getElementById("modalCategory"), "filters.chooseCategory", record.category || "");
  populateSubcategorySelect(document.getElementById("modalSubcategory"), record.category || "", record.subcategory || "");

  document.getElementById("modalType").value = record.type;
  document.getElementById("modalAmount").value = String(record.amount || "");
  document.getElementById("modalDate").value = record.happened_on;
  document.getElementById("modalDescription").value = record.description || "";
  if (App.actions && App.actions.dashboard && App.actions.dashboard.refreshIOSDateMirrors) {
    App.actions.dashboard.refreshIOSDateMirrors();
  }

  syncRecordEditIncomeMode();

  openModal(document.getElementById("recordEditModal"));
}

function closeRecordEditModal() {
  state.records.editingRecordId = null;
  closeModal(document.getElementById("recordEditModal"));
}

function openRecordDeleteModal(recordId) {
  state.records.deleteRecordId = recordId;
  document.getElementById("recordDeleteMessage").textContent = t("modal.deleteQuestion");
  openModal(document.getElementById("recordDeleteModal"));
}

function closeRecordDeleteModal() {
  state.records.deleteRecordId = null;
  closeModal(document.getElementById("recordDeleteModal"));
}

async function submitRecordEdit(event) {
  event.preventDefault();

  const id = state.records.editingRecordId;
  if (!id) return;

  const type = document.getElementById("modalType").value;
  const defaults = getIncomeDefaults();
  const isIncome = type === "income";
  const category = isIncome
    ? defaults.category
    : document.getElementById("modalCategory").value.trim();
  const subcategory = isIncome
    ? defaults.subcategory
    : document.getElementById("modalSubcategory").value.trim();
  const amount = Number(document.getElementById("modalAmount").value);
  const happenedOn = document.getElementById("modalDate").value;
  const description = document.getElementById("modalDescription").value.trim();

  if (!isIncome && !category) {
    showToast(t("toast.categoryRequired"), true);
    return;
  }
  if (!happenedOn) {
    showToast(t("toast.dateRequired"), true);
    return;
  }
  if (!description) {
    showToast(t("toast.descriptionRequired"), true);
    return;
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    showToast(t("toast.amountPositive"), true);
    return;
  }
  if (!["income", "expense"].includes(type)) {
    showToast(t("toast.typeIncomeExpense"), true);
    return;
  }

  await apiJson(`/api/webapp/records/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      category,
      subcategory: subcategory || null,
      amount,
      type,
      happened_on: happenedOn,
      description,
    }),
  });

  closeRecordEditModal();
  showToast(t("toast.recordUpdated"));
  await refreshAllData();
}

async function confirmRecordDelete() {
  const id = state.records.deleteRecordId;
  if (!id) return;

  await apiJson(`/api/webapp/records/${id}`, {
    method: "DELETE",
  });

  closeRecordDeleteModal();
  showToast(t("toast.recordDeleted"));
  await refreshAllData();
}

async function handleRecordTableClick(event) {
  const editId = event.target.dataset.editId;
  const deleteId = event.target.dataset.deleteId;

  if (editId) {
    const id = Number(editId);
    const record = state.records.map.get(id);
    if (!record) return;

    openRecordEditModal(record);
    return;
  }

  if (deleteId) {
    openRecordDeleteModal(Number(deleteId));
  }
}

async function refreshAllData() {
  await Promise.all([loadDashboard(), loadRecords(true), loadAnalytics(), loadBudget(), loadRecurring()]);
}

async function submitFilters(event) {
  event.preventDefault();
  readFilterFormValues();
  saveLocalState();
  await loadRecords(true);
}

async function resetFilters() {
  state.resetFilters();
  applyFilterFormValues();
  saveLocalState();
  await loadRecords(true);
}

async function addLimit() {
  const category = document.getElementById("limitCategory").value;
  const rawSub = ((document.getElementById("limitSubcategory") && document.getElementById("limitSubcategory").value) || "").trim();
  const subcategory = rawSub === "" ? null : rawSub;
  const amountValue = Number(document.getElementById("limitAmount").value);

  if (!category) {
    showToast(t("toast.selectCategory"), true);
    return;
  }
  if (!Number.isFinite(amountValue) || amountValue < 0) {
    showToast(t("toast.nonNegativeLimit"), true);
    return;
  }

  const existing = state.budgetLimits.find(
    (item) => item.category === category && (item.subcategory || null) === subcategory
  );
  if (existing) {
    existing.limit = amountValue;
  } else {
    state.budgetLimits.push({
      category,
      subcategory,
      limit: amountValue,
      spent: 0,
      remaining: amountValue,
      status: "normal",
      forecast: 0,
      forecast_used_percent: 0,
      forecast_status: "forecast_normal",
    });
  }

  document.getElementById("limitAmount").value = "";
  renderLimitsTable();
}

async function saveLimits() {
  const period_start = document.getElementById("budgetStart").value;
  const period_end = document.getElementById("budgetEnd").value;
  // determine selected mode; if custom selected, read custom percent
  let limit_alert_mode;
  const select = document.getElementById("limitAlertMode");
  if (select && select.value === "custom") {
    const customInput = document.getElementById("limitAlertCustomPercent");
    const p = Number((customInput && customInput.value) || 70);
    const validP = Number.isFinite(p) && p >= 1 && p <= 100 ? Math.round(p) : 70;
    limit_alert_mode = `threshold_${validP}`;
  } else {
    limit_alert_mode = normalizeRecordsLimitAlertMode((document.getElementById("limitAlertMode") && document.getElementById("limitAlertMode").value) || "");
  }

  if (!period_start || !period_end) {
    showToast(t("toast.setPeriodFirst"), true);
    return;
  }

  const payload = {
    period_start,
    period_end,
    limit_alert_mode,
    limits: state.budgetLimits.map((item) => ({
      category: item.category,
      subcategory: item.subcategory || null,
      limit_amount: Number(item.limit || 0),
    })),
  };

  const snapshot = await apiJson("/api/webapp/budget/category-limits", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  state.budgetLimits = (snapshot.category_limits || []).map((item) => ({
    category: item.category,
    subcategory: item.subcategory || null,
    limit: Number(item.limit || 0),
    spent: Number(item.spent || 0),
    remaining: Number(item.remaining || 0),
    status: item.status || "normal",
    forecast: Number(item.forecast || 0),
    forecast_used_percent: Number(item.forecast_used_percent || 0),
    forecast_status: item.forecast_status || "forecast_normal",
  }));

  const effectiveMode = normalizeRecordsLimitAlertMode(snapshot.limit_alert_mode || limit_alert_mode);
  if (state.settings) {
    state.settings.limit_alert_mode = effectiveMode;
  }
  const alertModeSelect = document.getElementById("limitAlertMode");
  if (alertModeSelect) {
    alertModeSelect.value = effectiveMode;
  }

  renderLimitsTable();
  showToast(t("toast.limitsSaved"));
}

async function saveBudgetPlan(event) {
  event.preventDefault();
  const payload = {
    period_start: document.getElementById("budgetStart").value,
    period_end: document.getElementById("budgetEnd").value,
    planned_expense: Number(document.getElementById("budgetExpense").value),
    planned_income: Number(document.getElementById("budgetIncome").value),
  };

  if (!payload.period_start || !payload.period_end) {
    showToast(t("toast.periodRequired"), true);
    return;
  }

  await apiJson("/api/webapp/budget/month", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  showToast(t("toast.budgetSaved"));
  await Promise.all([loadBudget(), loadDashboard(), loadAnalytics()]);
}

async function handleLimitTableClick(event) {
  const limitKey = event.target.dataset.removeLimitKey;
  if (!limitKey) return;
  state.budgetLimits = state.budgetLimits.filter((item) => limitItemKey(item) !== limitKey);
  renderLimitsTable();
}

async function downloadReport(format) {
  let endpoint = "";
  if (format === "csv") {
    const params = buildFilterQueryParams();
    endpoint = `/api/webapp/export/csv?${params.toString()}`;
  } else {
    endpoint = `/api/webapp/export/pdf?period=${encodeURIComponent(state.period)}`;
  }

  const { blob, response } = await apiBlob(endpoint);
  const disposition = response.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename=([^;]+)/i);
  const filename = filenameMatch ? filenameMatch[1].replace(/"/g, "") : `report.${format}`;

  const tempUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = tempUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(tempUrl);
}

App.actions = App.actions || {};
App.actions.records = {
  loadRecords,
  closeRecordEditModal,
  closeRecordDeleteModal,
  syncRecordEditIncomeMode,
  submitRecordEdit,
  confirmRecordDelete,
  handleRecordTableClick,
  refreshAllData,
  submitFilters,
  resetFilters,
  downloadReport,
};
App.actions.budget = Object.assign(App.actions.budget || {}, {
  addLimit,
  saveLimits,
  saveBudgetPlan,
  handleLimitTableClick,
});


