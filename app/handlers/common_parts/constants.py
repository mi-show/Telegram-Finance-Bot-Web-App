from decimal import Decimal

QUICK_CATEGORY_PAGE_SIZE = 10
SUPPORTED_LANGUAGES = {"uk", "ru", "en"}
SUPPORTED_ONBOARDING_CURRENCIES = {"UAH", "USD", "EUR"}
SUPPORTED_CONVERSION_ORDER = ("UAH", "USD", "EUR")
CURRENCY_SCALE = Decimal("0.01")

ONBOARDING_INCOME_CATEGORY = "Salary"
ONBOARDING_INCOME_SUBCATEGORY = "Main"
ONBOARDING_INCOME_MARKER = "[onboarding-income]"
ONBOARDING_RECURRING_TITLES = {
    "ru": "Ежемесячный доход",
    "uk": "Щомісячний дохід",
    "en": "Monthly income",
}
ONBOARDING_RECURRING_TITLE_VARIANTS = tuple(ONBOARDING_RECURRING_TITLES.values())

FALLBACK_RATES_BY_USD = {
    "USD": Decimal("1.00"),
    "UAH": Decimal("40.00"),
    "EUR": Decimal("0.92"),
}
LIVE_FX_API_URL = "https://open.er-api.com/v6/latest/USD"

TELEGRAM_SAFE_TEXT_LIMIT = 3000
TELEGRAM_MIN_CHUNK_LIMIT = 256
