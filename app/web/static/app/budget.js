var App = window.App || (window.App = {});

const BUDGET_LIMIT_ALERT_MODES = new Set(["always", "threshold_50", "threshold_70", "custom"]);

function normalizeLimitAlertMode(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (BUDGET_LIMIT_ALERT_MODES.has(normalized)) return normalized;
  // accept dynamic threshold_N
  if (normalized.startsWith("threshold_")) {
    const parts = normalized.split("_");
    if (parts.length === 2) {
      const n = Number(parts[1]);
      if (Number.isFinite(n) && n >= 1 && n <= 100) return `threshold_${n}`;
    }
  }
  return "threshold_70";
}

function applyLimitAlertMode(mode) {
  const select = document.getElementById("limitAlertMode");
  const customInput = document.getElementById("limitAlertCustomPercent");
  if (!select) return;
  const normalized = normalizeLimitAlertMode(mode);

  if (normalized.startsWith("threshold_")) {
    const parts = normalized.split("_");
    const n = Number(parts[1]);
    if (n === 50 || n === 70) {
      select.value = `threshold_${n}`;
      if (customInput) customInput.style.display = "none";
    } else {
      select.value = "custom";
      if (customInput) {
        customInput.value = String(n);
        customInput.style.display = "inline-block";
      }
    }
    if (state.settings) state.settings.limit_alert_mode = normalized;
    return;
  }

  select.value = normalized;
  if (customInput) customInput.style.display = normalized === "custom" ? "inline-block" : "none";
  if (state.settings) state.settings.limit_alert_mode = normalized;
}

function limitItemKey(item) {
  const category = String(item.category || "").trim();
  const subcategory = String(item.subcategory || "").trim();
  return `${category}::${subcategory}`;
}

function createStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = "badge";

  if (!status) {
    badge.classList.add("badge-normal");
    badge.textContent = t("status.normal");
    return badge;
  }

  const normalized = String(status);

  if (normalized.includes("exceeded")) {
    badge.classList.add("badge-exceeded");
    badge.textContent = t("status.exceeded");
    return badge;
  }

  if (normalized.includes("near_limit")) {
    badge.classList.add("badge-near");
    badge.textContent = t("status.near_limit");
    return badge;
  }

  badge.classList.add("badge-normal");
  badge.textContent = t("status.normal");
  return badge;
}

function createRecurringStatusBadge(item) {
  const badge = document.createElement("span");
  badge.className = "badge";

  if (!item.is_active) {
    badge.classList.add("badge-muted");
    badge.textContent = t("status.paused");
    return badge;
  }

  if (item.confirmed_for_month) {
    badge.classList.add("badge-normal");
    badge.textContent = t("status.confirmed");
    return badge;
  }

  if (item.reminder_due) {
    badge.classList.add("badge-near");
    badge.textContent = t("status.reminder");
    return badge;
  }

  badge.classList.add("badge-pending");
  badge.textContent = t("status.pending");
  return badge;
}

function renderLimitsTable() {
  const body = document.getElementById("limitsBody");
  body.textContent = "";

  if (state.budgetLimits.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = t("messages.noCategoryLimits");
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  for (const item of state.budgetLimits) {
    const row = document.createElement("tr");

    const categoryCell = document.createElement("td");
    categoryCell.textContent = item.subcategory ? `${item.category} (${item.subcategory})` : item.category;

    const limitCell = document.createElement("td");
    limitCell.textContent = formatAmount(item.limit);

    const spentCell = document.createElement("td");
    spentCell.textContent = formatAmount(item.spent || 0);

    const remainingCell = document.createElement("td");
    remainingCell.textContent = formatAmount(item.remaining || 0);

    const forecastCell = document.createElement("td");
    const forecastAmount = Number(item.forecast || 0);
    const forecastPercent = Number(item.forecast_used_percent || 0);
    forecastCell.textContent = `${formatAmount(forecastAmount)} (${forecastPercent.toFixed(1)}%)`;

    if (item.forecast_status && item.forecast_status !== "forecast_normal") {
      forecastCell.appendChild(document.createTextNode(" "));
      forecastCell.appendChild(createStatusBadge(item.forecast_status));
    }

    const statusCell = document.createElement("td");
    statusCell.appendChild(createStatusBadge(item.status || "normal"));

    const actionCell = document.createElement("td");
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.dataset.removeLimitKey = limitItemKey(item);
    removeButton.textContent = t("actions.remove");
    actionCell.appendChild(removeButton);

    row.append(categoryCell, limitCell, spentCell, remainingCell, forecastCell, statusCell, actionCell);
    body.appendChild(row);
  }
}

function renderRecurringRows(items = []) {
  const body = document.getElementById("recurringBody");
  body.textContent = "";

  if (!items || items.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = t("messages.noRecurring");
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  for (const item of items) {
    const row = document.createElement("tr");

    const titleCell = document.createElement("td");
    titleCell.textContent = item.title;

    const typeCell = document.createElement("td");
    typeCell.textContent = item.type === "income" ? t("filters.income") : t("filters.expense");

    const categoryCell = document.createElement("td");
    categoryCell.textContent = `${item.category}${item.subcategory ? ` (${item.subcategory})` : ""}`;

    const amountCell = document.createElement("td");
    amountCell.textContent = formatAmount(item.amount);

    const dueCell = document.createElement("td");
    dueCell.textContent = item.due_date ? `${item.day_of_month} (${item.due_date})` : String(item.day_of_month);

    const statusCell = document.createElement("td");
    statusCell.appendChild(createRecurringStatusBadge(item));

    const actionsCell = document.createElement("td");
    const wrap = document.createElement("div");
    wrap.className = "row-actions";

    const toggleButton = document.createElement("button");
    toggleButton.type = "button";
    toggleButton.dataset.toggleRecurringId = String(item.id);
    toggleButton.dataset.nextActive = item.is_active ? "0" : "1";
    toggleButton.textContent = item.is_active ? t("actions.pause") : t("actions.resume");
    wrap.appendChild(toggleButton);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.dataset.deleteRecurringId = String(item.id);
    deleteButton.textContent = t("actions.delete");
    wrap.appendChild(deleteButton);

    actionsCell.appendChild(wrap);

    row.append(titleCell, typeCell, categoryCell, amountCell, dueCell, statusCell, actionsCell);
    body.appendChild(row);
  }
}

async function loadBudget() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const data = await apiJson(`/api/webapp/budget?year=${year}&month=${month}`);

  document.getElementById("budgetStart").value = data.period_start;
  document.getElementById("budgetEnd").value = data.period_end;
  if (App.actions && App.actions.dashboard && App.actions.dashboard.refreshIOSDateMirrors) {
    App.actions.dashboard.refreshIOSDateMirrors();
  }

  const monthly = data.monthly_plan || {};
  document.getElementById("budgetExpense").value = monthly.planned_expense ?? "";
  document.getElementById("budgetIncome").value = monthly.planned_income ?? "";

  const statusText = document.getElementById("budgetPlanStatus");
  let summary = `${t("budget.spent")}: ${formatAmount(monthly.spent || 0)} | ${t("budget.remaining")}: ${formatAmount(
    monthly.remaining || 0
  )} | ${t("budget.used")}: ${(monthly.used_percent || 0).toFixed(2)}%`;

  const forecastAlerts = data.forecast_alerts || [];
  if (forecastAlerts.length > 0) {
    const alertCategories = forecastAlerts.slice(0, 3).map((item) => item.category).join(", ");
    summary += ` | ${t("table.forecast")}: ${alertCategories}`;
  }
  statusText.textContent = summary;

  state.budgetLimits = (data.category_limits || []).map((item) => ({
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

  applyLimitAlertMode(data.limit_alert_mode || (state.settings && state.settings.limit_alert_mode) || "threshold_70");

  renderLimitsTable();

  // store current monthly plan for UI actions and render selected budget card
  state.currentBudget =
    monthly && monthly.id
      ? { ...monthly, period_start: data.period_start, period_end: data.period_end }
      : null;
  renderSelectedBudgetCard();
}

function renderSelectedBudgetCard() {
  const container = document.getElementById("selectedBudgetCard");
  if (!container) return;
  container.textContent = "";

  if (!state.currentBudget || !state.currentBudget.id) {
    // nothing selected
    return;
  }

  const plan = state.currentBudget;
  const wrap = document.createElement("div");
  wrap.className = "selected-budget-wrap";
  const title = document.createElement("div");
  title.textContent = `План: ${plan.planned_expense ?? ""} | ${plan.period_start} — ${plan.period_end}`;
  title.style.marginBottom = "6px";

  const actions = document.createElement("div");
  actions.className = "inline-actions";

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "ghost-btn";
  delBtn.textContent = t("actions.delete") || "Удалить";
  delBtn.onclick = async () => {
    if (!window.confirm(t("modal.deleteQuestion"))) return;
    await deleteBudget(plan.id);
  };
  actions.appendChild(delBtn);

  wrap.appendChild(title);
  wrap.appendChild(actions);
  container.appendChild(wrap);
}

async function deleteBudget(budgetId) {
  if (!budgetId) return;
  const resp = await apiJson(`/api/webapp/budget/${budgetId}`, { method: "DELETE" });
  const deleted = resp && resp.deleted ? resp.deleted : null;

  const undoAction = async () => {
    if (!deleted) return;
    // recreate budget from deleted payload
    await apiJson("/api/webapp/budget/month", {
      method: "PUT",
      body: JSON.stringify({
        period_start: deleted.period_start,
        period_end: deleted.period_end,
        planned_expense: deleted.planned_expense,
        planned_income: deleted.planned_income || 0,
      }),
    });
    await Promise.all([loadBudget(), loadDashboard(), loadAnalytics()]);
    showToast(t("toast.budgetRestored") || "Бюджет восстановлен");
  };

  showToastWithAction(t("toast.budgetDeleted") || "Бюджет удалён", t("actions.undo") || "Отменить", undoAction);
  // refresh data
  await Promise.all([loadBudget(), loadDashboard(), loadAnalytics()]);
}

async function loadRecurring() {
  const data = await apiJson("/api/webapp/recurring");
  state.recurring.items = data.items || [];
  renderRecurringRows(state.recurring.items);
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

function syncRecurringIncomeMode() {
  const typeSelect = document.getElementById("recurringType");
  const categorySelect = document.getElementById("recurringCategory");
  const subcategorySelect = document.getElementById("recurringSubcategory");
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

  populateSubcategorySelect(subcategorySelect, categorySelect.value || "", "");
}

async function createRecurring(event) {
  event.preventDefault();

  const title = document.getElementById("recurringTitle").value.trim();
  const type = document.getElementById("recurringType").value;
  const defaults = getIncomeDefaults();
  const isIncome = type === "income";
  const category = isIncome
    ? defaults.category
    : document.getElementById("recurringCategory").value.trim();
  const subcategory = isIncome
    ? defaults.subcategory
    : document.getElementById("recurringSubcategory").value.trim();
  const amount = Number(document.getElementById("recurringAmount").value);
  const dayOfMonth = Number(document.getElementById("recurringDay").value);
  const reminderDays = Number(document.getElementById("recurringReminderDays").value);
  const isActive = document.getElementById("recurringActive").checked;

  if (!title) {
    showToast(t("toast.descriptionRequired"), true);
    return;
  }
  if (!isIncome && !category) {
    showToast(t("toast.categoryRequired"), true);
    return;
  }
  if (!Number.isFinite(amount) || amount <= 0) {
    showToast(t("toast.amountPositive"), true);
    return;
  }
  if (!Number.isInteger(dayOfMonth) || dayOfMonth < 1 || dayOfMonth > 31) {
    showToast(t("toast.dateRequired"), true);
    return;
  }

  await apiJson("/api/webapp/recurring", {
    method: "POST",
    body: JSON.stringify({
      title,
      type,
      category,
      subcategory: subcategory || null,
      amount,
      currency: (state.settings && state.settings.currency) || "UAH",
      day_of_month: dayOfMonth,
      reminder_days_before: Number.isFinite(reminderDays) ? Math.max(0, Math.min(15, reminderDays)) : 0,
      is_active: isActive,
    }),
  });

  document.getElementById("recurringTitle").value = "";
  document.getElementById("recurringAmount").value = "";
  syncRecurringIncomeMode();
  showToast(t("toast.recurringCreated"));
  await Promise.all([loadRecurring(), loadBudget(), loadDashboard(), loadAnalytics()]);
}

async function toggleRecurring(recurringId, isActive) {
  await apiJson(`/api/webapp/recurring/${recurringId}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: isActive }),
  });
  showToast(t("toast.recurringUpdated"));
  await loadRecurring();
}

async function deleteRecurring(recurringId) {
  await apiJson(`/api/webapp/recurring/${recurringId}`, {
    method: "DELETE",
  });
  showToast(t("toast.recurringUpdated"));
  await loadRecurring();
}

async function handleRecurringTableClick(event) {
  const toggleId = event.target.dataset.toggleRecurringId;
  const deleteId = event.target.dataset.deleteRecurringId;

  if (toggleId) {
    const nextActive = event.target.dataset.nextActive === "1";
    await toggleRecurring(Number(toggleId), nextActive);
    return;
  }

  if (deleteId) {
    const ok = window.confirm(t("modal.deleteQuestion"));
    if (!ok) return;
    await deleteRecurring(Number(deleteId));
  }
}

async function saveSettings(event) {
  event.preventDefault();

  const fullscreenToggle = document.getElementById("settingFullscreen");

  const payload = {
    theme: document.getElementById("settingTheme").value,
    currency: document.getElementById("settingCurrency").value.trim().toUpperCase() || "UAH",
    interface_language: document.getElementById("settingLanguage").value,
    notifications_enabled: document.getElementById("settingNotifications").checked,
    desktop_fullscreen_enabled: Boolean(fullscreenToggle && fullscreenToggle.checked),
    hidden_blocks: [],
    budget_warning_percent: Number((document.getElementById("settingBudgetWarning") && document.getElementById("settingBudgetWarning").value) || 80),
    budget_danger_percent: Number((document.getElementById("settingBudgetDanger") && document.getElementById("settingBudgetDanger").value) || 100),
  };

  if (payload.budget_warning_percent >= payload.budget_danger_percent) {
    showToast(t("toast.budgetThresholdsInvalid"), true);
    return;
  }

  const saved = await apiJson("/api/webapp/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  state.settings = saved;
  applyTheme(saved.theme || "dark");
  fillSettingsForm(saved);
  if (App.actions && App.actions.dashboard && App.actions.dashboard.applyDesktopFullscreenPreference) {
    App.actions.dashboard.applyDesktopFullscreenPreference({ interactive: true });
  }
  await loadCategoriesByLanguage(saved.interface_language || "uk");
  applyTranslationsToDom();
  await refreshAllData();
  showToast(t("toast.settingsSaved"));
}

function analyticsLocaleForLanguage() {
  const lang = String(currentLanguage() || "en").toLowerCase();
  if (lang === "ru") return "ru-RU";
  if (lang === "uk") return "uk-UA";
  return "en-US";
}

function parseIsoDate(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const [year, month, day] = raw.split("-").map((part) => Number(part));
  if (!year || !month || !day) return null;
  const parsed = new Date(year, month - 1, day);
  if (!Number.isFinite(parsed.getTime())) return null;
  return parsed;
}

function formatIsoDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatAnalyticsDateLabel(value) {
  const parsed = parseIsoDate(value);
  if (!parsed) return String(value || "");
  try {
    return new Intl.DateTimeFormat(analyticsLocaleForLanguage(), {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(parsed);
  } catch (_error) {
    return String(value || "");
  }
}

function syncAnalyticsRangeInputs() {
  const fromInput = document.getElementById("analyticsDateFrom");
  const toInput = document.getElementById("analyticsDateTo");
  if (fromInput) fromInput.value = String(state.analytics.dateFrom || "");
  if (toInput) toInput.value = String(state.analytics.dateTo || "");
  if (App.actions && App.actions.dashboard && App.actions.dashboard.refreshIOSDateMirrors) {
    App.actions.dashboard.refreshIOSDateMirrors();
  }
}

function clearAnalyticsRange() {
  state.analytics.dateFrom = "";
  state.analytics.dateTo = "";
  syncAnalyticsRangeInputs();
}

function setAnalyticsRange(dateFrom, dateTo) {
  state.analytics.dateFrom = String(dateFrom || "").trim();
  state.analytics.dateTo = String(dateTo || "").trim();
  syncAnalyticsRangeInputs();
}

function hasAnalyticsCustomRange() {
  return Boolean(state.analytics.dateFrom && state.analytics.dateTo);
}

function buildAnalyticsUrl() {
  const params = new URLSearchParams();
  params.set("period", state.period);
  if (hasAnalyticsCustomRange()) {
    params.set("date_from", state.analytics.dateFrom);
    params.set("date_to", state.analytics.dateTo);
  }
  return `/api/webapp/analytics?${params.toString()}`;
}

function updateAnalyticsRangeCaption(period = null) {
  const caption = document.getElementById("analyticsRangeCaption");
  if (!caption) return;

  const from = String((period && period.from) || state.analytics.lastPeriodFrom || "").trim();
  const to = String((period && period.to) || state.analytics.lastPeriodTo || "").trim();
  if (!from || !to) {
    caption.textContent = "";
    return;
  }

  const modeLabel = hasAnalyticsCustomRange() ? t("analytics.rangeCustomTag") : t("analytics.rangePresetTag");
  caption.textContent = `${t("analytics.rangeShown")}: ${formatAnalyticsDateLabel(from)} - ${formatAnalyticsDateLabel(to)} (${modeLabel})`;
}

function analyticsMonthBoundsForAnchor(offsetMonths = 0) {
  const anchorRaw = state.analytics.dateTo || state.analytics.lastPeriodTo;
  const anchor = parseIsoDate(anchorRaw) || new Date();
  const start = new Date(anchor.getFullYear(), anchor.getMonth() + offsetMonths, 1);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  return {
    from: formatIsoDate(start),
    to: formatIsoDate(end),
  };
}

async function applyAnalyticsRange(event) {
  event.preventDefault();
  const fromInput = document.getElementById("analyticsDateFrom");
  const toInput = document.getElementById("analyticsDateTo");
  const dateFrom = String((fromInput && fromInput.value) || "").trim();
  const dateTo = String((toInput && toInput.value) || "").trim();

  if (!dateFrom || !dateTo) {
    showToast(t("analytics.rangeBothDates"), true);
    return;
  }
  if (dateFrom > dateTo) {
    showToast(t("analytics.rangeOrderInvalid"), true);
    return;
  }

  setAnalyticsRange(dateFrom, dateTo);
  await loadAnalytics();
}

async function resetAnalyticsRange() {
  clearAnalyticsRange();
  await loadAnalytics();
}

async function showPreviousAnalyticsMonth() {
  const target = analyticsMonthBoundsForAnchor(-1);
  setAnalyticsRange(target.from, target.to);
  await loadAnalytics();
}

async function showNextAnalyticsMonth() {
  const target = analyticsMonthBoundsForAnchor(1);
  setAnalyticsRange(target.from, target.to);
  await loadAnalytics();
}

async function loadAnalytics() {
  const data = await apiJson(buildAnalyticsUrl());
  state.analytics.lastPeriodFrom = String((data && data.period && data.period.from) || "");
  state.analytics.lastPeriodTo = String((data && data.period && data.period.to) || "");
  syncAnalyticsRangeInputs();
  updateAnalyticsRangeCaption((data && data.period) || null);

  animateAmount(document.getElementById("analyticsDayExpense"), data.totals.day.expenses);
  animateAmount(document.getElementById("analyticsWeekExpense"), data.totals.week.expenses);
  animateAmount(document.getElementById("analyticsMonthExpense"), data.totals.month.expenses);
  animateAmount(document.getElementById("analyticsAvgExpense"), data.avg_expense || 0);
  animateAmount(document.getElementById("analyticsMaxExpense"), data.max_expense || 0);
  animateAmount(document.getElementById("analyticsForecast"), data.forecast_next_month_expense || 0);

  const common = chartConfigBase();
  const distribution = data.distribution || [];

  if (!distribution.some((item) => item.category === state.analytics.selectedCategory)) {
    state.analytics.selectedCategory = (distribution[0] && distribution[0].category) || "";
  }

  renderChart("analyticsMonthly", "analyticsMonthly", {
    type: "line",
    data: {
      labels: (data.monthly_comparison || []).map((item) => item.month),
      datasets: [
        {
          label: t("chart.income"),
          data: (data.monthly_comparison || []).map((item) => item.incomes),
          borderColor: "#2bc06f",
          backgroundColor: "rgba(43, 192, 111, 0.2)",
          tension: 0.35,
        },
        {
          label: t("chart.expense"),
          data: (data.monthly_comparison || []).map((item) => item.expenses),
          borderColor: "#ff6b6b",
          backgroundColor: "rgba(255, 107, 107, 0.2)",
          tension: 0.35,
        },
      ],
    },
    options: common,
  });

  renderChart("analyticsDistribution", "analyticsDistribution", {
    type: "doughnut",
    data: {
      labels: distribution.map((item) => item.category),
      datasets: [
        {
          label: t("chart.sharePercent"),
          data: distribution.map((item) => item.percent),
          backgroundColor: palette(),
          borderWidth: 0,
        },
      ],
    },
    options: {
      ...common,
      scales: {},
      onClick: (_event, elements) => {
        if (!elements || elements.length === 0) return;
        const index = elements[0].index;
        const selected = distribution[index];
        if (!selected) return;
        state.analytics.selectedCategory = selected.category;
        renderAnalyticsSubcategoryChart(data.subcategory_distribution || []);
      },
    },
  });

  renderAnalyticsSubcategoryChart(data.subcategory_distribution || []);
  renderRecommendations(data.recommendations || []);
  // render budget overview block using analytics budget snapshot
  await renderBudgetOverview(data.budget || {}, data);
}

function buildSparklineSeriesFromDaily(amounts = []) {
  const series = [];
  let running = 0;
  for (const value of amounts) {
    running += Number(value || 0);
    series.push(Number(running.toFixed(2)));
  }
  return series.length ? series : [0];
}

function renderLimitSparkline(key, canvasId, series, status) {
  const danger = getComputedStyle(document.body).getPropertyValue("--danger").trim();
  const warning = getComputedStyle(document.body).getPropertyValue("--warning").trim();
  const accent = getComputedStyle(document.body).getPropertyValue("--accent").trim();
  const color = status && String(status).includes("exceeded") ? danger : status && String(status).includes("near") ? warning : accent;

  renderChart(key, canvasId, {
    type: "line",
    data: {
      labels: series.map((_, i) => String(i + 1)),
      datasets: [
        {
          data: series,
          borderColor: color || "#2dd4bf",
          backgroundColor: "rgba(45, 212, 191, 0.12)",
          tension: 0.35,
          borderWidth: 2,
          fill: true,
          pointRadius: 0,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

function buildBudgetRecommendations(snapshot, analyticsData) {
  const recs = [];
  const plan = snapshot.monthly_plan || {};
  const planned = Number(plan.planned_expense || 0);
  const used = Number(plan.used_percent || 0);
  const remaining = Number(plan.remaining || 0);
  const context = snapshot.projection_context || {};
  const daysRemaining = Number(context.days_remaining || 0);
  const warning = Number(snapshot.budget_warning_percent || 80);
  const danger = Number(snapshot.budget_danger_percent || 100);

  if (!planned) {
    recs.push(t("analytics.budgetNoPlan"));
    return recs;
  }

  if (used >= danger) {
    recs.push(`${t("analytics.budgetExceeded")}: ${used.toFixed(1)}%`);
  } else if (used >= warning) {
    recs.push(`${t("analytics.budgetNear")}: ${used.toFixed(1)}%`);
  }

  if (daysRemaining > 0 && plan.recommended_daily_spend != null) {
    recs.push(`${t("analytics.dailyBudget")}: ${formatAmount(plan.recommended_daily_spend)} ${t("analytics.perDay")}`);
  }

  if (!snapshot.category_limits || snapshot.category_limits.length === 0) {
    recs.push(t("analytics.noLimitsSet"));
  }

  if (remaining < 0) {
    recs.push(`${t("analytics.budgetDeficit")}: ${formatAmount(Math.abs(remaining))}`);
  }

  const monthly = ((analyticsData && analyticsData.monthly_comparison) || []).slice(-3);
  if (planned > 0 && monthly.length >= 2) {
    const avg = monthly.reduce((sum, item) => sum + Number(item.expenses || 0), 0) / monthly.length;
    if (avg > 0) {
      const diffPct = ((planned - avg) / avg) * 100;
      if (diffPct < -10) {
        recs.push(`${t("analytics.planBelowAverage")}: ${formatAmount(avg)}`);
      } else if (diffPct > 10) {
        recs.push(`${t("analytics.planAboveAverage")}: ${formatAmount(avg)}`);
      }
    }
  }

  const forecastNext = Number((analyticsData && analyticsData.forecast_next_month_expense) || 0);
  if (planned > 0 && forecastNext > 0) {
    const delta = forecastNext - planned;
    const deltaPct = (delta / planned) * 100;
    if (deltaPct > 8) {
      recs.push(`${t("analytics.forecastOverPlan")}: ${formatAmount(forecastNext)} (+${deltaPct.toFixed(0)}%)`);
    } else if (deltaPct < -8) {
      recs.push(`${t("analytics.forecastUnderPlan")}: ${formatAmount(forecastNext)} (${deltaPct.toFixed(0)}%)`);
    }
  }

  const distribution = (analyticsData && analyticsData.distribution) || [];
  if (distribution.length > 0) {
    const top = distribution[0];
    if (Number(top.percent || 0) >= 40) {
      recs.push(`${t("analytics.topCategoryHeavy")}: ${top.category} ${Number(top.percent || 0).toFixed(0)}%`);
    }
  }

  const forecastAlerts = snapshot.forecast_alerts || [];
  for (const item of forecastAlerts.slice(0, 2)) {
    const name = item.subcategory ? `${item.category} · ${item.subcategory}` : item.category;
    const pct = Number(item.forecast_used_percent || 0);
    recs.push(`${t("analytics.limitForecast")}: ${name} ${pct.toFixed(0)}%`);
  }

  const alerts = snapshot.alerts || [];
  for (const item of alerts.slice(0, 1)) {
    const name = item.subcategory ? `${item.category} · ${item.subcategory}` : item.category;
    const pct = Number(item.used_percent || 0);
    recs.push(`${t("analytics.limitAlert")}: ${name} ${pct.toFixed(0)}%`);
    if (item.recommended_daily_spend != null) {
      recs.push(`${t("analytics.dailyLimitHint")}: ${name} ${formatAmount(item.recommended_daily_spend)} ${t("analytics.perDay")}`);
    }
  }

  const wow = analyticsData && analyticsData.week_over_week;
  if (wow && Number.isFinite(wow.expenses_pct)) {
    if (wow.expenses_pct >= 20) {
      recs.push(`${t("analytics.weekSpike")}: +${wow.expenses_pct.toFixed(0)}%`);
    } else if (wow.expenses_pct <= -20) {
      recs.push(`${t("analytics.weekDrop")}: ${wow.expenses_pct.toFixed(0)}%`);
    }
  }

  const volatility = analyticsData && analyticsData.daily_volatility;
  if (volatility && Number.isFinite(volatility.index)) {
    if (volatility.index >= 0.6) {
      recs.push(`${t("analytics.volatilityHigh")}: ${(volatility.index * 100).toFixed(0)}%`);
    } else if (volatility.index >= 0.35) {
      recs.push(`${t("analytics.volatilityMedium")}: ${(volatility.index * 100).toFixed(0)}%`);
    }
  }

  return recs.slice(0, 6);
}

function renderBudgetRecommendations(items) {
  const container = document.getElementById("budgetRecommendations");
  if (!container) return;
  container.textContent = "";

  if (!items || items.length === 0) {
    container.textContent = t("messages.noRecommendations");
    return;
  }

  const title = document.createElement("div");
  title.className = "budget-reco-title";
  title.textContent = t("analytics.budgetRecommendations");
  container.appendChild(title);

  const ul = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  }
  container.appendChild(ul);
}

async function renderBudgetOverview(snapshot, analyticsData) {
  const monthly = snapshot.monthly_plan || {};
  const planned = Number(monthly.planned_expense || 0);
  const spent = Number(monthly.spent || 0);
  const remaining = Number(monthly.remaining || 0);
  const used = Number(monthly.used_percent || 0);

  animateAmount(document.getElementById("budgetPlanned"), planned);
  animateAmount(document.getElementById("budgetSpent"), spent);
  animateAmount(document.getElementById("budgetRemaining"), remaining);
  document.getElementById("budgetUsed").textContent = `${used.toFixed(1)}%`;

  const periodCaption = document.getElementById("budgetPeriodCaption");
  if (periodCaption) {
    const periodStart = String(snapshot.period_start || "");
    const periodEnd = String(snapshot.period_end || "");
    if (periodStart && periodEnd) {
      periodCaption.textContent = `${t("analytics.budgetPeriodLabel")}: ${formatAnalyticsDateLabel(periodStart)} — ${formatAnalyticsDateLabel(periodEnd)}`;
    }
  }

  const plannedData = [spent, Math.max(0, planned - spent)];
  renderChart("budgetPlan", "budgetPlanChart", {
    type: "doughnut",
    data: {
      labels: [t("chart.spent"), t("chart.remaining")],
      datasets: [
        {
          data: plannedData,
          backgroundColor: ["#ff6b6b", "#2bc06f"],
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      devicePixelRatio: window.devicePixelRatio || 1,
      cutout: "62%",
      radius: "80%",
      layout: {
        padding: { top: 4, right: 8, bottom: 4, left: 8 },
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          callbacks: {
            label: (context) => {
              const label = String(context.label || "");
              const raw = Number(context.raw || 0);
              return `${label}: ${formatAmount(raw)}`;
            },
          },
        },
      },
      scales: {},
    },
  });

  const limits = snapshot.category_limits || [];
  const limitsContainer = document.getElementById("limitsProgress");
  limitsContainer.textContent = "";

  if (limits.length === 0) {
    limitsContainer.textContent = t("messages.noCategoryLimits");
  } else {
    const periodStart = snapshot.period_start;
    const periodEnd = snapshot.period_end;
    const warningThreshold = Math.min(100, Number(snapshot.budget_warning_percent || 80));
    const dangerThreshold = Math.min(100, Number(snapshot.budget_danger_percent || 100));
    const keys = limits.slice(0, 8).map((item) => ({
      category: item.canonical_category || item.category,
      subcategory: item.canonical_subcategory || item.subcategory || null,
    }));

    let dailySeries = [];
    const now = Date.now();
    const cache = state.budgetSparklines;
    const sameKeys = JSON.stringify(cache.keys || []) === JSON.stringify(keys);
    if (sameKeys && cache.expiresAt > now) {
      dailySeries = cache.items || [];
    } else if (periodStart && periodEnd) {
      try {
        const seriesPayload = await apiJson("/api/webapp/budget/limit-series", {
          method: "POST",
          body: JSON.stringify({ period_start: periodStart, period_end: periodEnd, keys }),
        });
        dailySeries = seriesPayload.items || [];
        state.budgetSparklines = {
          keys,
          items: dailySeries,
          expiresAt: now + 60 * 1000,
        };
      } catch (err) {
        console.error(err);
      }
    }

    for (const [idx, item] of limits.slice(0, 8).entries()) {
      const usedPct = Number(item.used_percent || 0);
      const row = document.createElement("div");
      row.className = "limit-row";
      row.dataset.category = item.category || "";
      row.dataset.subcategory = item.subcategory || "";

      row.addEventListener("click", async () => {
        const drill = App.actions && App.actions.dashboard && App.actions.dashboard.applyCategoryDrilldown;
        if (typeof drill !== "function") return;
        await drill(item.category, item.subcategory || "");
      });

      const info = document.createElement("div");
      const header = document.createElement("div");
      header.className = "limit-header";

      const label = document.createElement("div");
      label.className = "limit-label";
      const subcategoryLabel = item.subcategory || item.canonical_subcategory || "";
      label.textContent = subcategoryLabel ? `${item.category} · ${subcategoryLabel}` : item.category;
      header.appendChild(label);
      header.appendChild(createStatusBadge(item.status || "normal"));

      const barWrap = document.createElement("div");
      barWrap.className = "limit-bar";
      const bar = document.createElement("span");
      bar.style.width = `${Math.min(100, usedPct)}%`;
      if (usedPct > 100) {
        bar.style.background = "var(--danger)";
      } else if (usedPct >= 80) {
        bar.style.background = "var(--warning)";
      } else {
        bar.style.background = "var(--ok)";
      }
      barWrap.appendChild(bar);

      const warnMarker = document.createElement("span");
      warnMarker.className = "limit-marker warn";
      warnMarker.style.left = `${warningThreshold}%`;
      warnMarker.title = `${t("analytics.budgetWarning") || "Warning"} ${warningThreshold}%`;
      barWrap.appendChild(warnMarker);

      const dangerMarker = document.createElement("span");
      dangerMarker.className = "limit-marker danger";
      dangerMarker.style.left = `${dangerThreshold}%`;
      dangerMarker.title = `${t("analytics.budgetDanger") || "Danger"} ${dangerThreshold}%`;
      barWrap.appendChild(dangerMarker);

      const meta = document.createElement("div");
      meta.className = "limit-meta";
      meta.textContent = `${formatAmount(item.spent || 0)} / ${formatAmount(item.limit || 0)} (${usedPct.toFixed(1)}%)`;

      const hint = document.createElement("div");
      hint.className = "limit-hint";
      if (item.forecast) {
        hint.textContent = `${t("table.forecast")}: ${formatAmount(item.forecast || 0)} (${Number(item.forecast_used_percent || 0).toFixed(1)}%)`;
      }

      info.appendChild(header);
      info.appendChild(barWrap);
      info.appendChild(meta);
      if (hint.textContent) {
        info.appendChild(hint);
      }

      const sparkWrap = document.createElement("div");
      const sparkId = `limitSpark_${idx}`;
      const canvas = document.createElement("canvas");
      canvas.id = sparkId;
      canvas.className = "limit-spark";
      sparkWrap.appendChild(canvas);

      row.appendChild(info);
      row.appendChild(sparkWrap);
      limitsContainer.appendChild(row);

      const match = dailySeries.find((entry) => {
        const entryCat = String(entry.canonical_category || entry.category || "").trim();
        const entrySub = String(entry.canonical_subcategory || entry.subcategory || "");
        const itemCat = String(item.canonical_category || item.category || "").trim();
        const itemSub = String(item.canonical_subcategory || item.subcategory || "");
        return entryCat === itemCat && entrySub === itemSub;
      });
      const amounts = match ? match.amounts || [] : [];
      const series = buildSparklineSeriesFromDaily(amounts);
      renderLimitSparkline(`limitSpark_${idx}`, sparkId, series, item.forecast_status || item.status);
    }
  }

  const recs = buildBudgetRecommendations(snapshot, analyticsData);
  renderBudgetRecommendations(recs);
}

App.actions = App.actions || {};
App.actions.budget = Object.assign(App.actions.budget || {}, {
  loadBudget,
  loadRecurring,
  createRecurring,
  syncRecurringIncomeMode,
  handleRecurringTableClick,
  applyAnalyticsRange,
  resetAnalyticsRange,
  showPreviousAnalyticsMonth,
  showNextAnalyticsMonth,
  clearAnalyticsRange,
  loadAnalytics,
});
App.actions.settings = Object.assign(App.actions.settings || {}, {
  saveSettings,
});


