const STORAGE_KEYS = {
  period: "finance_webapp_period",
  filters: "finance_webapp_filters",
};

const state = {
  tg: null,
  initData: "",
  period: "30d",
  bootstrap: null,
  settings: null,
  charts: {},
  records: {
    offset: 0,
    limit: 25,
    hasMore: false,
    map: new Map(),
  },
  filters: {
    date_from: "",
    date_to: "",
    type: "",
    category: "",
    min_amount: "",
    max_amount: "",
    query: "",
  },
  budgetLimits: [],
};

let queryDebounceTimer = null;

function showToast(text, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = text;
  toast.style.borderColor = isError ? "rgba(255, 107, 107, 0.5)" : "rgba(45, 212, 191, 0.45)";
  toast.classList.add("show");
  window.setTimeout(() => {
    toast.classList.remove("show");
  }, 2300);
}

function parseApiError(payload) {
  if (!payload) return "Request failed";
  if (typeof payload === "string") return payload;
  if (payload.detail) {
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg || String(item)).join("; ");
  }
  return "Request failed";
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (state.initData) {
    headers.set("X-Telegram-Init-Data", state.initData);
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    throw new Error(parseApiError(payload));
  }

  return response;
}

async function apiJson(path, options = {}) {
  const response = await request(path, options);
  return response.json();
}

async function apiBlob(path, options = {}) {
  const response = await request(path, options);
  const blob = await response.blob();
  return { blob, response };
}

function formatAmount(value) {
  const currency = state.settings?.currency || "UAH";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(Number(value || 0));
  } catch (error) {
    return `${Number(value || 0).toFixed(2)} ${currency}`;
  }
}

function animateAmount(element, targetValue) {
  if (!element) return;
  const duration = 380;
  const start = performance.now();
  const from = Number(element.dataset.value || 0);
  const to = Number(targetValue || 0);

  const frame = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = from + (to - from) * eased;
    element.textContent = formatAmount(current);
    if (progress < 1) {
      requestAnimationFrame(frame);
    } else {
      element.dataset.value = String(to);
      element.textContent = formatAmount(to);
    }
  };

  requestAnimationFrame(frame);
}

function setActivePage(page) {
  document.querySelectorAll(".bottom-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === page);
  });

  document.querySelectorAll(".page").forEach((section) => {
    section.classList.toggle("active", section.id === `page-${page}`);
  });
}

function saveLocalState() {
  localStorage.setItem(STORAGE_KEYS.period, state.period);
  localStorage.setItem(STORAGE_KEYS.filters, JSON.stringify(state.filters));
}

function restoreLocalState() {
  const savedPeriod = localStorage.getItem(STORAGE_KEYS.period);
  if (savedPeriod) {
    state.period = savedPeriod;
  }

  const savedFilters = localStorage.getItem(STORAGE_KEYS.filters);
  if (savedFilters) {
    try {
      const parsed = JSON.parse(savedFilters);
      state.filters = {
        ...state.filters,
        ...parsed,
      };
    } catch (error) {
      state.filters = { ...state.filters };
    }
  }
}

function applyFilterFormValues() {
  document.getElementById("filterDateFrom").value = state.filters.date_from || "";
  document.getElementById("filterDateTo").value = state.filters.date_to || "";
  document.getElementById("filterType").value = state.filters.type || "";
  document.getElementById("filterCategory").value = state.filters.category || "";
  document.getElementById("filterMin").value = state.filters.min_amount || "";
  document.getElementById("filterMax").value = state.filters.max_amount || "";
  document.getElementById("filterQuery").value = state.filters.query || "";
}

function readFilterFormValues() {
  state.filters = {
    date_from: document.getElementById("filterDateFrom").value,
    date_to: document.getElementById("filterDateTo").value,
    type: document.getElementById("filterType").value,
    category: document.getElementById("filterCategory").value,
    min_amount: document.getElementById("filterMin").value,
    max_amount: document.getElementById("filterMax").value,
    query: document.getElementById("filterQuery").value.trim(),
  };
}

function updatePeriodButtons() {
  document.querySelectorAll("#periodSwitch button").forEach((button) => {
    button.classList.toggle("active", button.dataset.period === state.period);
  });
}

function buildFilterQueryParams() {
  const params = new URLSearchParams();
  if (state.filters.date_from) params.set("date_from", state.filters.date_from);
  if (state.filters.date_to) params.set("date_to", state.filters.date_to);
  if (state.filters.type) params.set("type", state.filters.type);
  if (state.filters.category) params.append("categories", state.filters.category);
  if (state.filters.min_amount) params.set("min_amount", state.filters.min_amount);
  if (state.filters.max_amount) params.set("max_amount", state.filters.max_amount);
  if (state.filters.query) params.set("query", state.filters.query);
  return params;
}

function populateCategorySelects(categories = []) {
  const filterSelect = document.getElementById("filterCategory");
  const limitSelect = document.getElementById("limitCategory");

  const previousFilter = filterSelect.value;
  const previousLimit = limitSelect.value;

  filterSelect.innerHTML = `<option value="">Category</option>`;
  limitSelect.innerHTML = `<option value="">Choose Category</option>`;

  for (const category of categories) {
    const optionA = document.createElement("option");
    optionA.value = category;
    optionA.textContent = category;
    filterSelect.appendChild(optionA);

    const optionB = document.createElement("option");
    optionB.value = category;
    optionB.textContent = category;
    limitSelect.appendChild(optionB);
  }

  filterSelect.value = previousFilter;
  limitSelect.value = previousLimit;
}

function chartConfigBase() {
  const textColor = getComputedStyle(document.body).getPropertyValue("--text").trim();
  const mutedColor = getComputedStyle(document.body).getPropertyValue("--muted").trim();

  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: textColor,
        },
      },
      tooltip: {
        backgroundColor: "rgba(6, 22, 30, 0.92)",
        titleColor: "#e7f6f5",
        bodyColor: "#cce6e2",
      },
    },
    scales: {
      x: {
        ticks: { color: mutedColor },
        grid: { color: "rgba(255,255,255,0.05)" },
      },
      y: {
        ticks: { color: mutedColor },
        grid: { color: "rgba(255,255,255,0.05)" },
      },
    },
  };
}

function renderChart(key, canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  if (state.charts[key]) {
    state.charts[key].destroy();
  }

  state.charts[key] = new Chart(canvas, config);
}

function renderRecentOperations(items) {
  const container = document.getElementById("recentOperations");
  container.innerHTML = "";

  if (!items || items.length === 0) {
    container.innerHTML = `<p class="status-text">No operations yet for selected period.</p>`;
    return;
  }

  for (const item of items.slice(0, 8)) {
    const wrapper = document.createElement("div");
    wrapper.className = "recent-item";
    wrapper.innerHTML = `
      <div>
        <strong>${item.category}${item.subcategory ? ` (${item.subcategory})` : ""}</strong>
        <small>${item.happened_on} • ${item.type}</small>
      </div>
      <strong>${formatAmount(item.amount)}</strong>
    `;
    container.appendChild(wrapper);
  }
}

function renderDashboardCharts(data) {
  const categories = data.categories || [];
  const trend = data.trend || [];

  const common = chartConfigBase();

  renderChart("categoryPie", "categoryPie", {
    type: "doughnut",
    data: {
      labels: categories.map((item) => item.category),
      datasets: [
        {
          data: categories.map((item) => item.amount),
          backgroundColor: [
            "#2dd4bf",
            "#56ccf2",
            "#f4b942",
            "#60d394",
            "#ff6b6b",
            "#5ea1ff",
            "#ffc36e",
            "#7fe3ce",
          ],
          borderWidth: 0,
        },
      ],
    },
    options: {
      ...common,
      scales: {},
    },
  });

  renderChart("trendLine", "trendLine", {
    type: "line",
    data: {
      labels: trend.map((row) => row.date),
      datasets: [
        {
          label: "Income",
          data: trend.map((row) => row.income),
          borderColor: "#2bc06f",
          backgroundColor: "rgba(43, 192, 111, 0.14)",
          tension: 0.35,
          fill: true,
        },
        {
          label: "Expense",
          data: trend.map((row) => row.expense),
          borderColor: "#ff7f7f",
          backgroundColor: "rgba(255, 107, 107, 0.12)",
          tension: 0.35,
          fill: true,
        },
      ],
    },
    options: common,
  });

  renderChart("categoryBar", "categoryBar", {
    type: "bar",
    data: {
      labels: categories.map((item) => item.category),
      datasets: [
        {
          label: "Expenses",
          data: categories.map((item) => item.amount),
          backgroundColor: "rgba(86, 204, 242, 0.72)",
          borderRadius: 8,
        },
      ],
    },
    options: common,
  });
}

function renderHeatmap(heatmapData) {
  const grid = document.getElementById("analyticsHeatmap");
  grid.innerHTML = "";

  const values = (heatmapData || []).map((item) => Number(item.total || 0));
  const max = Math.max(...values, 1);

  if (!heatmapData || heatmapData.length === 0) {
    grid.innerHTML = `<p class="status-text">No heatmap data for selected period.</p>`;
    return;
  }

  for (const item of heatmapData) {
    const cell = document.createElement("div");
    const ratio = Number(item.total || 0) / max;
    let level = 0;
    if (ratio > 0.66) level = 3;
    else if (ratio > 0.33) level = 2;
    else if (ratio > 0.12) level = 1;

    cell.className = `heat-cell level-${level}`;
    cell.title = `${item.date}: ${formatAmount(item.total)}`;
    grid.appendChild(cell);
  }
}

function renderRecommendations(items) {
  const list = document.getElementById("recommendationsList");
  list.innerHTML = "";

  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No recommendations right now.";
    list.appendChild(li);
    return;
  }

  for (const tip of items) {
    const li = document.createElement("li");
    li.textContent = tip;
    list.appendChild(li);
  }
}

function applyTheme(theme) {
  document.body.classList.toggle("theme-light", theme === "light");
  document.body.classList.toggle("theme-dark", theme !== "light");
}

function applyHiddenBlocks(hiddenBlocks = []) {
  const hidden = new Set(hiddenBlocks);
  document.querySelectorAll(".dash-block").forEach((node) => {
    const key = node.dataset.block;
    node.style.display = hidden.has(key) ? "none" : "";
  });
}

async function loadBootstrap() {
  const data = await apiJson("/api/webapp/bootstrap");
  state.bootstrap = data;
  state.settings = data.settings;

  populateCategorySelects(data.categories || []);
  applyTheme(state.settings.theme || "dark");
  applyHiddenBlocks(state.settings.hidden_blocks || []);
}

async function loadDashboard() {
  const data = await apiJson(`/api/webapp/dashboard?period=${encodeURIComponent(state.period)}`);

  animateAmount(document.getElementById("cardBalance"), data.totals.balance);
  animateAmount(document.getElementById("cardIncome"), data.totals.incomes);
  animateAmount(document.getElementById("cardExpense"), data.totals.expenses);
  animateAmount(document.getElementById("cardRemaining"), data.totals.remaining);

  renderRecentOperations(data.recent_operations || []);
  renderDashboardCharts(data);
  renderHeatmap(data.heatmap || []);
}

function mapStatusToBadge(status) {
  if (status === "exceeded") return "<span class=\"badge badge-exceeded\">Exceeded</span>";
  if (status === "near_limit") return "<span class=\"badge badge-near\">Near Limit</span>";
  return "<span class=\"badge badge-normal\">Normal</span>";
}

function renderLimitsTable() {
  const body = document.getElementById("limitsBody");
  body.innerHTML = "";

  if (state.budgetLimits.length === 0) {
    body.innerHTML = `<tr><td colspan="6">No category limits yet.</td></tr>`;
    return;
  }

  for (const item of state.budgetLimits) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.category}</td>
      <td>${formatAmount(item.limit)}</td>
      <td>${formatAmount(item.spent || 0)}</td>
      <td>${formatAmount(item.remaining || 0)}</td>
      <td>${mapStatusToBadge(item.status || "normal")}</td>
      <td><button type="button" data-remove-category="${item.category}">Remove</button></td>
    `;
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

  const monthly = data.monthly_plan || {};
  document.getElementById("budgetExpense").value = monthly.planned_expense ?? "";
  document.getElementById("budgetIncome").value = monthly.planned_income ?? "";

  const statusText = document.getElementById("budgetPlanStatus");
  statusText.textContent = `Spent: ${formatAmount(monthly.spent || 0)} | Remaining: ${formatAmount(
    monthly.remaining || 0
  )} | Used: ${(monthly.used_percent || 0).toFixed(2)}%`;

  state.budgetLimits = (data.category_limits || []).map((item) => ({
    category: item.category,
    limit: Number(item.limit || 0),
    spent: Number(item.spent || 0),
    remaining: Number(item.remaining || 0),
    status: item.status || "normal",
  }));

  renderLimitsTable();
}

function fillSettingsForm(settings) {
  document.getElementById("settingTheme").value = settings.theme || "dark";
  document.getElementById("settingCurrency").value = settings.currency || "UAH";
  document.getElementById("settingLanguage").value = settings.interface_language || "uk";
  document.getElementById("settingWeekStart").value = settings.week_starts_on || "monday";
  document.getElementById("settingNotifications").checked = Boolean(settings.notifications_enabled);
  document.getElementById("settingHiddenBlocks").value = (settings.hidden_blocks || []).join(",");
  document.getElementById("settingPinnedFilters").value = (settings.pinned_filters || []).join(",");
  document.getElementById("settingFavoriteCategories").value = (settings.favorite_categories || []).join(",");
}

async function loadSettings() {
  const data = await apiJson("/api/webapp/settings");
  state.settings = data;
  fillSettingsForm(data);
  applyTheme(data.theme || "dark");
  applyHiddenBlocks(data.hidden_blocks || []);
}

function parseCsvField(raw) {
  return raw
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function loadCategoriesByLanguage(language) {
  const payload = await apiJson(`/api/webapp/categories?language=${encodeURIComponent(language)}`);
  populateCategorySelects((payload.items || []).map((item) => item.category));
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    theme: document.getElementById("settingTheme").value,
    currency: document.getElementById("settingCurrency").value.trim() || "UAH",
    interface_language: document.getElementById("settingLanguage").value,
    week_starts_on: document.getElementById("settingWeekStart").value,
    notifications_enabled: document.getElementById("settingNotifications").checked,
    hidden_blocks: parseCsvField(document.getElementById("settingHiddenBlocks").value),
    pinned_filters: parseCsvField(document.getElementById("settingPinnedFilters").value),
    favorite_categories: parseCsvField(document.getElementById("settingFavoriteCategories").value),
  };

  const saved = await apiJson("/api/webapp/settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.settings = saved;
  applyTheme(saved.theme || "dark");
  applyHiddenBlocks(saved.hidden_blocks || []);
  await loadCategoriesByLanguage(saved.interface_language || "uk");
  showToast("Settings saved");
}

async function loadAnalytics() {
  const data = await apiJson(`/api/webapp/analytics?period=${encodeURIComponent(state.period)}`);

  animateAmount(document.getElementById("analyticsDayExpense"), data.totals.day.expenses);
  animateAmount(document.getElementById("analyticsWeekExpense"), data.totals.week.expenses);
  animateAmount(document.getElementById("analyticsMonthExpense"), data.totals.month.expenses);
  animateAmount(document.getElementById("analyticsAvgExpense"), data.avg_expense || 0);
  animateAmount(document.getElementById("analyticsMaxExpense"), data.max_expense || 0);
  animateAmount(document.getElementById("analyticsForecast"), data.forecast_next_month_expense || 0);

  const common = chartConfigBase();

  renderChart("analyticsMonthly", "analyticsMonthly", {
    type: "line",
    data: {
      labels: data.monthly_comparison.map((item) => item.month),
      datasets: [
        {
          label: "Income",
          data: data.monthly_comparison.map((item) => item.incomes),
          borderColor: "#2bc06f",
          backgroundColor: "rgba(43, 192, 111, 0.2)",
          tension: 0.35,
        },
        {
          label: "Expense",
          data: data.monthly_comparison.map((item) => item.expenses),
          borderColor: "#ff6b6b",
          backgroundColor: "rgba(255, 107, 107, 0.2)",
          tension: 0.35,
        },
      ],
    },
    options: common,
  });

  renderChart("analyticsDistribution", "analyticsDistribution", {
    type: "bar",
    data: {
      labels: data.distribution.map((item) => item.category),
      datasets: [
        {
          label: "Share %",
          data: data.distribution.map((item) => item.percent),
          backgroundColor: "rgba(45, 212, 191, 0.72)",
          borderRadius: 8,
        },
      ],
    },
    options: common,
  });

  renderRecommendations(data.recommendations || []);
}

function appendRecordRows(items) {
  const body = document.getElementById("recordsBody");

  if (items.length === 0 && state.records.offset === 0) {
    body.innerHTML = `<tr><td colspan="7">No records found for current filters.</td></tr>`;
    return;
  }

  for (const record of items) {
    state.records.map.set(record.id, record);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${record.happened_on}</td>
      <td>${record.description || "-"}</td>
      <td>${record.category}${record.subcategory ? ` (${record.subcategory})` : ""}</td>
      <td>${record.type}</td>
      <td>${formatAmount(record.amount)}</td>
      <td>manual</td>
      <td>
        <div class="row-actions">
          <button type="button" data-edit-id="${record.id}">Edit</button>
          <button type="button" data-delete-id="${record.id}">Delete</button>
        </div>
      </td>
    `;
    body.appendChild(row);
  }
}

async function loadRecords(reset = false) {
  if (reset) {
    state.records.offset = 0;
    state.records.map.clear();
    document.getElementById("recordsBody").innerHTML = "";
  }

  const params = buildFilterQueryParams();
  params.set("limit", String(state.records.limit));
  params.set("offset", String(state.records.offset));

  const data = await apiJson(`/api/webapp/records?${params.toString()}`);
  appendRecordRows(data.items || []);

  state.records.offset += (data.items || []).length;
  state.records.hasMore = Boolean(data.paging?.has_more);

  const moreButton = document.getElementById("loadMoreRecordsBtn");
  moreButton.style.display = state.records.hasMore ? "inline-block" : "none";
}

async function handleRecordTableClick(event) {
  const editId = event.target.dataset.editId;
  const deleteId = event.target.dataset.deleteId;

  if (editId) {
    const id = Number(editId);
    const record = state.records.map.get(id);
    if (!record) return;

    const category = prompt("Category", record.category);
    if (category === null) return;

    const amountInput = prompt("Amount", String(record.amount));
    if (amountInput === null) return;

    const typeInput = prompt("Type (income/expense)", record.type);
    if (typeInput === null) return;

    const dateInput = prompt("Date YYYY-MM-DD", record.happened_on);
    if (dateInput === null) return;

    const descriptionInput = prompt("Description", record.description || "");
    if (descriptionInput === null) return;

    const amount = Number(amountInput);
    if (!Number.isFinite(amount) || amount <= 0) {
      showToast("Amount must be positive", true);
      return;
    }

    if (!["income", "expense"].includes(typeInput)) {
      showToast("Type must be income or expense", true);
      return;
    }

    await apiJson(`/api/webapp/records/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        category: category.trim(),
        amount,
        type: typeInput,
        happened_on: dateInput,
        description: descriptionInput,
      }),
    });

    showToast("Record updated");
    await refreshAllData();
    return;
  }

  if (deleteId) {
    const id = Number(deleteId);
    const shouldDelete = confirm("Delete this record?");
    if (!shouldDelete) return;

    await apiJson(`/api/webapp/records/${id}`, {
      method: "DELETE",
    });

    showToast("Record deleted");
    await refreshAllData();
  }
}

async function refreshAllData() {
  await Promise.all([loadDashboard(), loadRecords(true), loadAnalytics(), loadBudget()]);
}

async function submitFilters(event) {
  event.preventDefault();
  readFilterFormValues();
  saveLocalState();
  await loadRecords(true);
}

async function resetFilters() {
  state.filters = {
    date_from: "",
    date_to: "",
    type: "",
    category: "",
    min_amount: "",
    max_amount: "",
    query: "",
  };
  applyFilterFormValues();
  saveLocalState();
  await loadRecords(true);
}

async function addLimit() {
  const category = document.getElementById("limitCategory").value;
  const amountValue = Number(document.getElementById("limitAmount").value);

  if (!category) {
    showToast("Select category first", true);
    return;
  }
  if (!Number.isFinite(amountValue) || amountValue < 0) {
    showToast("Limit amount must be non-negative", true);
    return;
  }

  const existing = state.budgetLimits.find((item) => item.category === category);
  if (existing) {
    existing.limit = amountValue;
  } else {
    state.budgetLimits.push({
      category,
      limit: amountValue,
      spent: 0,
      remaining: amountValue,
      status: "normal",
    });
  }

  document.getElementById("limitAmount").value = "";
  renderLimitsTable();
}

async function saveLimits() {
  const period_start = document.getElementById("budgetStart").value;
  const period_end = document.getElementById("budgetEnd").value;

  if (!period_start || !period_end) {
    showToast("Set budget period first", true);
    return;
  }

  const payload = {
    period_start,
    period_end,
    limits: state.budgetLimits.map((item) => ({
      category: item.category,
      limit_amount: Number(item.limit || 0),
    })),
  };

  const snapshot = await apiJson("/api/webapp/budget/category-limits", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  state.budgetLimits = (snapshot.category_limits || []).map((item) => ({
    category: item.category,
    limit: Number(item.limit || 0),
    spent: Number(item.spent || 0),
    remaining: Number(item.remaining || 0),
    status: item.status || "normal",
  }));

  renderLimitsTable();
  showToast("Category limits saved");
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
    showToast("Date period is required", true);
    return;
  }

  await apiJson("/api/webapp/budget/month", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

  showToast("Budget plan saved");
  await Promise.all([loadBudget(), loadDashboard(), loadAnalytics()]);
}

async function handleLimitTableClick(event) {
  const category = event.target.dataset.removeCategory;
  if (!category) return;
  state.budgetLimits = state.budgetLimits.filter((item) => item.category !== category);
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

function bindEvents() {
  document.querySelectorAll(".bottom-nav button").forEach((button) => {
    button.addEventListener("click", () => setActivePage(button.dataset.page));
  });

  document.querySelectorAll("#periodSwitch button").forEach((button) => {
    button.addEventListener("click", async () => {
      state.period = button.dataset.period;
      updatePeriodButtons();
      saveLocalState();
      await Promise.all([loadDashboard(), loadAnalytics()]);
    });
  });

  document.getElementById("refreshAllBtn").addEventListener("click", async () => {
    await refreshAllData();
    showToast("Data refreshed");
  });

  document.getElementById("filtersForm").addEventListener("submit", submitFilters);
  document.getElementById("resetFiltersBtn").addEventListener("click", resetFilters);
  document.getElementById("recordsBody").addEventListener("click", handleRecordTableClick);
  document.getElementById("loadMoreRecordsBtn").addEventListener("click", () => loadRecords(false));

  document.getElementById("filterQuery").addEventListener("input", async () => {
    clearTimeout(queryDebounceTimer);
    queryDebounceTimer = setTimeout(async () => {
      readFilterFormValues();
      saveLocalState();
      await loadRecords(true);
    }, 320);
  });

  document.getElementById("budgetPlanForm").addEventListener("submit", saveBudgetPlan);
  document.getElementById("addLimitBtn").addEventListener("click", addLimit);
  document.getElementById("saveLimitsBtn").addEventListener("click", saveLimits);
  document.getElementById("limitsBody").addEventListener("click", handleLimitTableClick);

  document.getElementById("settingsForm").addEventListener("submit", async (event) => {
    await saveSettings(event);
    await Promise.all([loadDashboard(), loadAnalytics(), loadBudget()]);
  });

  document.getElementById("exportCsvBtn").addEventListener("click", async () => {
    await downloadReport("csv");
  });

  document.getElementById("exportPdfBtn").addEventListener("click", async () => {
    await downloadReport("pdf");
  });
}

function initTelegram() {
  const tg = window.Telegram?.WebApp;
  if (!tg) return;

  state.tg = tg;
  state.initData = tg.initData || "";
  tg.ready();
  tg.expand();
}

async function bootstrapApp() {
  try {
    initTelegram();
    restoreLocalState();
    bindEvents();
    updatePeriodButtons();
    applyFilterFormValues();

    await loadBootstrap();
    await Promise.all([loadDashboard(), loadRecords(true), loadAnalytics(), loadBudget(), loadSettings()]);
    showToast("Web App is ready");
  } catch (error) {
    showToast(error.message || "Failed to initialize app", true);
  }
}

document.addEventListener("DOMContentLoaded", bootstrapApp);
