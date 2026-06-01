const STORAGE_KEYS = {
  period: "finance_webapp_period",
  filters: "finance_webapp_filters",
  desktopWindow: "finance_webapp_desktop_window",
};

var App = window.App || (window.App = {});

class AppState {
  constructor() {
    this.tg = null;
    this.initData = "";
    this.period = "month";
    this.bootstrap = null;
    this.settings = null;
    this.charts = {};
    this.categoryCatalog = [];
    this.categoryOrder = [];
    this.subcategoryByCategory = new Map();
    this.records = {
      offset: 0,
      limit: 5,
      hasMore: false,
      map: new Map(),
      editingRecordId: null,
      deleteRecordId: null,
    };
    this.filters = {
      date_from: "",
      date_to: "",
      type: "",
      category: "",
      min_amount: "",
      max_amount: "",
      query: "",
    };
    this.budgetLimits = [];
    this.recurring = {
      items: [],
    };
    this.analytics = {
      selectedCategory: "",
      dateFrom: "",
      dateTo: "",
      lastPeriodFrom: "",
      lastPeriodTo: "",
    };
    this.budgetSparklines = {
      keys: [],
      items: [],
      expiresAt: 0,
    };
  }

  resetFilters() {
    this.filters = {
      date_from: "",
      date_to: "",
      type: "",
      category: "",
      min_amount: "",
      max_amount: "",
      query: "",
    };
  }
}

const state = new AppState();

const DEFAULT_INCOME_CONFIG = Object.freeze({
  category: "Salary",
  subcategory: "Main",
});

App.config = App.config || {};
if (!App.config.incomeDefaults) {
  App.config.incomeDefaults = {
    category: DEFAULT_INCOME_CONFIG.category,
    subcategory: DEFAULT_INCOME_CONFIG.subcategory,
  };
}

const I18N = {
  en: {
    top: { eyebrow: "Telegram Finance", title: "Personal Control Center", refresh: "Refresh" },
    period: { week: "Week", month: "Month", "6m": "6 Months", year: "Year" },
    dashboard: {
      balance: "Balance",
      income: "Income",
      expense: "Expense",
      remaining: "Remaining",
      expenseByCategories: "Expense by Categories",
      incomeVsExpenseTrend: "Income vs Expense Trend",
      categoryComparison: "Category Comparison",
      recentOperations: "Recent Operations",
    },
    operations: {
      title: "Operations",
      exportCsv: "Export CSV",
      exportPdf: "Export PDF",
      loadMore: "Load More",
      newOperation: "New Operation",
      filtersTitle: "Operations Filter",
      create: "Create",
    },
    filters: {
      type: "Type",
      income: "Income",
      expense: "Expense",
      category: "Category",
      min: "Min",
      max: "Max",
      search: "Search by text",
      apply: "Apply",
      reset: "Reset",
      chooseCategory: "Choose Category",
      chooseSubcategory: "Choose Subcategory",
    },
    table: {
      date: "Date",
      description: "Description",
      category: "Category",
      type: "Type",
      amount: "Amount",
      source: "Source",
      actions: "Actions",
      limit: "Limit",
      spent: "Spent",
      remaining: "Remaining",
      forecast: "Forecast",
      status: "Status",
    },
    analytics: {
      dayExpense: "Day Expense",
      weekExpense: "Week Expense",
      monthExpense: "Month Expense",
      averageExpense: "Average Expense",
      maxExpense: "Max Expense",
      forecastNextMonth: "Forecast Next Month",
      periodAnalysis: "Period Analysis",
      rangeFrom: "From",
      rangeTo: "To",
      applyRange: "Apply",
      clearRange: "Reset",
      prevMonth: "Prev Month",
      nextMonth: "Next Month",
      rangeShown: "Showing",
      rangeCustomTag: "custom",
      rangePresetTag: "tab period",
      rangeBothDates: "Select both dates",
      rangeOrderInvalid: "Start date must be earlier than end date",
      monthlyComparison: "Monthly Comparison",
      distribution: "Distribution by Category",
      subcategoryDistribution: "Subcategory Breakdown",
      recommendations: "Recommendations",
      selectCategoryHint: "Tap a category to see subcategories",
      budgetOverview: "Budget Overview",
      budgetPeriodLabel: "Period",
      "budget.periodLabel": "Period",
      budgetPlanned: "Planned",
      budgetSpent: "Spent",
      budgetRemaining: "Remaining",
      budgetUsed: "Used %",
      budgetNoPlan: "Set a monthly budget to unlock insights.",
      budgetExceeded: "Budget exceeded",
      budgetNear: "Budget close to limit",
      budgetDeficit: "Overspend",
      dailyBudget: "Daily target",
      perDay: "per day",
      planBelowAverage: "Plan below 3-month average",
      planAboveAverage: "Plan above 3-month average",
      limitForecast: "Forecast risk",
      limitAlert: "Limit alert",
      budgetRecommendations: "Budget recommendations",
      budgetWarning: "Warning",
      budgetDanger: "Danger",
      noLimitsSet: "Set category limits to keep spending under control.",
      forecastOverPlan: "Forecast above plan",
      forecastUnderPlan: "Forecast below plan",
      topCategoryHeavy: "Top category share",
      dailyLimitHint: "Daily cap",
      weekSpike: "Weekly spike",
      weekDrop: "Weekly drop",
      volatilityHigh: "Spending volatility high",
      volatilityMedium: "Spending volatility rising",
    },
    budget: {
      monthlyBudget: "Monthly Budget",
      start: "Start",
      end: "End",
      plannedExpense: "Planned Expense",
      plannedIncome: "Planned Income",
      savePlan: "Save Plan",
      categoryLimits: "Category Limits",
      limit: "Limit",
      limitAlertAlways: "Always notify",
      limitAlertThreshold50: "Notify from 50%",
      limitAlertThreshold70: "Notify from 70%",
      limitAlertCustom: "Custom threshold",
      add: "Add",
      saveLimits: "Save Limits",
      spent: "Spent",
      remaining: "Remaining",
      used: "Used",
      recurringTitle: "Recurring Items",
      recurringName: "Name",
      recurringType: "Type",
      recurringCategory: "Category",
      recurringSubcategory: "Subcategory",
      recurringAmount: "Amount",
      recurringDay: "Day of month",
      recurringReminder: "Reminder days before",
      recurringActive: "Active",
      addRecurring: "Add recurring",
      recurringDue: "Due",
    },
    settings: {
      title: "Settings",
      theme: "Theme",
      themeDark: "Dark",
      themeLight: "Light",
      currency: "Currency",
      interfaceLanguage: "Interface Language",
      langUk: "Ukrainian",
      langRu: "Russian",
      langEn: "English",
      notifications: "Enable Notifications",
      budgetWarning: "Budget warning %",
      budgetDanger: "Budget danger %",
      fullscreen: "Fullscreen",
      save: "Save Settings",
    },
    nav: {
      dashboard: "Dashboard",
      operations: "Operations",
      analytics: "Analytics",
      budget: "Budget",
      settings: "Settings",
    },
    status: {
      exceeded: "Exceeded",
      near_limit: "Near Limit",
      normal: "Normal",
      paused: "Paused",
      pending: "Pending",
      confirmed: "Confirmed",
      reminder: "Reminder",
    },
    messages: {
      noOperations: "No operations yet for selected period.",
      noRecommendations: "No recommendations right now.",
      noRecords: "No records found for current filters.",
      noCategoryLimits: "No category limits yet.",
      noRecurring: "No recurring items yet.",
      noSubcategoryData: "No subcategory data for selected category.",
    },
    record: { sourceManual: "manual" },
    actions: {
      edit: "Edit",
      delete: "Delete",
      remove: "Remove",
      view: "View",
      undo: "Undo",
      confirm: "Confirm",
      pause: "Pause",
      resume: "Resume",
    },
    modal: {
      editTitle: "Edit Record",
      deleteTitle: "Delete Record",
      category: "Category",
      subcategory: "Subcategory",
      type: "Type",
      amount: "Amount",
      date: "Date",
      description: "Description",
      cancel: "Cancel",
      save: "Save",
      delete: "Delete",
      deleteQuestion: "Delete this record?",
    },
    toast: {
      dataRefreshed: "Data refreshed",
      settingsSaved: "Settings saved",
      fullscreenRequested: "Fullscreen requested",
      fullscreenUnavailable: "Fullscreen is unavailable",
      recordCreated: "Record created",
      recordUpdated: "Record updated",
      recordDeleted: "Record deleted",
      limitsSaved: "Category limits saved",
      budgetSaved: "Budget plan saved",
      budgetDeleted: "Budget deleted",
      budgetRestored: "Budget restored",
      budgetThresholdsInvalid: "Warning must be lower than danger",
      appReady: "Web App is ready",
      drilldownApplied: "Drill-down filters applied",
      recurringCreated: "Recurring item created",
      recurringUpdated: "Recurring item updated",
      recurringConfirmed: "Recurring item confirmed",
      selectCategory: "Select category first",
      nonNegativeLimit: "Limit amount must be non-negative",
      setPeriodFirst: "Set budget period first",
      periodRequired: "Date period is required",
      categoryRequired: "Category is required",
      dateRequired: "Date is required",
      descriptionRequired: "Description is required",
      amountPositive: "Amount must be positive",
      typeIncomeExpense: "Type must be income or expense",
      initFailed: "Failed to initialize app",
    },
    chart: {
      income: "Income",
      expense: "Expense",
      expenses: "Expenses",
      sharePercent: "Share %",
      spent: "Spent",
      remaining: "Remaining",
    },
  },
  ru: {
    top: { eyebrow: "Telegram Финансы", title: "Личный финансовый центр", refresh: "Обновить" },
    period: { week: "Неделя", month: "Месяц", "6m": "6 месяцев", year: "Год" },
    dashboard: {
      balance: "Баланс",
      income: "Доход",
      expense: "Расход",
      remaining: "Остаток",
      expenseByCategories: "Расходы по категориям",
      incomeVsExpenseTrend: "Тренд доходов и расходов",
      categoryComparison: "Сравнение категорий",
      recentOperations: "Последние операции",
    },
    operations: {
      title: "Операции",
      exportCsv: "Экспорт CSV",
      exportPdf: "Экспорт PDF",
      loadMore: "Загрузить еще",
      newOperation: "Новая операция",
      filtersTitle: "Фильтр операций",
      create: "Создать",
    },
    filters: {
      type: "Тип",
      income: "Доход",
      expense: "Расход",
      category: "Категория",
      min: "Мин",
      max: "Макс",
      search: "Поиск по тексту",
      apply: "Применить",
      reset: "Сброс",
      chooseCategory: "Выберите категорию",
      chooseSubcategory: "Выберите подкатегорию",
    },
    table: {
      date: "Дата",
      description: "Описание",
      category: "Категория",
      type: "Тип",
      amount: "Сумма",
      source: "Источник",
      actions: "Действия",
      limit: "Лимит",
      spent: "Потрачено",
      remaining: "Остаток",
      forecast: "Прогноз",
      status: "Статус",
    },
    analytics: {
      dayExpense: "Расход за день",
      weekExpense: "Расход за неделю",
      monthExpense: "Расход за месяц",
      averageExpense: "Средний расход",
      maxExpense: "Макс. расход",
      forecastNextMonth: "Прогноз на месяц",
      periodAnalysis: "Анализ периода",
      rangeFrom: "С",
      rangeTo: "По",
      applyRange: "Применить",
      clearRange: "Сброс",
      prevMonth: "Прошлый месяц",
      nextMonth: "Следующий месяц",
      rangeShown: "Показано",
      rangeCustomTag: "кастомный",
      rangePresetTag: "период вкладки",
      rangeBothDates: "Выберите обе даты",
      rangeOrderInvalid: "Дата начала должна быть раньше даты окончания",
      monthlyComparison: "Сравнение по месяцам",
      distribution: "Распределение по категориям",
      subcategoryDistribution: "Детализация подкатегорий",
      recommendations: "Рекомендации",
      selectCategoryHint: "Нажмите на категорию, чтобы увидеть подкатегории",
      budgetOverview: "Обзор бюджета",
      budgetPeriodLabel: "Период",
      "budget.periodLabel": "Период",
      budgetPlanned: "План",
      budgetSpent: "Потрачено",
      budgetRemaining: "Остаток",
      budgetUsed: "Использовано %",
      budgetNoPlan: "Задайте месячный бюджет, чтобы получить подсказки.",
      budgetExceeded: "Бюджет превышен",
      budgetNear: "Бюджет близок к лимиту",
      budgetDeficit: "Перерасход",
      dailyBudget: "Дневной лимит",
      perDay: "в день",
      planBelowAverage: "План ниже среднего за 3 месяца",
      planAboveAverage: "План выше среднего за 3 месяца",
      limitForecast: "Риск по прогнозу",
      limitAlert: "Лимит превышается",
      budgetRecommendations: "Советы по бюджету",
      budgetWarning: "Предупреждение",
      budgetDanger: "Опасно",
      noLimitsSet: "Задайте лимиты по категориям, чтобы контролировать расходы.",
      forecastOverPlan: "Прогноз выше плана",
      forecastUnderPlan: "Прогноз ниже плана",
      topCategoryHeavy: "Доля топ-категории",
      dailyLimitHint: "Дневной лимит",
      weekSpike: "Скачок за неделю",
      weekDrop: "Падение за неделю",
      volatilityHigh: "Высокая волатильность расходов",
      volatilityMedium: "Растущая волатильность",
    },
    budget: {
      monthlyBudget: "Месячный бюджет",
      start: "Начало",
      end: "Конец",
      plannedExpense: "План расхода",
      plannedIncome: "План дохода",
      savePlan: "Сохранить план",
      categoryLimits: "Лимиты по категориям",
      limit: "Лимит",
      limitAlertAlways: "Уведомлять всегда",
      limitAlertThreshold50: "Уведомлять от 50%",
      limitAlertThreshold70: "Уведомлять от 70%",
      limitAlertCustom: "Произвольный порог",
      add: "Добавить",
      saveLimits: "Сохранить лимиты",
      spent: "Потрачено",
      remaining: "Остаток",
      used: "Использовано",
      recurringTitle: "Регулярные платежи и доходы",
      recurringName: "Название",
      recurringType: "Тип",
      recurringCategory: "Категория",
      recurringSubcategory: "Подкатегория",
      recurringAmount: "Сумма",
      recurringDay: "День месяца",
      recurringReminder: "Напомнить за (дней)",
      recurringActive: "Активно",
      addRecurring: "Добавить регулярный",
      recurringDue: "Срок",
    },
    settings: {
      title: "Настройки",
      theme: "Тема",
      themeDark: "Темная",
      themeLight: "Светлая",
      currency: "Валюта",
      interfaceLanguage: "Язык интерфейса",
      langUk: "Украинский",
      langRu: "Русский",
      langEn: "Английский",
      notifications: "Включить уведомления",
      budgetWarning: "Предупреждение бюджета %",
      budgetDanger: "Опасный порог бюджета %",
      fullscreen: "Полный экран",
      save: "Сохранить настройки",
    },
    nav: {
      dashboard: "Дашборд",
      operations: "Операции",
      analytics: "Аналитика",
      budget: "Бюджет",
      settings: "Настройки",
    },
    status: {
      exceeded: "Превышен",
      near_limit: "Почти лимит",
      normal: "Норма",
      paused: "Пауза",
      pending: "Ожидает",
      confirmed: "Подтверждено",
      reminder: "Напоминание",
    },
    messages: {
      noOperations: "За выбранный период операций нет.",
      noRecommendations: "Рекомендаций пока нет.",
      noRecords: "По текущим фильтрам записи не найдены.",
      noCategoryLimits: "Лимиты по категориям пока не заданы.",
      noRecurring: "Регулярные операции не добавлены.",
      noSubcategoryData: "Нет данных по подкатегориям для выбранной категории.",
    },
    record: { sourceManual: "вручную" },
    actions: {
      edit: "Изменить",
      delete: "Удалить",
      remove: "Убрать",
      view: "Просмотреть",
      undo: "Отменить",
      confirm: "Подтвердить",
      pause: "Остановить",
      resume: "Включить",
    },
    modal: {
      editTitle: "Редактировать запись",
      deleteTitle: "Удаление записи",
      category: "Категория",
      subcategory: "Подкатегория",
      type: "Тип",
      amount: "Сумма",
      date: "Дата",
      description: "Описание",
      cancel: "Отмена",
      save: "Сохранить",
      delete: "Удалить",
      deleteQuestion: "Удалить эту запись?",
    },
    toast: {
      dataRefreshed: "Данные обновлены",
      settingsSaved: "Настройки сохранены",
      fullscreenRequested: "Запрошен полный экран",
      fullscreenUnavailable: "Полный экран недоступен",
      recordCreated: "Запись создана",
      recordUpdated: "Запись обновлена",
      recordDeleted: "Запись удалена",
      limitsSaved: "Лимиты по категориям сохранены",
      budgetSaved: "План бюджета сохранен",
      budgetDeleted: "Бюджет удалён",
      budgetRestored: "Бюджет восстановлен",
      budgetThresholdsInvalid: "Порог предупреждения должен быть ниже опасного",
      appReady: "Web App готов",
      drilldownApplied: "Фильтр применен",
      recurringCreated: "Регулярная операция добавлена",
      recurringUpdated: "Регулярная операция обновлена",
      recurringConfirmed: "Регулярная операция подтверждена",
      selectCategory: "Сначала выберите категорию",
      nonNegativeLimit: "Лимит должен быть неотрицательным",
      setPeriodFirst: "Сначала задайте период бюджета",
      periodRequired: "Нужно заполнить период дат",
      categoryRequired: "Категория обязательна",
      dateRequired: "Дата обязательна",
      descriptionRequired: "Описание обязательно",
      amountPositive: "Сумма должна быть больше нуля",
      typeIncomeExpense: "Тип должен быть income или expense",
      initFailed: "Не удалось инициализировать приложение",
    },
    chart: {
      income: "Доход",
      expense: "Расход",
      expenses: "Расходы",
      sharePercent: "Доля %",
      spent: "Потрачено",
      remaining: "Остаток",
    },
  },
  uk: {
    top: { eyebrow: "Telegram Фінанси", title: "Особистий фінансовий центр", refresh: "Оновити" },
    period: { week: "Тиждень", month: "Місяць", "6m": "6 місяців", year: "Рік" },
    dashboard: {
      balance: "Баланс",
      income: "Дохід",
      expense: "Витрати",
      remaining: "Залишок",
      expenseByCategories: "Витрати за категоріями",
      incomeVsExpenseTrend: "Тренд доходів і витрат",
      categoryComparison: "Порівняння категорій",
      recentOperations: "Останні операції",
    },
    operations: {
      title: "Операції",
      exportCsv: "Експорт CSV",
      exportPdf: "Експорт PDF",
      loadMore: "Завантажити ще",
      newOperation: "Нова операція",
      filtersTitle: "Фільтр операцій",
      create: "Створити",
    },
    filters: {
      type: "Тип",
      income: "Дохід",
      expense: "Витрати",
      category: "Категорія",
      min: "Мін",
      max: "Макс",
      search: "Пошук за текстом",
      apply: "Застосувати",
      reset: "Скинути",
      chooseCategory: "Оберіть категорію",
      chooseSubcategory: "Оберіть підкатегорію",
    },
    table: {
      date: "Дата",
      description: "Опис",
      category: "Категорія",
      type: "Тип",
      amount: "Сума",
      source: "Джерело",
      actions: "Дії",
      limit: "Ліміт",
      spent: "Витрачено",
      remaining: "Залишок",
      forecast: "Прогноз",
      status: "Статус",
    },
    analytics: {
      dayExpense: "Витрати за день",
      weekExpense: "Витрати за тиждень",
      monthExpense: "Витрати за місяць",
      averageExpense: "Середні витрати",
      maxExpense: "Макс. витрати",
      forecastNextMonth: "Прогноз на місяць",
      periodAnalysis: "Аналіз періоду",
      rangeFrom: "Від",
      rangeTo: "До",
      applyRange: "Застосувати",
      clearRange: "Скинути",
      prevMonth: "Минулий місяць",
      nextMonth: "Наступний місяць",
      rangeShown: "Показано",
      rangeCustomTag: "довільний",
      rangePresetTag: "період вкладки",
      rangeBothDates: "Виберіть обидві дати",
      rangeOrderInvalid: "Дата початку має бути раніше дати завершення",
      monthlyComparison: "Порівняння за місяцями",
      distribution: "Розподіл за категоріями",
      subcategoryDistribution: "Деталізація підкатегорій",
      recommendations: "Рекомендації",
      selectCategoryHint: "Натисніть категорію, щоб побачити підкатегорії",
      budgetOverview: "Огляд бюджету",
      budgetPeriodLabel: "Період",
      "budget.periodLabel": "Період",
      budgetPlanned: "План",
      budgetSpent: "Витрачено",
      budgetRemaining: "Залишок",
      budgetUsed: "Використано %",
      budgetNoPlan: "Задайте місячний бюджет, щоб отримати підказки.",
      budgetExceeded: "Бюджет перевищено",
      budgetNear: "Бюджет близький до ліміту",
      budgetDeficit: "Перевитрати",
      dailyBudget: "Денний ліміт",
      perDay: "на день",
      planBelowAverage: "План нижче середнього за 3 місяці",
      planAboveAverage: "План вище середнього за 3 місяці",
      limitForecast: "Ризик за прогнозом",
      limitAlert: "Ліміт перевищується",
      budgetRecommendations: "Поради щодо бюджету",
      budgetWarning: "Попередження",
      budgetDanger: "Небезпечно",
      noLimitsSet: "Задайте ліміти за категоріями, щоб контролювати витрати.",
      forecastOverPlan: "Прогноз вище плану",
      forecastUnderPlan: "Прогноз нижче плану",
      topCategoryHeavy: "Частка топ-категорії",
      dailyLimitHint: "Денний ліміт",
      weekSpike: "Стрибок за тиждень",
      weekDrop: "Падіння за тиждень",
      volatilityHigh: "Висока волатильність витрат",
      volatilityMedium: "Зростає волатильність",
    },
    budget: {
      monthlyBudget: "Місячний бюджет",
      start: "Початок",
      end: "Кінець",
      plannedExpense: "План витрат",
      plannedIncome: "План доходу",
      savePlan: "Зберегти план",
      categoryLimits: "Ліміти за категоріями",
      limit: "Ліміт",
      limitAlertAlways: "Сповіщати завжди",
      limitAlertThreshold50: "Сповіщати від 50%",
      limitAlertThreshold70: "Сповіщати від 70%",
      limitAlertCustom: "Произвольный поріг",
      add: "Додати",
      saveLimits: "Зберегти ліміти",
      spent: "Витрачено",
      remaining: "Залишок",
      used: "Використано",
      recurringTitle: "Регулярні платежі та доходи",
      recurringName: "Назва",
      recurringType: "Тип",
      recurringCategory: "Категорія",
      recurringSubcategory: "Підкатегорія",
      recurringAmount: "Сума",
      recurringDay: "День місяця",
      recurringReminder: "Нагадати за (днів)",
      recurringActive: "Активно",
      addRecurring: "Додати регулярний",
      recurringDue: "Термін",
    },
    settings: {
      title: "Налаштування",
      theme: "Тема",
      themeDark: "Темна",
      themeLight: "Світла",
      currency: "Валюта",
      interfaceLanguage: "Мова інтерфейсу",
      langUk: "Українська",
      langRu: "Російська",
      langEn: "Англійська",
      notifications: "Увімкнути сповіщення",
      budgetWarning: "Попередження бюджету %",
      budgetDanger: "Небезпечний поріг бюджету %",
      fullscreen: "Повний екран",
      save: "Зберегти налаштування",
    },
    nav: {
      dashboard: "Дашборд",
      operations: "Операції",
      analytics: "Аналітика",
      budget: "Бюджет",
      settings: "Налаштування",
    },
    status: {
      exceeded: "Перевищено",
      near_limit: "Майже ліміт",
      normal: "Норма",
      paused: "Пауза",
      pending: "Очікує",
      confirmed: "Підтверджено",
      reminder: "Нагадування",
    },
    messages: {
      noOperations: "За вибраний період операцій немає.",
      noRecommendations: "Рекомендацій поки немає.",
      noRecords: "За поточними фільтрами записи не знайдено.",
      noCategoryLimits: "Ліміти за категоріями ще не задані.",
      noRecurring: "Регулярні операції ще не додані.",
      noSubcategoryData: "Немає даних по підкатегоріях для вибраної категорії.",
    },
    record: { sourceManual: "вручну" },
    actions: {
      edit: "Редагувати",
      delete: "Видалити",
      remove: "Прибрати",
      view: "Переглянути",
      undo: "Скасувати",
      confirm: "Підтвердити",
      pause: "Зупинити",
      resume: "Увімкнути",
    },
    modal: {
      editTitle: "Редагувати запис",
      deleteTitle: "Видалення запису",
      category: "Категорія",
      subcategory: "Підкатегорія",
      type: "Тип",
      amount: "Сума",
      date: "Дата",
      description: "Опис",
      cancel: "Скасувати",
      save: "Зберегти",
      delete: "Видалити",
      deleteQuestion: "Видалити цей запис?",
    },
    toast: {
      dataRefreshed: "Дані оновлено",
      settingsSaved: "Налаштування збережено",
      fullscreenRequested: "Запрошено повний екран",
      fullscreenUnavailable: "Повний екран недоступний",
      recordCreated: "Запис створено",
      recordUpdated: "Запис оновлено",
      recordDeleted: "Запис видалено",
      limitsSaved: "Ліміти за категоріями збережено",
      budgetSaved: "План бюджету збережено",
      budgetDeleted: "Бюджет видалено",
      budgetRestored: "Бюджет відновлено",
      budgetThresholdsInvalid: "Поріг попередження має бути нижчим за небезпечний",
      appReady: "Web App готовий",
      drilldownApplied: "Фільтр застосовано",
      recurringCreated: "Регулярну операцію додано",
      recurringUpdated: "Регулярну операцію оновлено",
      recurringConfirmed: "Регулярну операцію підтверджено",
      selectCategory: "Спочатку оберіть категорію",
      nonNegativeLimit: "Ліміт має бути невід'ємним",
      setPeriodFirst: "Спочатку задайте період бюджету",
      periodRequired: "Потрібно заповнити період дат",
      categoryRequired: "Категорія обов'язкова",
      dateRequired: "Дата обов'язкова",
      descriptionRequired: "Опис обов'язковий",
      amountPositive: "Сума має бути більшою за нуль",
      typeIncomeExpense: "Тип має бути income або expense",
      initFailed: "Не вдалося ініціалізувати застосунок",
    },
    chart: {
      income: "Дохід",
      expense: "Витрати",
      expenses: "Витрати",
      sharePercent: "Частка %",
      spent: "Витрачено",
      remaining: "Залишок",
    },
  },
};

class I18nService {
  constructor(stateRef, dictionary, fallbackLanguage = "en") {
    this.state = stateRef;
    this.dictionary = dictionary;
    this.fallbackLanguage = fallbackLanguage;
  }

  currentLanguage() {
    const language = (
      (this.state.settings && this.state.settings.interface_language) ||
      (this.state.bootstrap && this.state.bootstrap.user && this.state.bootstrap.user.language) ||
      "uk"
    ).toLowerCase();
    return this.dictionary[language] ? language : this.fallbackLanguage;
  }

  lookup(dictionary, key) {
    return key.split(".").reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), dictionary);
  }

  translate(key) {
    const lang = this.currentLanguage();
    const localized = this.lookup(this.dictionary[lang], key);
    if (localized !== undefined) return localized;

    const fallback = this.lookup(this.dictionary[this.fallbackLanguage], key);
    if (fallback !== undefined) return fallback;
    return key;
  }

  applyToDom() {
    const language = this.currentLanguage();
    document.documentElement.lang = language;

    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.dataset.i18n;
      if (!key) return;
      node.textContent = this.translate(key);
    });

    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      const key = node.dataset.i18nPlaceholder;
      if (!key || !("placeholder" in node)) return;
      node.placeholder = this.translate(key);
    });

    updateAnalyticsHint();
  }
}

class ApiClient {
  constructor(stateRef) {
    this.state = stateRef;
  }

  parseApiError(payload) {
    if (!payload) return "Request failed";
    if (typeof payload === "string") return payload;
    if (payload.detail) {
      if (typeof payload.detail === "string") return payload.detail;
      if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg || String(item)).join("; ");
    }
    return "Request failed";
  }

  async request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (this.state.initData) {
      headers.set("X-Telegram-Init-Data", this.state.initData);
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
      throw new Error(this.parseApiError(payload));
    }

    return response;
  }

  async json(path, options = {}) {
    const response = await this.request(path, options);
    return response.json();
  }

  async blob(path, options = {}) {
    const response = await this.request(path, options);
    const blob = await response.blob();
    return { blob, response };
  }
}

const i18nService = new I18nService(state, I18N);
const apiClient = new ApiClient(state);

function currentLanguage() {
  return i18nService.currentLanguage();
}

function lookupTranslation(dictionary, key) {
  return i18nService.lookup(dictionary, key);
}

function t(key) {
  return i18nService.translate(key);
}

function applyTranslationsToDom() {
  i18nService.applyToDom();
}

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

function showToastWithAction(text, actionLabel, actionCallback, isError = false, timeoutMs = 5000) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = "";
  toast.style.borderColor = isError ? "rgba(255, 107, 107, 0.5)" : "rgba(45, 212, 191, 0.45)";
  const textNode = document.createElement("span");
  textNode.textContent = text;
  toast.appendChild(textNode);

  const btn = document.createElement("button");
  btn.className = "ghost-btn";
  btn.style.marginLeft = "12px";
  btn.textContent = actionLabel;
  btn.onclick = async (e) => {
    e.stopPropagation();
    try {
      await actionCallback();
    } catch (err) {
      console.error(err);
    }
    toast.classList.remove("show");
  };
  toast.appendChild(btn);

  toast.classList.add("show");
  window.setTimeout(() => {
    toast.classList.remove("show");
  }, timeoutMs);
}

function parseApiError(payload) {
  return apiClient.parseApiError(payload);
}

async function request(path, options = {}) {
  return apiClient.request(path, options);
}

async function apiJson(path, options = {}) {
  return apiClient.json(path, options);
}

async function apiBlob(path, options = {}) {
  return apiClient.blob(path, options);
}

App.state = state;
App.services = {
  i18n: i18nService,
  api: apiClient,
};
App.actions = App.actions || {};
App.listeners = App.listeners || {};
App.utils = {
  t,
  showToast,
};
App.runtime = App.runtime || {};

if (!Object.getOwnPropertyDescriptor(App.runtime, "queryDebounceTimer")) {
  Object.defineProperty(App.runtime, "queryDebounceTimer", {
    get() {
      return queryDebounceTimer;
    },
    set(value) {
      queryDebounceTimer = value;
    },
    configurable: true,
  });
}


