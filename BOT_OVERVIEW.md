# Bot Overview

## 1. Общая архитектура

Проект состоит из трёх основных сервисов в `docker-compose.yml`:

- `db`
  - PostgreSQL 16 на `postgres:16-alpine`
  - хранилище данных для бота и веб-приложения
  - подключается через переменные окружения из `.env`

- `finance-bot`
  - основной Telegram-бот
  - запускается из `app/bot.py`
  - использует библиотеку `aiogram` для polling и обработки сообщений
  - подключается к базе данных через SQLAlchemy Async
  - выполняет фоновые задачи: автопост рекуррентных записей и напоминаний

- `finance-web`
  - FastAPI веб-приложение
  - запускается командой `python -m app.web_main`
  - обслуживает UI `webapp` и API под путём `/api/webapp/*`
  - доступно на `http://localhost:8000`

## 2. Что делает бот

### Основные функции Telegram-бота

- принимает текстовые сообщения и команды
- распознаёт быстрые расходы из строки
- обрабатывает чековые фото через OCR
- предлагает меню с кнопками в Telegram
- предоставляет ссылку на веб-приложение `webapp`
- сохраняет записи расходов/доходов в базу данных
- поддерживает рекурсивные записи и бюджетные планы
- отправляет уведомления о напоминаниях для рекуррентных расходов

### Ключевые файлы

- `app/bot.py`
  - точка входа бота
  - создаёт `Bot` и `Dispatcher`
  - включает роутер `common.router`
  - удаляет webhook перед polling
  - запускает фоновые циклы:
    - `_run_recurring_autopost_loop`
    - `_run_recurring_reminders_loop`

- `app/handlers/common.py`
  - общие маршруты и контекст для бота
  - подключает датасессии, классификатор и OCR-сервис

- `app/handlers/routes_menu.py`
  - меню Telegram, команды `/start`, `/help`, `/convert`, `/language`
  - кнопки для операций, webapp, настроек и входов

- `app/handlers/routes_quick_expense.py`
  - быстрый ввод расхода по тексту
  - находит сумму и категорию в одном сообщении

- `app/handlers/routes_manual_add.py`
  - ручной ввод записи через Telegram

- `app/handlers/routes_ocr.py`
  - обработка фото чеков
  - скачивает файл, запускает OCR, парсит результаты
  - предлагает вариант сохранения как одну запись или по позициям

- `app/handlers/routes_reports.py`
  - отчёты, списки и бюджетные команды через Telegram

## 3. Что делает веб-приложение

### Навигация и UI

- `/webapp` — основной интерфейс
- статичные файлы находятся в `app/web/static/`
- frontend использует глобальный объект `App` и модули JS в `app/web/static/app/`

### API и маршруты

Веб-приложение предоставляет REST API для управления данными:

- `/api/webapp/bootstrap` — начальная загрузка данных
- `/api/webapp/categories` — список категорий
- `/api/webapp/dashboard` — данные для дашборда
- `/api/webapp/records` — список записей
- `/api/webapp/records/templates` — шаблоны
- `/api/webapp/records` POST/PATCH/DELETE — CRUD записи
- `/api/webapp/analytics` — аналитика
- `/api/webapp/budget` — данные бюджета
- `/api/webapp/budget/month` — сохранить план бюджета
- `/api/webapp/budget/category-limits` — лимиты по категориям
- `/api/webapp/budget/limit-series` — серии данных для графиков
- `/api/webapp/recurring` — список рекуррентных записей
- `/api/webapp/recurring` POST/PATCH/DELETE — CRUD рекуррентных записей
- `/api/webapp/settings` GET/PUT — пользовательские настройки
- `/api/webapp/export/csv` и `/api/webapp/export/pdf` — экспорт отчетов
- `/api/webapp/audit` — журнал аудита
- `/api/webapp/recommendations` — рекомендации
- `/api/webapp/health` — проверка здоровья

### Аутентификация веб-приложения

- `app/web/auth.py` содержит валидацию `init_data` от Telegram Web App
- `app/web/dependencies.py` извлекает пользователя по данным Telegram и связывает с базой
- веб-приложение работает через Telegram Web App токен/инициализацию

## 4. Какие технологии и зависимости использует бот

### Ядро

- Python 3.11+ (предположительно)
- `aiogram` — Telegram bot framework
- `FastAPI` — веб-сервер
- `uvicorn` — ASGI сервер
- `SQLAlchemy` async — ORM для PostgreSQL
- `asyncpg` / `psycopg` (вероятно) — драйвер Postgres

### OCR

- `pytesseract` — обёртка для Tesseract OCR
- `Pillow` — обработка изображений
- тesseract должен быть установлен в контейнере / системе

### База данных

- PostgreSQL 16
- схема создаётся через SQLAlchemy в `app/db.py`
- используется `Base.metadata.create_all` и `ensure_schema()`

### Контейнеризация

- `docker-compose.yml` связывает:
  - `db`
  - `finance-bot`
  - `finance-web`
- общая сеть `bot-network`
- volume `pgdata` для данных БД

## 5. Как данные движутся в системе

1. Пользователь пишет в Telegram или отправляет фото.
2. `finance-bot` обрабатывает сообщение через `aiogram`.
3. Бот сохраняет записи в PostgreSQL через SQLAlchemy.
4. Веб-приложение `finance-web` читает те же данные и отображает их в UI.
5. Web App использует Telegram Web App и `/api/webapp/*` для управления категориями, бюджетом, аналитикой.
6. Фоновые задачи бота запускают автопост рекуррентных расходов и уведомления.

## 6. Основной пользовательский поток

- В Telegram:
  - добавить расход/доход
  - отправить фото чека
  - управлять категориями
  - открыть веб-приложение

- В веб-приложении:
  - просматривать дашборд
  - смотреть аналитику
  - настраивать бюджет и лимиты
  - редактировать записи
  - экспортировать данные

## 7. Где искать точки расширения

- `app/handlers/` — логика Telegram-бота
- `app/services/` — OCR, классификация, бюджетные вычисления
- `app/web/routes/` — API для веб-интерфейса
- `app/web/static/app/` — клиентская JavaScript-логика
- `app/models.py` и `app/schemas.py` — модель данных и валидация

## 8. Полезные файлы

- `docker-compose.yml` — запуск всего стека
- `.env` — настройки окружения (токен бота, БД, URL)
- `app/bot.py` — бот и background tasks
- `app/web_main.py` — запуск веб-сервера
- `app/web/auth.py` — проверка Telegram Web App init_data
- `app/services/ocr_service.py` — OCR и распознавание чеков

---

Этот файл описывает, какие части использует бот, какие сервисы поднимает Docker, и какие API доступны в веб-приложении.