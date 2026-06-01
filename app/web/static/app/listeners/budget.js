var App = window.App || (window.App = {});

function bindBudgetEvents() {
  const budget = App.actions.budget;
  const dashboard = App.actions.dashboard;

  const budgetPlanForm = document.getElementById("budgetPlanForm");
  if (budgetPlanForm && budget && typeof budget.saveBudgetPlan === "function") {
    budgetPlanForm.addEventListener("submit", budget.saveBudgetPlan);
  }

  const addLimitBtn = document.getElementById("addLimitBtn");
  if (addLimitBtn && budget && typeof budget.addLimit === "function") {
    addLimitBtn.addEventListener("click", budget.addLimit);
  }

  const saveLimitsBtn = document.getElementById("saveLimitsBtn");
  if (saveLimitsBtn && budget && typeof budget.saveLimits === "function") {
    saveLimitsBtn.addEventListener("click", budget.saveLimits);
  }

  const limitsBody = document.getElementById("limitsBody");
  if (limitsBody && budget && typeof budget.handleLimitTableClick === "function") {
    limitsBody.addEventListener("click", budget.handleLimitTableClick);
  }

  const alertSelect = document.getElementById("limitAlertMode");
  if (alertSelect) {
    alertSelect.addEventListener("change", (e) => {
      const customInput = document.getElementById("limitAlertCustomPercent");
      if (!customInput) return;
      customInput.style.display = e.target.value === "custom" ? "inline-block" : "none";
    });
  }

  const recurringForm = document.getElementById("recurringForm");
  if (recurringForm && budget && typeof budget.createRecurring === "function") {
    recurringForm.addEventListener("submit", budget.createRecurring);
  }

  const reloadRecurringBtn = document.getElementById("reloadRecurringBtn");
  if (reloadRecurringBtn && budget && typeof budget.loadRecurring === "function") {
    reloadRecurringBtn.addEventListener("click", budget.loadRecurring);
  }

  const recurringBody = document.getElementById("recurringBody");
  if (recurringBody && budget && typeof budget.handleRecurringTableClick === "function") {
    recurringBody.addEventListener("click", budget.handleRecurringTableClick);
  }

  const recurringTypeElement = document.getElementById("recurringType");
  if (recurringTypeElement && budget && typeof budget.syncRecurringIncomeMode === "function") {
    recurringTypeElement.addEventListener("change", budget.syncRecurringIncomeMode);
  }

  const recurringCategoryElement = document.getElementById("recurringCategory");
  if (recurringCategoryElement) {
    recurringCategoryElement.addEventListener("change", () => {
      if (document.getElementById("recurringType").value !== "expense") {
        return;
      }
      dashboard.populateSubcategorySelect(
        document.getElementById("recurringSubcategory"),
        document.getElementById("recurringCategory").value,
        ""
      );
    });
  }

  const limitCategory = document.getElementById("limitCategory");
  if (limitCategory) {
    limitCategory.addEventListener("change", () => {
      dashboard.populateSubcategorySelect(
        document.getElementById("limitSubcategory"),
        limitCategory.value || "",
        ""
      );
    });
  }

  const analyticsRangeForm = document.getElementById("analyticsRangeForm");
  if (analyticsRangeForm && budget && typeof budget.applyAnalyticsRange === "function") {
    analyticsRangeForm.addEventListener("submit", budget.applyAnalyticsRange);
  }

  const analyticsRangeResetBtn = document.getElementById("analyticsRangeResetBtn");
  if (analyticsRangeResetBtn && budget && typeof budget.resetAnalyticsRange === "function") {
    analyticsRangeResetBtn.addEventListener("click", budget.resetAnalyticsRange);
  }

  const analyticsPrevMonthBtn = document.getElementById("analyticsPrevMonthBtn");
  if (analyticsPrevMonthBtn && budget && typeof budget.showPreviousAnalyticsMonth === "function") {
    analyticsPrevMonthBtn.addEventListener("click", budget.showPreviousAnalyticsMonth);
  }

  const analyticsNextMonthBtn = document.getElementById("analyticsNextMonthBtn");
  if (analyticsNextMonthBtn && budget && typeof budget.showNextAnalyticsMonth === "function") {
    analyticsNextMonthBtn.addEventListener("click", budget.showNextAnalyticsMonth);
  }

  if (budget && typeof budget.syncRecurringIncomeMode === "function") {
    budget.syncRecurringIncomeMode();
  }
}

App.listeners = App.listeners || {};
App.listeners.budget = {
  bindBudgetEvents,
};
