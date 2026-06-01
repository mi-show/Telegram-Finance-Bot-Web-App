UI_TEXTS = {
    "ru": {
        "menu_add_expense": "➕ Добавить расход",
        "menu_add_income": "➕ Добавить доход",
        "menu_list": "📋 Список",
        "menu_stats": "📈 Статистика",
        "menu_budget": "📑 Бюджет",
        "menu_receipt": "🖼 Чек (отправь фото)",
        "menu_webapp": "📱 Финансы Web App",
        "menu_language": "🌐 Язык",
        "menu_placeholder": "Нажми кнопку или пришли фото чека",
        "pick_language_intro": "Сначала выбери язык бота. От выбора зависит, какие словари категорий и ключевых слов используются.",
        "start_help": (
            "Привет! Я бот для учета личных финансов.\n\n"
            "Что умею:\n"
            "• Быстро записывать траты: просто напиши 'кофе 100'.\n"
            "• Если категория непонятна, попрошу выбрать вручную и запомню твой выбор.\n"
            "• Помогать с накоплениями и планом расходов через бюджет.\n"
            "• Распознавать чеки по фото и сохранять позиции.\n"
            "• Показывать аналитику за период в Web App.\n\n"
            "Нажми кнопку в меню ниже, чтобы начать."
        ),
        "language_pick_prompt": "Выбери язык:",
        "language_saved_toast": "Язык сохранен",
        "language_changed": "✅ Язык переключен на Русский.",
        "language_menu_updated": "Кнопки меню обновлены.",
        "error_data": "Ошибка данных.",
        "error_unsupported_lang": "Неподдерживаемый язык.",
        "error_save_lang": "Не удалось сохранить язык.",
        "hint_send_receipt": "Пришли фото чека — я распознаю сумму и предложу категорию.",
        "hint_open_webapp": "Открой Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL не настроен. Добавь переменную окружения WEBAPP_URL.",
        "hint_add_expense_example": "Пример:\n/add expense Coffee 10.00 {today} [описание]",
        "hint_add_income_example": "Пример:\n/add income Salary 1000 {today} [описание]",
        "hint_add_expense_menu": (
            "💸 Добавление расхода\n\n"
            "Напиши в чат в свободном виде, например: кофе 100\n"
            "Я попробую сам определить категорию.\n"
            "Если не пойму — предложу выбрать категорию вручную и запомню выбор.\n\n"
            "Также можно добавить расход в Web App: раздел Операции."
        ),
        "menu_income_kind_prompt": "💰 Добавление дохода\nЭто доход регулярный или разовый?",
        "menu_income_kind_regular_btn": "🔁 Регулярный",
        "menu_income_kind_one_time_btn": "1️⃣ Разовый",
        "menu_income_kind_selected_recurring": "🔁 Выбран регулярный доход.",
        "menu_income_kind_selected_onetime": "1️⃣ Выбран разовый доход.",
        "hint_add_income_recurring": (
            "Регулярный доход удобнее добавить в Web App в разделе Бюджет -> Регулярные платежи и доходы.\n"
            "Это же можно настроить в начале (onboarding)."
        ),
        "hint_add_income_onetime": (
            "Напиши сумму в чат, например: +1000\n"
            "Я сразу добавлю это как разовый доход.\n"
            "Также можно добавить в Web App в разделе Операции.\n"
            "Либо командой: /add income Salary 1000 {today} [описание]"
        ),
        "menu_income_onetime_amount_invalid": "Отправь сумму в формате +1000 или 1000.50.",
        "menu_income_onetime_added": "✅ Добавил разовый доход: {category} {amount} {currency} от {happened_on}",
        "list_count_prompt": "Сколько последних операций показать? Напиши число от 1 до {max_count}.",
        "list_count_invalid": "Нужно число от 1 до {max_count}. Попробуй еще раз.",
        "onboarding_income_prompt": "Отлично. Теперь отправь сумму ежемесячного дохода (только число, например 25000).",
        "onboarding_income_invalid": "Не понял сумму. Отправь только число больше 0, например 25000 или 1200.50.",
        "onboarding_currency_prompt": "Сначала выбери валюту:",
        "onboarding_currency_uah": "₴ Гривна (UAH)",
        "onboarding_currency_usd": "$ Доллар (USD)",
        "onboarding_currency_eur": "€ Евро (EUR)",
        "onboarding_currency_selected": "✅ Валюта выбрана: {currency}",
        "onboarding_income_offer_prompt": "💼 Добавить ежемесячный доход (зарплату) сейчас?",
        "onboarding_income_offer_add": "➕ Добавить зарплату",
        "onboarding_income_offer_skip": "⏭ Пропустить",
        "onboarding_income_offer_selected_add": "✅ Хорошо, добавим ежемесячный доход.",
        "onboarding_income_offer_selected_skip": "⏭ Пропущено. Доход можно добавить позже.",
        "onboarding_income_skipped_note": "Валюту сохранил. Доход можно добавить позже в Web App или через меню.",
        "onboarding_currency_saved_toast": "Доход и валюта сохранены",
        "onboarding_currency_stale": "Этот запрос устарел. Нажми /start, чтобы начать заново.",
        "onboarding_recurring_prompt": "Это регулярный доход (например зарплата), который добавить в раздел регулярных в Web App?",
        "onboarding_recurring_yes": "✅ Да, регулярно",
        "onboarding_recurring_no": "❌ Нет, разовый",
        "onboarding_recurring_skip": "⏭ Пропустить",
        "onboarding_recurring_selected_yes": "✅ Буду считать этот доход регулярным.",
        "onboarding_recurring_selected_no": "✅ Доход сохранен как разовый.",
        "onboarding_recurring_selected_skip": "⏭ Пропущено. Это можно настроить позже.",
        "onboarding_recurring_note_with": "Добавил доход в раздел регулярных платежей и доходов Web App.",
        "onboarding_recurring_note_without": "Регулярный доход можно добавить позже в разделе регулярных платежей и доходов Web App.",
        "onboarding_currency_saved": (
            "✅ Сохранил месячный доход: {amount} {currency}\n"
            "≈ {alt1_amount} {alt1_currency} | {alt2_amount} {alt2_currency}\n"
            "Курс обновляется автоматически."
        ),
        "convert_usage": "Формат: /convert <amount> <FROM> [TO]\nПримеры: /convert 1000 UAH USD или /convert 100 EUR",
        "convert_invalid": "Не понял запрос. Пример: /convert 1000 UAH USD",
        "convert_result": "💱 {amount} {from_currency} = {converted} {to_currency}\nКурс: 1 {from_currency} = {pair_rate} {to_currency}",
        "nav_prev": "⬅️ Назад",
        "nav_next": "➡️ Далее",
        "btn_spelling_yes": "✅ Да, написано правильно",
        "btn_spelling_no": "❌ Слово было написано неправильно",
        "btn_spelling_back": "↩️ Выбрать другую категорию",
        "btn_subcat_none": "Без подкатегории",
        "btn_subcat_back": "↩️ К категориям",
        "limit_suffix": " Лимит: {spent}/{limit} {currency} ({used_percent}%).",
        "recurring_reminder": "⏰ Напоминание: скоро платеж «{title}» на {amount} {currency}. Дата: {due_date}",
    },
    "uk": {
        "menu_add_expense": "➕ Додати витрату",
        "menu_add_income": "➕ Додати дохід",
        "menu_list": "📋 Список",
        "menu_stats": "📈 Статистика",
        "menu_budget": "📑 Бюджет",
        "menu_receipt": "🖼 Чек (надішли фото)",
        "menu_webapp": "📱 Фінанси Web App",
        "menu_language": "🌐 Мова",
        "menu_placeholder": "Натисни кнопку або надішли фото чека",
        "pick_language_intro": "Спочатку обери мову бота. Від цього залежить, які словники категорій і ключових слів використовуються.",
        "start_help": (
            "Привіт! Я бот для обліку особистих фінансів.\n\n"
            "Що вмію:\n"
            "• Швидко записувати витрати: просто напиши 'кава 100'.\n"
            "• Якщо категорія неочевидна, попрошу обрати вручну і запам'ятаю твій вибір.\n"
            "• Допомагати з накопиченнями та планом витрат через бюджет.\n"
            "• Розпізнавати чеки з фото та зберігати позиції.\n"
            "• Показувати аналітику за період у Web App.\n\n"
            "Натисни кнопку в меню нижче, щоб почати."
        ),
        "language_pick_prompt": "Обери мову:",
        "language_saved_toast": "Мову збережено",
        "language_changed": "✅ Мову змінено на Українську.",
        "language_menu_updated": "Кнопки меню оновлено.",
        "error_data": "Помилка даних.",
        "error_unsupported_lang": "Непідтримувана мова.",
        "error_save_lang": "Не вдалося зберегти мову.",
        "hint_send_receipt": "Надішли фото чека — я розпізнаю суму та запропоную категорію.",
        "hint_open_webapp": "Відкрий Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL не налаштовано. Додай змінну оточення WEBAPP_URL.",
        "hint_add_expense_example": "Приклад:\n/add expense Coffee 10.00 {today} [опис]",
        "hint_add_income_example": "Приклад:\n/add income Salary 1000 {today} [опис]",
        "hint_add_expense_menu": (
            "💸 Додавання витрати\n\n"
            "Напиши у чат у довільному вигляді, наприклад: кава 100\n"
            "Я спробую сам визначити категорію.\n"
            "Якщо не зрозумію — запропоную обрати категорію вручну та запам'ятаю вибір.\n\n"
            "Також можна додати витрату у Web App: розділ Операції."
        ),
        "menu_income_kind_prompt": "💰 Додавання доходу\nЦе дохід регулярний чи разовий?",
        "menu_income_kind_regular_btn": "🔁 Регулярний",
        "menu_income_kind_one_time_btn": "1️⃣ Разовий",
        "menu_income_kind_selected_recurring": "🔁 Обрано регулярний дохід.",
        "menu_income_kind_selected_onetime": "1️⃣ Обрано разовий дохід.",
        "hint_add_income_recurring": (
            "Регулярний дохід зручніше додати у Web App у розділі Бюджет -> Регулярні платежі та доходи.\n"
            "Це ж саме можна налаштувати на старті (onboarding)."
        ),
        "hint_add_income_onetime": (
            "Надішли суму у чат, наприклад: +1000\n"
            "Я одразу додам це як разовий дохід.\n"
            "Також можна додати у Web App у розділі Операції.\n"
            "Або командою: /add income Salary 1000 {today} [опис]"
        ),
        "menu_income_onetime_amount_invalid": "Надішли суму у форматі +1000 або 1000.50.",
        "menu_income_onetime_added": "✅ Додав разовий дохід: {category} {amount} {currency} від {happened_on}",
        "list_count_prompt": "Скільки останніх операцій показати? Надішли число від 1 до {max_count}.",
        "list_count_invalid": "Потрібне число від 1 до {max_count}. Спробуй ще раз.",
        "onboarding_income_prompt": "Чудово. Тепер надішли суму щомісячного доходу (лише число, наприклад 25000).",
        "onboarding_income_invalid": "Не вдалося розпізнати суму. Надішли лише число більше 0, наприклад 25000 або 1200.50.",
        "onboarding_currency_prompt": "Спочатку обери валюту:",
        "onboarding_currency_uah": "₴ Гривня (UAH)",
        "onboarding_currency_usd": "$ Долар (USD)",
        "onboarding_currency_eur": "€ Євро (EUR)",
        "onboarding_currency_selected": "✅ Валюту обрано: {currency}",
        "onboarding_income_offer_prompt": "💼 Додати щомісячний дохід (зарплату) зараз?",
        "onboarding_income_offer_add": "➕ Додати зарплату",
        "onboarding_income_offer_skip": "⏭ Пропустити",
        "onboarding_income_offer_selected_add": "✅ Добре, додаємо щомісячний дохід.",
        "onboarding_income_offer_selected_skip": "⏭ Пропущено. Дохід можна додати пізніше.",
        "onboarding_income_skipped_note": "Валюту збережено. Дохід можна додати пізніше у Web App або через меню.",
        "onboarding_currency_saved_toast": "Дохід і валюту збережено",
        "onboarding_currency_stale": "Цей запит застарів. Натисни /start, щоб почати заново.",
        "onboarding_recurring_prompt": "Це регулярний дохід (наприклад зарплата), який додати в розділ регулярних у Web App?",
        "onboarding_recurring_yes": "✅ Так, регулярно",
        "onboarding_recurring_no": "❌ Ні, разовий",
        "onboarding_recurring_skip": "⏭ Пропустити",
        "onboarding_recurring_selected_yes": "✅ Буду вважати цей дохід регулярним.",
        "onboarding_recurring_selected_no": "✅ Дохід збережено як разовий.",
        "onboarding_recurring_selected_skip": "⏭ Пропущено. Це можна налаштувати пізніше.",
        "onboarding_recurring_note_with": "Додав дохід у розділ регулярних платежів і доходів Web App.",
        "onboarding_recurring_note_without": "Регулярний дохід можна додати пізніше в розділі регулярних платежів і доходів Web App.",
        "onboarding_currency_saved": (
            "✅ Зберіг щомісячний дохід: {amount} {currency}\n"
            "≈ {alt1_amount} {alt1_currency} | {alt2_amount} {alt2_currency}\n"
            "Курс оновлюється автоматично."
        ),
        "convert_usage": "Формат: /convert <amount> <FROM> [TO]\nПриклади: /convert 1000 UAH USD або /convert 100 EUR",
        "convert_invalid": "Не вдалося розпізнати запит. Приклад: /convert 1000 UAH USD",
        "convert_result": "💱 {amount} {from_currency} = {converted} {to_currency}\nКурс: 1 {from_currency} = {pair_rate} {to_currency}",
        "nav_prev": "⬅️ Назад",
        "nav_next": "➡️ Далі",
        "btn_spelling_yes": "✅ Так, написано правильно",
        "btn_spelling_no": "❌ Слово написано неправильно",
        "btn_spelling_back": "↩️ Обрати іншу категорію",
        "btn_subcat_none": "Без підкатегорії",
        "btn_subcat_back": "↩️ До категорій",
        "limit_suffix": " Ліміт: {spent}/{limit} {currency} ({used_percent}%).",
        "recurring_reminder": "⏰ Нагадування: скоро платіж «{title}» на {amount} {currency}. Дата: {due_date}",
    },
    "en": {
        "menu_add_expense": "➕ Add Expense",
        "menu_add_income": "➕ Add Income",
        "menu_list": "📋 List",
        "menu_stats": "📈 Stats",
        "menu_budget": "📑 Budget",
        "menu_receipt": "🖼 Receipt (send photo)",
        "menu_webapp": "📱 Finance Web App",
        "menu_language": "🌐 Language",
        "menu_placeholder": "Tap a button or send a receipt photo",
        "pick_language_intro": "First choose the bot language. It affects which category and keyword dictionaries are used.",
        "start_help": (
            "Hi! I am your personal finance bot.\n\n"
            "What I can do:\n"
            "• Quickly save expenses from text: just type 'coffee 100'.\n"
            "• If category is unclear, I ask you once and remember your choice.\n"
            "• Help with savings and spending plans via budget tracking.\n"
            "• Parse receipt photos and save recognized items.\n"
            "• Show period analytics in the Web App.\n\n"
            "Tap a button in the menu below to start."
        ),
        "language_pick_prompt": "Choose a language:",
        "language_saved_toast": "Language saved",
        "language_changed": "✅ Language switched to English.",
        "language_menu_updated": "Menu buttons have been updated.",
        "error_data": "Invalid data.",
        "error_unsupported_lang": "Unsupported language.",
        "error_save_lang": "Failed to save language.",
        "hint_send_receipt": "Send a receipt photo and I will detect amount and category.",
        "hint_open_webapp": "Open Web App: {url}",
        "hint_webapp_unavailable": "WEBAPP_URL is not configured. Set WEBAPP_URL in environment.",
        "hint_add_expense_example": "Example:\n/add expense Coffee 10.00 {today} [note]",
        "hint_add_income_example": "Example:\n/add income Salary 1000 {today} [note]",
        "hint_add_expense_menu": (
            "💸 Adding an expense\n\n"
            "Type a freeform message, for example: coffee 100\n"
            "I will try to detect the category automatically.\n"
            "If I cannot, I will ask you to pick a category manually and remember it.\n\n"
            "You can also add an expense in Web App: Operations section."
        ),
        "menu_income_kind_prompt": "💰 Adding income\nIs this income recurring or one-time?",
        "menu_income_kind_regular_btn": "🔁 Recurring",
        "menu_income_kind_one_time_btn": "1️⃣ One-time",
        "menu_income_kind_selected_recurring": "🔁 Recurring income selected.",
        "menu_income_kind_selected_onetime": "1️⃣ One-time income selected.",
        "hint_add_income_recurring": (
            "Recurring income is best added in Web App: Budget -> Recurring payments and income.\n"
            "You can also configure this during onboarding."
        ),
        "hint_add_income_onetime": (
            "Send an amount in chat, for example: +1000\n"
            "I will add it immediately as one-time income.\n"
            "You can also add it in Web App: Operations section.\n"
            "Or via command: /add income Salary 1000 {today} [note]"
        ),
        "menu_income_onetime_amount_invalid": "Send amount in format +1000 or 1000.50.",
        "menu_income_onetime_added": "✅ Added one-time income: {category} {amount} {currency} on {happened_on}",
        "list_count_prompt": "How many latest operations should I show? Send a number from 1 to {max_count}.",
        "list_count_invalid": "Please send a number from 1 to {max_count}.",
        "onboarding_income_prompt": "Great. Now send your monthly income amount (number only, for example 25000).",
        "onboarding_income_invalid": "I could not parse the amount. Send a number greater than 0, for example 25000 or 1200.50.",
        "onboarding_currency_prompt": "Choose your currency first:",
        "onboarding_currency_uah": "₴ Hryvnia (UAH)",
        "onboarding_currency_usd": "$ US Dollar (USD)",
        "onboarding_currency_eur": "€ Euro (EUR)",
        "onboarding_currency_selected": "✅ Currency selected: {currency}",
        "onboarding_income_offer_prompt": "💼 Add monthly income (salary) now?",
        "onboarding_income_offer_add": "➕ Add salary",
        "onboarding_income_offer_skip": "⏭ Skip",
        "onboarding_income_offer_selected_add": "✅ Great, let us add monthly income.",
        "onboarding_income_offer_selected_skip": "⏭ Skipped. You can add income later.",
        "onboarding_income_skipped_note": "Currency saved. You can add income later in Web App or from the menu.",
        "onboarding_currency_saved_toast": "Income and currency saved",
        "onboarding_currency_stale": "This request is stale. Tap /start to begin again.",
        "onboarding_recurring_prompt": "Is this a recurring income (for example salary) that should be added to Recurring in Web App?",
        "onboarding_recurring_yes": "✅ Yes, recurring",
        "onboarding_recurring_no": "❌ No, one-time",
        "onboarding_recurring_skip": "⏭ Skip",
        "onboarding_recurring_selected_yes": "✅ This income will be treated as recurring.",
        "onboarding_recurring_selected_no": "✅ Income saved as one-time.",
        "onboarding_recurring_selected_skip": "⏭ Skipped. You can configure it later.",
        "onboarding_recurring_note_with": "Added income to Recurring items in Web App.",
        "onboarding_recurring_note_without": "You can add recurring income later in Web App Recurring items.",
        "onboarding_currency_saved": (
            "✅ Saved monthly income: {amount} {currency}\n"
            "≈ {alt1_amount} {alt1_currency} | {alt2_amount} {alt2_currency}\n"
            "Rates are refreshed automatically."
        ),
        "convert_usage": "Format: /convert <amount> <FROM> [TO]\nExamples: /convert 1000 UAH USD or /convert 100 EUR",
        "convert_invalid": "I could not parse your request. Example: /convert 1000 UAH USD",
        "convert_result": "💱 {amount} {from_currency} = {converted} {to_currency}\nRate: 1 {from_currency} = {pair_rate} {to_currency}",
        "nav_prev": "⬅️ Back",
        "nav_next": "➡️ Next",
        "btn_spelling_yes": "✅ Yes, this spelling is correct",
        "btn_spelling_no": "❌ The word was misspelled",
        "btn_spelling_back": "↩️ Choose another category",
        "btn_subcat_none": "No subcategory",
        "btn_subcat_back": "↩️ Back to categories",
        "limit_suffix": " Limit: {spent}/{limit} {currency} ({used_percent}%).",
        "recurring_reminder": "⏰ Reminder: upcoming payment \"{title}\" for {amount} {currency}. Due: {due_date}",
    },
}
