# Telegram Finance Bot + Web App

Languages: [English](README.md) | [Русский](README.ru.md) | [Українська](README.uk.md)

![Python](https://img.shields.io/badge/Python-3.11-blue) ![aiogram](https://img.shields.io/badge/aiogram-3.x-2c2c2c) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688) ![Docker](https://img.shields.io/badge/Docker-ready-2496ED)

> Async Telegram bot + Web App for personal finance tracking with OCR receipts, smart categorization, budgets, and analytics.

![Bot preview](content/бот.jpg)

## Why this project

This is a full-stack portfolio project that demonstrates production-grade Python skills:

- async Telegram UX (aiogram) with real user flows
- FastAPI + PostgreSQL API with SQLAlchemy async
- OCR pipeline + ML-assisted categorization
- Web App with charts, exports, and budgets
- Dockerized stack and automated tests

## Demo

- Video walkthrough: [content/видео_работы.MP4](content/видео_работы.MP4)

## Screenshots

| Dashboard | Operations | Analytics 1 |
| --- | --- | --- |
| ![Dashboard](content/дашборд.png) | ![Operations](content/операции.png) | ![Analytics 1](content/аналитка1.png) |

| Budget | OCR | Settings |
| --- | --- | --- |
| ![Budget](content/бюджет.png) | ![OCR](content/оср.png) | ![Settings](content/настройки.png) |

| Analytics 2 |
| --- |
| ![Analytics 2](content/аналитика2.png) |

## Highlights

- Telegram commands + quick expense input + OCR receipt flow with confirmation
- Smart categorization: user history -> fuzzy match -> global keywords -> TF-IDF model
- Budget planning, category limits, forecasts, and recurring payments
- Analytics dashboard with charts (Chart.js) and exports to CSV/PDF
- Multi-language UI: `uk`, `ru`, `en`
- Caching for heavy queries, async DB access
- OCR quality gates + regression corpus for parser quality

## Tech Stack

- Python 3.11, aiogram 3, FastAPI, SQLAlchemy async
- PostgreSQL (Docker), SQLite for local dev
- Tesseract OCR + Pillow, `pytesseract`
- ML: scikit-learn TF-IDF + rapidfuzz
- Web App: vanilla JS, Chart.js, Telegram Web App SDK
- Tests: pytest, pytest-asyncio, Playwright

## Architecture

```mermaid
flowchart LR
  subgraph Telegram
    U[User]
  end
  U -->|messages / photos| BOT[finance-bot (aiogram)]
  BOT -->|SQLAlchemy async| DB[(PostgreSQL)]
  BOT -->|OCR + parser| OCR[Tesseract + ReceiptParser]
  BOT -->|menu link| WEBAPP[Telegram Web App]

  WEBAPP -->|API /api/webapp/*| API[finance-web (FastAPI)]
  API --> DB
  WEBAPP -->|Charts & UI| UI[Web UI]
```

## Core flows

- Quick expense: "coffee 50" -> category suggestion -> save
- OCR receipts: photo -> OCR -> parse items/amount -> category -> confirm
- Web App: dashboard, operations, analytics, budget, recurring, settings
- Exports: CSV + PDF reports

## Quick Start

### Local (pip)

1. Create `.env` (copy from `.env.sample`) and set `BOT_TOKEN` and `DATABASE_URL`.
1. Install deps:

```bash
pip install -r requirements.txt
```

1. Run bot:

```bash
python -m app.bot
```

1. Run Web App API + UI:

```bash
python -m app.web_main
```

### Docker (full stack)

```bash
docker compose -p finance-bot up -d --build
```

### One-command dev + tunnel (Windows)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_bot_with_tunnel.ps1
```

This script:

- starts `db` and `finance-web`
- waits for `/api/webapp/health`
- creates a temporary localhost.run tunnel
- updates `WEBAPP_URL` in `.env`
- updates the Telegram menu button
- starts `finance-bot`

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

### E2E (Playwright)

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest tests/e2e/test_webapp_playwright.py -q
```

## Project structure

- `app/bot.py` Telegram bot entry
- `app/web_main.py` FastAPI Web App entry
- `app/services/` OCR, parsing, categorization, aggregation
- `app/handlers/` bot routes and workflows
- `app/web/` Web App backend + static UI
- `tests/` unit + e2e

## Docs

- Architecture overview: [BOT_OVERVIEW.md](BOT_OVERVIEW.md)
- Categorization improvements: [IMPROVEMENTS.md](IMPROVEMENTS.md)
- OCR quality targets: [OCR_QUALITY_TARGETS.md](OCR_QUALITY_TARGETS.md)

## Notes

- For production, use PostgreSQL and configure `WEBAPP_URL`.
- Tesseract binary must be installed on the host/container.
