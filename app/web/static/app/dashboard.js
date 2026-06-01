var App = window.App || (window.App = {});

function formatAmount(value) {
  const currency = (state.settings && state.settings.currency) || "UAH";
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
  const periodSwitch = document.getElementById("periodSwitch");
  if (periodSwitch) {
    const hidePeriodSwitch = page === "operations" || page === "budget" || page === "settings";
    periodSwitch.style.display = hidePeriodSwitch ? "none" : "";
  }

  document.querySelectorAll(".bottom-nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === page);
  });

  document.querySelectorAll(".page").forEach((section) => {
    section.classList.toggle("active", section.id === `page-${page}`);
  });
}

function normalizePeriod(value) {
  const period = String(value || "").toLowerCase();
  if (period === "week" || period === "7d") return "week";
  if (period === "month" || period === "30d") return "month";
  if (period === "6m" || period === "halfyear") return "6m";
  if (period === "year") return "year";
  return "month";
}

function scopedStorageKey(baseKey) {
  const telegramId = state.bootstrap && state.bootstrap.user && state.bootstrap.user.telegram_id;
  if (!telegramId) return `${baseKey}_anonymous`;
  return `${baseKey}_${telegramId}`;
}

const DESKTOP_RESIZE_DEBOUNCE_MS = 260;
const DESKTOP_REMOTE_SYNC_DEBOUNCE_MS = 700;
const iosDateMirrors = new Map();
let desktopResizeTimer = null;
let desktopRemoteSyncTimer = null;
let desktopPersistenceBound = false;
let desktopRemoteSyncInFlight = false;
let desktopPendingRemoteSize = null;
let desktopLastRemoteSnapshot = "";
let desktopWindowDirty = false;
let desktopSessionBaseline = null;
let desktopTelegramViewportBound = false;
let desktopPersistenceReadyAt = 0;
let desktopResizeSignal = false;
let desktopRestoreTimerIds = [];

function isDesktopDevice() {
  const ua = navigator.userAgent || "";
  const isMobileUa = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Windows Phone|Mobile/i.test(ua);
  return !isMobileUa;
}

function isIOSDevice() {
  const ua = navigator.userAgent || "";
  const platform = navigator.platform || "";
  const touchPoints = Number(navigator.maxTouchPoints || 0);
  return /iPhone|iPad|iPod/i.test(ua) || (platform === "MacIntel" && touchPoints > 1);
}

function formatDateForMirror(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";

  const [year, month, day] = raw.split("-").map((part) => Number(part));
  if (!year || !month || !day) {
    return raw;
  }

  const dateValue = new Date(year, month - 1, day);
  if (!Number.isFinite(dateValue.getTime())) {
    return raw;
  }

  try {
    return new Intl.DateTimeFormat(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(dateValue);
  } catch (_error) {
    return raw;
  }
}

function syncIOSDateMirror(inputElement) {
  const mirror = iosDateMirrors.get(inputElement);
  if (!mirror) return;

  const text = formatDateForMirror(inputElement.value);
  mirror.textContent = text || " ";
  mirror.classList.toggle("is-empty", !text);
}

function ensureIOSDateMirrors() {
  if (!isIOSDevice()) return;

  const dateInputs = document.querySelectorAll('input[type="date"]');
  for (const inputElement of dateInputs) {
    if (!(inputElement instanceof HTMLInputElement)) continue;

    if (inputElement.dataset.iosMirrorReady === "1") {
      syncIOSDateMirror(inputElement);
      continue;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "ios-date-field";

    const parent = inputElement.parentNode;
    if (!parent) continue;
    parent.insertBefore(wrapper, inputElement);
    wrapper.appendChild(inputElement);

    inputElement.classList.add("ios-date-native");

    const display = document.createElement("span");
    display.className = "ios-date-display";
    wrapper.appendChild(display);

    const update = () => syncIOSDateMirror(inputElement);
    inputElement.addEventListener("input", update);
    inputElement.addEventListener("change", update);
    inputElement.addEventListener("blur", update);

    inputElement.dataset.iosMirrorReady = "1";
    iosDateMirrors.set(inputElement, display);
    update();
  }
}

function refreshIOSDateMirrors() {
  if (!isIOSDevice()) return;
  ensureIOSDateMirrors();
  for (const inputElement of iosDateMirrors.keys()) {
    syncIOSDateMirror(inputElement);
  }
}

function syncDesktopModeClass() {
  if (!document.body) return;
  document.body.classList.toggle("desktop-app", isDesktopDevice());
}

function getTelegramViewportHeight() {
  const webApp = App.state && App.state.tg;
  if (!webApp) return 0;

  const stable = Number(webApp.viewportStableHeight || 0);
  if (Number.isFinite(stable) && stable > 0) {
    return stable;
  }

  const dynamic = Number(webApp.viewportHeight || 0);
  if (Number.isFinite(dynamic) && dynamic > 0) {
    return dynamic;
  }

  return 0;
}

function getCurrentDesktopWindowSize() {
  const viewportWidth = Number(window.innerWidth || (document.documentElement && document.documentElement.clientWidth) || 1400);
  const viewportHeight = Number(getTelegramViewportHeight() || window.innerHeight || (document.documentElement && document.documentElement.clientHeight) || 800);

  return {
    width: viewportWidth,
    height: viewportHeight,
  };
}

function rememberDesktopSessionBaseline() {
  const current = getCurrentDesktopWindowSize();
  desktopSessionBaseline = clampDesktopSize(current.width, current.height);
}

function deferDesktopPersistence(ms = 900) {
  desktopPersistenceReadyAt = Date.now() + ms;
}

function isDesktopPersistenceReady() {
  return Date.now() >= desktopPersistenceReadyAt;
}

function noteDesktopResizeSignal() {
  if (!isDesktopPersistenceReady()) {
    return false;
  }
  desktopResizeSignal = true;
  desktopWindowDirty = true;
  return true;
}

function markDesktopWindowDirtyIfChanged(size) {
  if (!desktopSessionBaseline) {
    desktopWindowDirty = true;
    return;
  }

  const widthDelta = Math.abs(size.width - desktopSessionBaseline.width);
  const heightDelta = Math.abs(size.height - desktopSessionBaseline.height);
  if (widthDelta >= 8 || heightDelta >= 8) {
    desktopWindowDirty = true;
  }
}

function clampDesktopSize(width, height) {
  const clampedWidth = Math.min(Math.max(Number(width) || 1400, 320), 2200);
  const clampedHeight = Math.min(Math.max(Number(height) || 800, 320), 1600);
  return {
    width: clampedWidth,
    height: clampedHeight,
  };
}

function getDesktopWindowSizeFromSettings() {
  const width = Number((state.settings && state.settings.desktop_window_width) || 0);
  const height = Number((state.settings && state.settings.desktop_window_height) || 0);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }
  return clampDesktopSize(width, height);
}

function applyDesktopWindowState(width, height) {
  if (!isDesktopDevice()) return;
  syncDesktopModeClass();

  const size = clampDesktopSize(width, height);
  document.documentElement.style.setProperty("--desktop-app-width", `${size.width}px`);
  document.documentElement.style.setProperty("--desktop-app-height", `${size.height}px`);
}

function persistDesktopWindowState(size) {
  const serialized = JSON.stringify(size);
  localStorage.setItem(scopedStorageKey(STORAGE_KEYS.desktopWindow), serialized);
  localStorage.setItem(STORAGE_KEYS.desktopWindow, serialized);
}

function queueDesktopWindowRemoteSync(size) {
  if (!isDesktopDevice()) return;

  desktopPendingRemoteSize = size;
  clearTimeout(desktopRemoteSyncTimer);
  desktopRemoteSyncTimer = window.setTimeout(() => {
    desktopRemoteSyncTimer = null;
    void flushDesktopWindowRemoteSync();
  }, DESKTOP_REMOTE_SYNC_DEBOUNCE_MS);
}

async function flushDesktopWindowRemoteSync(options = {}) {
  const keepalive = Boolean(options.keepalive);
  if (desktopRemoteSyncInFlight || !desktopPendingRemoteSize) return;

  const size = desktopPendingRemoteSize;
  desktopPendingRemoteSize = null;
  const snapshot = `${size.width}x${size.height}`;
  if (snapshot === desktopLastRemoteSnapshot) {
    return;
  }

  desktopRemoteSyncInFlight = true;
  try {
    const saved = await apiJson("/api/webapp/settings", {
      method: "PUT",
      keepalive,
      body: JSON.stringify({
        desktop_window_width: size.width,
        desktop_window_height: size.height,
      }),
    });
    state.settings = {
      ...(state.settings || {}),
      ...saved,
    };
    const syncedSize = clampDesktopSize(
      saved.desktop_window_width || size.width,
      saved.desktop_window_height || size.height
    );
    desktopLastRemoteSnapshot = `${syncedSize.width}x${syncedSize.height}`;
    persistDesktopWindowState(syncedSize);
  } catch (_error) {
    // Keep local state; server sync will retry on next resize/change.
  } finally {
    desktopRemoteSyncInFlight = false;
  }
}

function saveDesktopWindowState(options = {}) {
  if (!isDesktopDevice()) return;

  const force = Boolean(options.force);
  if (!force && !isDesktopPersistenceReady()) {
    return;
  }
  if (!desktopResizeSignal) {
    return;
  }

  const snapshot = getCurrentDesktopWindowSize();
  const size = clampDesktopSize(snapshot.width, snapshot.height);
  markDesktopWindowDirtyIfChanged(size);
  if (!desktopWindowDirty) {
    desktopResizeSignal = false;
    return;
  }

  applyDesktopWindowState(size.width, size.height);
  persistDesktopWindowState(size);
  queueDesktopWindowRemoteSync(size);
  desktopSessionBaseline = size;
  desktopWindowDirty = false;
  desktopResizeSignal = false;
}

function scheduleDesktopWindowPersistence(options = {}) {
  const force = Boolean(options.force);
  clearTimeout(desktopResizeTimer);
  desktopResizeTimer = window.setTimeout(() => {
    saveDesktopWindowState({ force });
  }, DESKTOP_RESIZE_DEBOUNCE_MS);
}

function bindTelegramViewportPersistence() {
  if (desktopTelegramViewportBound) return;

  const webApp = App.state && App.state.tg;
  if (!webApp || typeof webApp.onEvent !== "function") return;

  webApp.onEvent("viewportChanged", () => {
    syncDesktopModeClass();
    // Telegram can emit viewportChanged during startup without user resizing.
    // Do not persist size from this signal to avoid overwriting saved values.
  });
  desktopTelegramViewportBound = true;
}

function clearDesktopRestoreTimers() {
  for (const timerId of desktopRestoreTimerIds) {
    clearTimeout(timerId);
  }
  desktopRestoreTimerIds = [];
}

function tryRestoreHostWindowSize(width, height) {
  if (!isDesktopDevice() || typeof window.resizeTo !== "function") return;

  clearDesktopRestoreTimers();

  const desired = clampDesktopSize(width, height);
  const chromeWidth = Math.max(Number(window.outerWidth || 0) - Number(window.innerWidth || 0), 0);
  const chromeHeight = Math.max(Number(window.outerHeight || 0) - Number(window.innerHeight || 0), 0);
  const targetOuterWidth = Math.round(desired.width + chromeWidth);
  const targetOuterHeight = Math.round(desired.height + chromeHeight);

  const attemptResize = () => {
    const currentWidth = Number(window.innerWidth || 0);
    const currentHeight = Number(getTelegramViewportHeight() || window.innerHeight || 0);

    if (Math.abs(currentWidth - desired.width) <= 8 && Math.abs(currentHeight - desired.height) <= 8) {
      return;
    }

    try {
      window.resizeTo(targetOuterWidth, targetOuterHeight);
    } catch (_error) {
      // Ignore if host app blocks scripted resize.
    }
  };

  attemptResize();
  for (const delayMs of [180, 650, 1400, 2200]) {
    const timerId = window.setTimeout(attemptResize, delayMs);
    desktopRestoreTimerIds.push(timerId);
  }
}

function applyDesktopFullscreenPreference(options = {}) {
  if (!isDesktopDevice()) return;

  const adapter = App.adapters && App.adapters.telegram;
  if (!adapter) return;

  const interactive = Boolean(options.interactive);
  const shouldFullscreen = Boolean(state.settings && state.settings.desktop_fullscreen_enabled);

  if (shouldFullscreen) {
    const ok = typeof adapter.requestFullscreen === "function" ? adapter.requestFullscreen() : false;
    if (interactive && !ok) {
      showToast(t("toast.fullscreenUnavailable"), true);
    }
    return;
  }

  if (typeof adapter.exitFullscreen === "function") {
    const ok = adapter.exitFullscreen();
    if (interactive && !ok) {
      showToast(t("toast.fullscreenUnavailable"), true);
    }
  }
}

function restoreDesktopWindowState() {
  syncDesktopModeClass();
  if (!isDesktopDevice()) {
    return;
  }

  // Keep desktop layout intentionally wider by default for all users.
  const current = getCurrentDesktopWindowSize();
  const size = clampDesktopSize(Math.max(current.width, 1700), current.height);
  applyDesktopWindowState(size.width, size.height);
  applyDesktopFullscreenPreference();
}

function bindDesktopWindowPersistence() {
  syncDesktopModeClass();
}

function saveLocalState() {
  localStorage.setItem(scopedStorageKey(STORAGE_KEYS.period), state.period);
  localStorage.setItem(scopedStorageKey(STORAGE_KEYS.filters), JSON.stringify(state.filters));
}

function restoreLocalState() {
  const savedPeriod = localStorage.getItem(scopedStorageKey(STORAGE_KEYS.period));
  if (savedPeriod) {
    state.period = normalizePeriod(savedPeriod);
  }

  const savedFilters = localStorage.getItem(scopedStorageKey(STORAGE_KEYS.filters));
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

function resetSelect(selectElement, placeholderLabel) {
  if (!selectElement) return;
  selectElement.textContent = "";
  const placeholderOption = document.createElement("option");
  placeholderOption.value = "";
  placeholderOption.textContent = placeholderLabel;
  selectElement.appendChild(placeholderOption);
}

function fillCategorySelect(selectElement, placeholderKey, selectedCategory = "") {
  if (!selectElement) return;

  resetSelect(selectElement, t(placeholderKey));

  const categories = [...state.categoryOrder];
  if (selectedCategory && !categories.includes(selectedCategory)) {
    categories.unshift(selectedCategory);
  }

  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    selectElement.appendChild(option);
  }

  selectElement.value = selectedCategory || "";
}

function populateSubcategorySelect(selectElement, category, selectedSubcategory = "") {
  if (!selectElement) return;

  resetSelect(selectElement, t("filters.chooseSubcategory"));

  const subcategories = [...new Set(state.subcategoryByCategory.get(category) || [])];
  if (selectedSubcategory && !subcategories.includes(selectedSubcategory)) {
    subcategories.unshift(selectedSubcategory);
  }

  for (const subcategory of subcategories) {
    const option = document.createElement("option");
    option.value = subcategory;
    option.textContent = subcategory;
    selectElement.appendChild(option);
  }

  selectElement.value = selectedSubcategory || "";
}

function setCategoryCatalog(items = []) {
  state.categoryCatalog = items;
  state.categoryOrder = items.map((item) => item.category).filter(Boolean);

  const subcategoryMap = new Map();
  for (const item of items) {
    if (!item || !item.category) continue;
    const values = Array.isArray(item.subcategories) ? item.subcategories.filter(Boolean) : [];
    subcategoryMap.set(item.category, values);
  }
  state.subcategoryByCategory = subcategoryMap;

  populateCategorySelects();
}

function populateCategorySelects() {
  const filterSelect = document.getElementById("filterCategory");
  const limitSelect = document.getElementById("limitCategory");
  const createSelect = document.getElementById("createCategory");
  const recurringSelect = document.getElementById("recurringCategory");
  const modalSelect = document.getElementById("modalCategory");

  const previousFilter = (filterSelect && filterSelect.value) || "";
  const previousLimit = (limitSelect && limitSelect.value) || "";
  const previousCreate = (createSelect && createSelect.value) || "";
  const previousRecurring = (recurringSelect && recurringSelect.value) || "";
  const previousModal = (modalSelect && modalSelect.value) || "";

  fillCategorySelect(filterSelect, "filters.category", previousFilter);
  fillCategorySelect(limitSelect, "filters.chooseCategory", previousLimit);
  fillCategorySelect(createSelect, "filters.chooseCategory", previousCreate);
  fillCategorySelect(recurringSelect, "filters.chooseCategory", previousRecurring);
  fillCategorySelect(modalSelect, "filters.chooseCategory", previousModal);

  populateSubcategorySelect(document.getElementById("createSubcategory"), (createSelect && createSelect.value) || "", "");
  populateSubcategorySelect(document.getElementById("recurringSubcategory"), (recurringSelect && recurringSelect.value) || "", "");
  populateSubcategorySelect(document.getElementById("modalSubcategory"), (modalSelect && modalSelect.value) || "", "");

  if (App.actions && App.actions.dashboard && typeof App.actions.dashboard.syncCreateRecordIncomeMode === "function") {
    App.actions.dashboard.syncCreateRecordIncomeMode();
  }
  if (App.actions && App.actions.budget && typeof App.actions.budget.syncRecurringIncomeMode === "function") {
    App.actions.budget.syncRecurringIncomeMode();
  }
  if (App.actions && App.actions.records && typeof App.actions.records.syncRecordEditIncomeMode === "function") {
    App.actions.records.syncRecordEditIncomeMode();
  }
  if (App.actions && App.actions.dashboard && typeof App.actions.dashboard.syncFilterIncomeMode === "function") {
    App.actions.dashboard.syncFilterIncomeMode();
  }
}

function syncFilterIncomeMode() {
  const typeSelect = document.getElementById("filterType");
  const categorySelect = document.getElementById("filterCategory");
  if (!typeSelect || !categorySelect) {
    return;
  }

  const isIncome = typeSelect.value === "income";
  if (isIncome) {
    categorySelect.value = "";
    categorySelect.disabled = true;
    categorySelect.required = false;
    categorySelect.style.display = "none";
    return;
  }

  categorySelect.disabled = false;
  categorySelect.style.display = "";
}

function applyFilterFormValues() {
  document.getElementById("filterDateFrom").value = state.filters.date_from || "";
  document.getElementById("filterDateTo").value = state.filters.date_to || "";
  document.getElementById("filterType").value = state.filters.type || "";
  document.getElementById("filterCategory").value = state.filters.category || "";
  document.getElementById("filterMin").value = state.filters.min_amount || "";
  document.getElementById("filterMax").value = state.filters.max_amount || "";
  document.getElementById("filterQuery").value = state.filters.query || "";
  syncFilterIncomeMode();
  refreshIOSDateMirrors();
}

function readFilterFormValues() {
  const type = document.getElementById("filterType").value;
  const category = type === "income" ? "" : document.getElementById("filterCategory").value;
  state.filters = {
    date_from: document.getElementById("filterDateFrom").value,
    date_to: document.getElementById("filterDateTo").value,
    type,
    category,
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
  if (state.filters.category && state.filters.type !== "income") {
    params.append("categories", state.filters.category);
  }
  if (state.filters.min_amount) params.set("min_amount", state.filters.min_amount);
  if (state.filters.max_amount) params.set("max_amount", state.filters.max_amount);
  if (state.filters.query) params.set("query", state.filters.query);
  return params;
}

function formatDateISO(dateValue) {
  const y = dateValue.getFullYear();
  const m = String(dateValue.getMonth() + 1).padStart(2, "0");
  const d = String(dateValue.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function periodBounds(period) {
  const today = new Date();
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const normalized = normalizePeriod(period);
  const start = new Date(end);

  if (normalized === "week") {
    const weekday = (end.getDay() + 6) % 7;
    start.setDate(start.getDate() - weekday);
    return { from: formatDateISO(start), to: formatDateISO(end) };
  }
  if (normalized === "month") {
    start.setDate(1);
    return { from: formatDateISO(start), to: formatDateISO(end) };
  }
  if (normalized === "6m") {
    start.setDate(start.getDate() - 182);
    return { from: formatDateISO(start), to: formatDateISO(end) };
  }
  if (normalized === "year") {
    start.setDate(start.getDate() - 364);
    return { from: formatDateISO(start), to: formatDateISO(end) };
  }

  start.setDate(start.getDate() - 29);
  return { from: formatDateISO(start), to: formatDateISO(end) };
}

async function applyCategoryDrilldown(category, subcategory = "") {
  if (!category) return;

  const bounds = periodBounds(state.period);
  state.filters = {
    ...state.filters,
    date_from: bounds.from,
    date_to: bounds.to,
    type: "expense",
    category,
    query: subcategory || "",
  };

  applyFilterFormValues();
  saveLocalState();
  setActivePage("operations");
  await loadRecords(true);
  showToast(t("toast.drilldownApplied"));
}

function chartConfigBase() {
  const textColor = getComputedStyle(document.body).getPropertyValue("--text").trim();
  const mutedColor = getComputedStyle(document.body).getPropertyValue("--muted").trim();
  const panelBorder = getComputedStyle(document.body).getPropertyValue("--panel-border").trim();
  const isLightTheme = document.body.classList.contains("theme-light");
  const tooltipBackground = isLightTheme ? "rgba(255, 255, 255, 0.96)" : "rgba(6, 22, 30, 0.92)";
  const tooltipBodyColor = isLightTheme ? "#395567" : "#cce6e2";

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
        backgroundColor: tooltipBackground,
        titleColor: textColor,
        bodyColor: tooltipBodyColor,
      },
    },
    scales: {
      x: {
        ticks: { color: mutedColor },
        grid: { color: panelBorder },
      },
      y: {
        ticks: { color: mutedColor },
        grid: { color: panelBorder },
      },
    },
  };
}

function renderChart(key, canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const chartRegistry = App.adapters && App.adapters.chart;
  if (!chartRegistry) {
    if (state.charts[key]) {
      state.charts[key].destroy();
    }
    state.charts[key] = new Chart(canvas, config);
    return;
  }

  const chart = chartRegistry.render(key, canvas, config);
  if (chart) {
    state.charts[key] = chart;
  }
}

function palette() {
  return ["#2dd4bf", "#56ccf2", "#f4b942", "#60d394", "#ff6b6b", "#5ea1ff", "#ffc36e", "#7fe3ce"];
}

function isCompactViewport() {
  return window.matchMedia("(max-width: 720px)").matches;
}

function truncateLabel(label, maxLength) {
  const text = String(label || "").trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 1))}...`;
}

function toChartNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const normalized = value.trim().replace(/\s+/g, "").replace(",", ".");
    const parsed = Number(normalized);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatCompactTick(value) {
  const amount = toChartNumber(value);
  try {
    if (Math.abs(amount) >= 1000) {
      return new Intl.NumberFormat(undefined, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(amount);
    }
  } catch (_error) {
    // Fallback to plain rounded number when compact formatting is unavailable.
  }
  return String(Math.round(amount));
}

function formatSharePercent(amount, total) {
  const safeAmount = toChartNumber(amount);
  const safeTotal = toChartNumber(total);
  if (safeTotal <= 0) {
    return "0%";
  }
  return `${((safeAmount / safeTotal) * 100).toFixed(1)}%`;
}

function renderRecentOperations(items) {
  const container = document.getElementById("recentOperations");
  container.textContent = "";

  if (!items || items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "status-text";
    empty.textContent = t("messages.noOperations");
    container.appendChild(empty);
    return;
  }

  for (const item of items.slice(0, 8)) {
    const typeLabel = item.type === "income" ? t("filters.income") : t("filters.expense");
    const wrapper = document.createElement("div");
    wrapper.className = "recent-item";

    const left = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${item.category}${item.subcategory ? ` (${item.subcategory})` : ""}`;
    const subtitle = document.createElement("small");
    subtitle.textContent = `${item.happened_on} - ${typeLabel}`;
    left.append(title, subtitle);

    const amount = document.createElement("strong");
    amount.textContent = formatAmount(item.amount);

    wrapper.append(left, amount);
    container.appendChild(wrapper);
  }
}

function renderDashboardCharts(data) {
  const categories = data.categories || [];
  const trend = data.trend || [];
  const compact = isCompactViewport();
  const categoryAmounts = categories.map((item) => toChartNumber(item.amount));
  const totalCategoryAmount = categoryAmounts.reduce((sum, amount) => sum + amount, 0);
  const rawCategoryLabels = categories.map((item) => item.category || "");
  const chartCategoryLabels = rawCategoryLabels.map((label) => truncateLabel(label, compact ? 16 : 24));

  const common = chartConfigBase();

  renderChart("categoryPie", "categoryPie", {
    type: "doughnut",
    data: {
      labels: categories.map((item) => item.category),
      datasets: [
        {
          data: categoryAmounts,
          backgroundColor: palette(),
          borderWidth: 0,
        },
      ],
    },
    options: {
      ...common,
      scales: {},
      onClick: async (_event, elements) => {
        if (!elements || elements.length === 0) return;
        const selected = categories[elements[0].index];
        if (!selected) return;
        await applyCategoryDrilldown(selected.category);
      },
    },
  });

  renderChart("trendLine", "trendLine", {
    type: "line",
    data: {
      labels: trend.map((row) => row.date),
      datasets: [
        {
          label: t("chart.income"),
          data: trend.map((row) => toChartNumber(row.income)),
          borderColor: "#2bc06f",
          backgroundColor: "rgba(43, 192, 111, 0.14)",
          tension: 0.35,
          fill: true,
        },
        {
          label: t("chart.expense"),
          data: trend.map((row) => toChartNumber(row.expense)),
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
      labels: chartCategoryLabels,
      datasets: [
        {
          label: t("chart.expenses"),
          data: categoryAmounts,
          backgroundColor: (ctx) => {
            const chart = ctx.chart;
            const area = chart.chartArea;
            if (!area) {
              return "rgba(86, 204, 242, 0.72)";
            }
            const gradient = chart.ctx.createLinearGradient(0, area.bottom, 0, area.top);
            gradient.addColorStop(0, "rgba(67, 170, 210, 0.55)");
            gradient.addColorStop(0.55, "rgba(86, 204, 242, 0.78)");
            gradient.addColorStop(1, "rgba(126, 230, 255, 0.95)");
            return gradient;
          },
          borderColor: "rgba(139, 226, 251, 0.9)",
          borderWidth: 1,
          borderRadius: 8,
          minBarLength: 6,
          maxBarThickness: compact ? 18 : 30,
          barPercentage: 0.68,
          categoryPercentage: 0.76,
        },
      ],
    },
    options: {
      ...common,
      animation: {
        duration: 620,
        easing: "easeOutQuart",
      },
      layout: {
        padding: {
          top: 8,
          right: 10,
          left: 6,
          bottom: 2,
        },
      },
      plugins: {
        ...common.plugins,
        legend: {
          ...common.plugins.legend,
          display: false,
        },
        tooltip: {
          ...common.plugins.tooltip,
          callbacks: {
            title: (items) => {
              const index = items && items[0] ? items[0].dataIndex : -1;
              return index >= 0 ? rawCategoryLabels[index] : "";
            },
            label: (context) => {
              const amount = categoryAmounts[context.dataIndex] || 0;
              return `${t("chart.expenses")}: ${formatAmount(amount)}`;
            },
            afterLabel: (context) => {
              const amount = categoryAmounts[context.dataIndex] || 0;
              return `${t("chart.sharePercent")}: ${formatSharePercent(amount, totalCategoryAmount)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ...common.scales.x,
          offset: true,
          grid: {
            color: "rgba(117, 162, 186, 0.14)",
            offset: true,
          },
          ticks: {
            ...common.scales.x.ticks,
            autoSkip: false,
            minRotation: 0,
            maxRotation: 0,
            padding: 6,
          },
        },
        y: {
          ...common.scales.y,
          beginAtZero: true,
          grid: {
            display: false,
          },
          ticks: {
            ...common.scales.y.ticks,
            callback: (value) => formatCompactTick(value),
            maxTicksLimit: compact ? 5 : 7,
            padding: 8,
          },
        },
      },
      onClick: async (_event, elements) => {
        if (!elements || elements.length === 0) return;
        const selected = categories[elements[0].index];
        if (!selected) return;
        await applyCategoryDrilldown(selected.category);
      },
    },
  });

}

function renderRecommendations(items) {
  const list = document.getElementById("recommendationsList");
  list.textContent = "";

  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.textContent = t("messages.noRecommendations");
    list.appendChild(li);
    return;
  }

  for (const tip of items) {
    const li = document.createElement("li");
    li.textContent = tip;
    list.appendChild(li);
  }
}

function updateAnalyticsHint() {
  const hint = document.getElementById("analyticsSubcategoryHint");
  if (!hint) return;
  hint.textContent = state.analytics.selectedCategory || t("analytics.selectCategoryHint");
}

function renderAnalyticsSubcategoryChart(subcategoryDistribution = []) {
  const selected = state.analytics.selectedCategory;
  const match = subcategoryDistribution.find((item) => item.category === selected);
  const bucket = match || subcategoryDistribution[0] || null;

  if (!bucket) {
    state.analytics.selectedCategory = "";
    updateAnalyticsHint();
    renderChart("analyticsSubcategory", "analyticsSubcategory", {
      type: "bar",
      data: {
        labels: ["-"],
        datasets: [{ label: t("chart.expenses"), data: [0], backgroundColor: "rgba(157, 180, 194, 0.35)" }],
      },
      options: chartConfigBase(),
    });
    return;
  }

  state.analytics.selectedCategory = bucket.category;
  updateAnalyticsHint();

  const labels = (bucket.subcategories || []).map((item) => item.subcategory || "-");
  const values = (bucket.subcategories || []).map((item) => Number(item.amount || 0));
  const hasData = values.some((value) => value > 0);

  const dataLabels = hasData ? labels : [t("messages.noSubcategoryData")];
  const dataValues = hasData ? values : [0];

  renderChart("analyticsSubcategory", "analyticsSubcategory", {
    type: "bar",
    data: {
      labels: dataLabels,
      datasets: [
        {
          label: t("chart.expenses"),
          data: dataValues,
          backgroundColor: "rgba(45, 212, 191, 0.72)",
          borderRadius: 8,
        },
      ],
    },
    options: {
      ...chartConfigBase(),
      onClick: async (_event, elements) => {
        if (!hasData || !elements || elements.length === 0) return;
        const selectedSub = bucket.subcategories[elements[0].index];
        await applyCategoryDrilldown(bucket.category, (selectedSub && selectedSub.subcategory) || "");
      },
    },
  });
}

function applyTheme(theme) {
  document.body.classList.toggle("theme-light", theme === "light");
  document.body.classList.toggle("theme-dark", theme !== "light");
}

async function loadCategoriesByLanguage(language) {
  const payload = await apiJson(`/api/webapp/categories?language=${encodeURIComponent(language)}`);
  setCategoryCatalog(payload.items || []);
}

function fillSettingsForm(settings) {
  document.getElementById("settingTheme").value = settings.theme || "dark";

  const allowed = new Set(["UAH", "USD", "EUR"]);
  const selectedCurrency = allowed.has((settings.currency || "").toUpperCase())
    ? settings.currency.toUpperCase()
    : "UAH";
  document.getElementById("settingCurrency").value = selectedCurrency;
  document.getElementById("settingLanguage").value = settings.interface_language || "uk";
  document.getElementById("settingNotifications").checked = Boolean(settings.notifications_enabled);
  const warningInput = document.getElementById("settingBudgetWarning");
  const dangerInput = document.getElementById("settingBudgetDanger");
  if (warningInput) warningInput.value = Number(settings.budget_warning_percent || 80);
  if (dangerInput) dangerInput.value = Number(settings.budget_danger_percent || 100);
  const fullscreenToggle = document.getElementById("settingFullscreen");
  if (fullscreenToggle) {
    fullscreenToggle.checked = Boolean(settings.desktop_fullscreen_enabled);
  }
}

async function loadBootstrap() {
  const data = await apiJson("/api/webapp/bootstrap");
  state.bootstrap = data;
  state.settings = data.settings;

  applyTheme(state.settings.theme || "dark");
  fillSettingsForm(state.settings || {});
  await loadCategoriesByLanguage(state.settings.interface_language || (data.user && data.user.language) || "uk");
  applyTranslationsToDom();
  setCreateFormDefaults();
  refreshIOSDateMirrors();
}

async function loadDashboard() {
  const data = await apiJson(`/api/webapp/dashboard?period=${encodeURIComponent(state.period)}`);

  animateAmount(document.getElementById("cardBalance"), data.totals.balance);
  animateAmount(document.getElementById("cardIncome"), data.totals.incomes);
  animateAmount(document.getElementById("cardExpense"), data.totals.expenses);
  animateAmount(document.getElementById("cardRemaining"), data.totals.remaining);

  renderRecentOperations(data.recent_operations || []);
  renderDashboardCharts(data);
}

function setCreateFormDefaults() {
  const createDate = document.getElementById("createDate");
  const createType = document.getElementById("createType");
  if (createDate && !createDate.value) {
    createDate.value = formatDateISO(new Date());
  }
  if (createType && !createType.value) {
    createType.value = "expense";
  }

  syncCreateRecordIncomeMode();
  refreshIOSDateMirrors();
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

function syncCreateRecordIncomeMode() {
  const typeSelect = document.getElementById("createType");
  const categorySelect = document.getElementById("createCategory");
  const subcategorySelect = document.getElementById("createSubcategory");
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

async function submitCreateRecord(event) {
  event.preventDefault();

  const type = document.getElementById("createType").value;
  const defaults = getIncomeDefaults();
  const isIncome = type === "income";
  const category = isIncome
    ? defaults.category
    : document.getElementById("createCategory").value.trim();
  const subcategory = isIncome
    ? defaults.subcategory
    : document.getElementById("createSubcategory").value.trim();
  const amount = Number(document.getElementById("createAmount").value);
  const happenedOn = document.getElementById("createDate").value;
  const description = document.getElementById("createDescription").value.trim();

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

  await apiJson("/api/webapp/records", {
    method: "POST",
    body: JSON.stringify({
      type,
      category,
      subcategory: subcategory || null,
      amount,
      happened_on: happenedOn,
      description,
      currency: (state.settings && state.settings.currency) || "UAH",
    }),
  });

  document.getElementById("createAmount").value = "";
  document.getElementById("createDescription").value = "";
  showToast(t("toast.recordCreated"));
  await refreshAllData();
}

App.actions = App.actions || {};
App.actions.dashboard = {
  setActivePage,
  normalizePeriod,
  saveLocalState,
  restoreLocalState,
  restoreDesktopWindowState,
  applyDesktopFullscreenPreference,
  bindDesktopWindowPersistence,
  loadCategoriesByLanguage,
  populateSubcategorySelect,
  applyCategoryDrilldown,
  syncFilterIncomeMode,
  applyFilterFormValues,
  readFilterFormValues,
  updatePeriodButtons,
  loadBootstrap,
  loadDashboard,
  submitCreateRecord,
  syncCreateRecordIncomeMode,
  refreshIOSDateMirrors,
};


