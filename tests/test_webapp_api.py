import asyncio
import importlib
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.handlers.common import _resolve_user_currency, _save_start_currency
from app.models import Record, RecordType, User, UserSettings
from app.repositories.users import UserRepository
from app.services.aggregation_service import AggregationService, clear_stats_cache
from app.services.category_service import localize_category, localize_subcategory
from app.services.record_service import RecordService
from app.schemas import RecordCreate, RecordFilter
from app.web.app import app, _db_session, _get_auth_user
from app.web.auth import TelegramWebUser

TEST_TELEGRAM_ID = 915551234
webapp_module = importlib.import_module("app.web.app")


async def _prepare_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _seed_records(session_factory: async_sessionmaker[AsyncSession]) -> None:
    today = date.today()
    async with session_factory() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_or_create(TEST_TELEGRAM_ID, language="uk")

        session.add_all(
            [
                Record(
                    user_id=user.id,
                    type=RecordType.EXPENSE,
                    category="Groceries",
                    subcategory="Supermarket",
                    amount=Decimal("250.00"),
                    currency="UAH",
                    happened_on=today,
                    description="Weekly basket",
                ),
                Record(
                    user_id=user.id,
                    type=RecordType.EXPENSE,
                    category="Transport",
                    subcategory="Taxi",
                    amount=Decimal("120.50"),
                    currency="UAH",
                    happened_on=today - timedelta(days=1),
                    description="Airport ride",
                ),
                Record(
                    user_id=user.id,
                    type=RecordType.INCOME,
                    category="Salary",
                    subcategory="Main",
                    amount=Decimal("5000.00"),
                    currency="UAH",
                    happened_on=today - timedelta(days=2),
                    description="Monthly salary",
                ),
                Record(
                    user_id=user.id,
                    type=RecordType.EXPENSE,
                    category="Food & Drinks",
                    subcategory="Groceries",
                    amount=Decimal("75.00"),
                    currency="UAH",
                    happened_on=today - timedelta(days=3),
                    description="Localized category sample",
                ),
            ]
        )
        await session.commit()


async def _fetch_user_settings_snapshot(engine, telegram_id: int) -> dict[str, str | None]:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        user = (
            await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
        ).scalars().first()
        if user is None:
            return {
                "user_language": None,
                "settings_language": None,
                "settings_currency": None,
            }

        settings_row = (
            await session.execute(
                select(UserSettings).where(UserSettings.user_id == user.id)
            )
        ).scalars().first()
        return {
            "user_language": user.language,
            "settings_language": settings_row.interface_language if settings_row else None,
            "settings_currency": settings_row.currency if settings_row else None,
        }


async def _fetch_repo_language(engine, telegram_id: int) -> str:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        user_repo = UserRepository(session)
        return await user_repo.get_language(telegram_id)


async def _bot_save_start_currency(engine, telegram_id: int, lang: str, currency: str) -> None:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        await _save_start_currency(session, telegram_id=telegram_id, lang=lang, currency=currency)
        await session.commit()


async def _bot_resolve_currency(engine, telegram_id: int) -> str:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        return await _resolve_user_currency(session, telegram_id)


async def _bot_add_record_with_settings_currency(engine, telegram_id: int) -> Record:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        currency = await _resolve_user_currency(session, telegram_id)
        service = RecordService(session, telegram_id)
        record = await service.add(
            RecordCreate(
                type="expense",
                category="Transport",
                subcategory="Taxi",
                amount=Decimal("777.77"),
                currency=currency,
                happened_on=date.today(),
                description="Bot-Web-Bot sync currency check",
            )
        )
        await session.commit()
        return record


async def _mutate_totals_result_and_refetch(engine, telegram_id: int) -> tuple[Decimal, Decimal]:
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        agg = AggregationService(session, telegram_id)
        today = date.today()
        filters = RecordFilter(date_from=today - timedelta(days=29), date_to=today)

        first = await agg.totals(filters)
        first["incomes"] = Decimal(first["incomes"]) + Decimal("777.77")

        second = await agg.totals(filters)
        return Decimal(first["incomes"]), Decimal(second["incomes"])


@pytest.fixture()
def webapp_client(tmp_path):
    db_file = tmp_path / "webapp_api_test.sqlite3"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}", future=True)
    test_session_factory = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    asyncio.run(_prepare_schema(test_engine))
    asyncio.run(_seed_records(test_session_factory))

    async def override_db_session():
        async with test_session_factory() as session:
            yield session

    async def override_auth_user():
        return TelegramWebUser(
            telegram_id=TEST_TELEGRAM_ID,
            first_name="API",
            last_name="Test",
            username="api_test",
            language_code="uk",
        )

    async def _noop_ensure_schema():
        return None

    original_engine = getattr(webapp_module, "engine")
    original_ensure_schema = getattr(webapp_module, "ensure_schema")

    setattr(webapp_module, "engine", test_engine)
    setattr(webapp_module, "ensure_schema", _noop_ensure_schema)
    app.dependency_overrides[_db_session] = override_db_session
    app.dependency_overrides[_get_auth_user] = override_auth_user

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(_db_session, None)
    app.dependency_overrides.pop(_get_auth_user, None)
    setattr(webapp_module, "engine", original_engine)
    setattr(webapp_module, "ensure_schema", original_ensure_schema)
    asyncio.run(test_engine.dispose())


def _current_month_bounds() -> tuple[date, date]:
    start = date.today().replace(day=1)
    if start.month == 12:
        end = date(start.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    return start, end


def test_webapp_dashboard_returns_expected_structure(webapp_client: TestClient):
    response = webapp_client.get("/api/webapp/dashboard?period=30d")
    assert response.status_code == 200

    payload = response.json()
    assert payload["period"]["from"]
    assert payload["period"]["to"]
    assert payload["totals"]["expenses"] > 0
    assert payload["totals"]["incomes"] > 0
    assert isinstance(payload["recent_operations"], list)
    assert len(payload["recent_operations"]) >= 2


def test_webapp_records_templates_create_and_audit(webapp_client: TestClient):
    templates_response = webapp_client.get("/api/webapp/records/templates?limit=5")
    assert templates_response.status_code == 200
    assert len(templates_response.json()["items"]) > 0

    create_response = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": "Groceries",
            "subcategory": "Bakery",
            "amount": 88.5,
            "currency": "uah",
            "happened_on": date.today().isoformat(),
            "description": "Created from web test",
        },
    )
    assert create_response.status_code == 200
    created_item = create_response.json()["item"]
    assert created_item["type"] == "expense"
    assert created_item["amount"] == 88.5
    assert created_item["currency"] == "UAH"

    audit_response = webapp_client.get("/api/webapp/audit?limit=20&offset=0")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    audit_items = audit_payload["items"]
    assert "record.create" in audit_payload["available_actions"]
    assert any(item["action"] == "record.create" and item["entity_id"] == created_item["id"] for item in audit_items)

    action_filter_response = webapp_client.get("/api/webapp/audit", params={"action": "record.create", "limit": 20})
    assert action_filter_response.status_code == 200
    action_filter_payload = action_filter_response.json()
    assert action_filter_payload["filters"]["action"] == "record.create"
    assert all(item["action"] == "record.create" for item in action_filter_payload["items"])

    today_iso = date.today().isoformat()
    date_filter_response = webapp_client.get(
        "/api/webapp/audit",
        params={"date_from": today_iso, "date_to": today_iso, "limit": 20},
    )
    assert date_filter_response.status_code == 200
    date_filter_payload = date_filter_response.json()
    assert date_filter_payload["filters"]["date_from"] == today_iso
    assert date_filter_payload["filters"]["date_to"] == today_iso


def test_webapp_audit_rejects_invalid_date_range(webapp_client: TestClient):
    today = date.today()
    response = webapp_client.get(
        "/api/webapp/audit",
        params={
            "date_from": (today + timedelta(days=1)).isoformat(),
            "date_to": today.isoformat(),
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "date_from must be <= date_to"


def test_webapp_records_support_update_and_delete(webapp_client: TestClient):
    response = webapp_client.get("/api/webapp/records?limit=5&offset=0&type=expense")
    assert response.status_code == 200

    records_payload = response.json()
    assert records_payload["paging"]["total"] >= 2

    target_id = records_payload["items"][0]["id"]
    patch_response = webapp_client.patch(
        f"/api/webapp/records/{target_id}",
        json={
            "type": "expense",
            "category": "Updated Category",
            "subcategory": "Updated Subcategory",
            "amount": 99.99,
            "currency": "UAH",
            "happened_on": date.today().isoformat(),
            "description": "Updated via API test",
        },
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["item"]["category"] == "Updated Category"

    delete_response = webapp_client.delete(f"/api/webapp/records/{target_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True

    missing_response = webapp_client.delete(f"/api/webapp/records/{target_id}")
    assert missing_response.status_code == 404


def test_webapp_budget_settings_and_export_endpoints(webapp_client: TestClient):
    start, end = _current_month_bounds()

    budget_response = webapp_client.put(
        "/api/webapp/budget/month",
        json={
            "planned_expense": 1000,
            "planned_income": 6000,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
    )
    assert budget_response.status_code == 200
    assert budget_response.json()["planned_expense"] == 1000.0

    limits_response = webapp_client.put(
        "/api/webapp/budget/category-limits",
        json={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "limit_alert_mode": "threshold_50",
            "limits": [
                {"category": "Groceries", "limit_amount": 400},
            ],
        },
    )
    assert limits_response.status_code == 200
    limits_payload = limits_response.json()
    assert len(limits_payload["category_limits"]) == 1
    limit_item = limits_payload["category_limits"][0]
    assert "forecast" in limit_item
    assert "forecast_used_percent" in limit_item
    assert "forecast_status" in limit_item
    assert "forecast_alerts" in limits_payload
    assert limits_payload["limit_alert_mode"] == "threshold_50"
    assert limits_payload["limit_alert_threshold_percent"] == 50.0

    custom_limits_response = webapp_client.put(
        "/api/webapp/budget/category-limits",
        json={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "limit_alert_mode": "threshold_65",
            "limits": [
                {"category": "Groceries", "limit_amount": 400},
            ],
        },
    )
    assert custom_limits_response.status_code == 200
    custom_limits_payload = custom_limits_response.json()
    assert custom_limits_payload["limit_alert_mode"] == "threshold_65"
    assert custom_limits_payload["limit_alert_threshold_percent"] == 65.0

    get_budget_response = webapp_client.get(f"/api/webapp/budget?year={start.year}&month={start.month}")
    assert get_budget_response.status_code == 200
    get_budget_payload = get_budget_response.json()
    assert len(get_budget_payload["category_limits"]) == 1
    assert get_budget_payload["limit_alert_mode"] == "threshold_50"

    get_settings_response = webapp_client.get("/api/webapp/settings")
    assert get_settings_response.status_code == 200
    assert get_settings_response.json()["interface_language"] in {"uk", "ru", "en"}

    put_settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={
            "theme": "light",
            "currency": "EUR",
            "interface_language": "ru",
            "week_starts_on": "sunday",
            "notifications_enabled": False,
            "desktop_fullscreen_enabled": True,
            "hidden_blocks": ["dashboardPie"],
            "pinned_filters": ["this_month"],
            "favorite_categories": ["Groceries"],
            "budget_warning_percent": 75,
            "budget_danger_percent": 110,
        },
    )
    assert put_settings_response.status_code == 200
    saved_settings = put_settings_response.json()
    assert saved_settings["theme"] == "light"
    assert saved_settings["currency"] == "EUR"
    assert saved_settings["interface_language"] == "ru"
    assert saved_settings["desktop_fullscreen_enabled"] is True
    assert saved_settings["budget_warning_percent"] == 75
    assert saved_settings["budget_danger_percent"] == 110

    follow_up_settings_response = webapp_client.get("/api/webapp/settings")
    assert follow_up_settings_response.status_code == 200
    assert follow_up_settings_response.json()["interface_language"] == "ru"
    assert follow_up_settings_response.json()["budget_warning_percent"] == 75
    assert follow_up_settings_response.json()["budget_danger_percent"] == 110

    snapshot = asyncio.run(_fetch_user_settings_snapshot(webapp_module.engine, TEST_TELEGRAM_ID))
    assert snapshot["settings_currency"] == "EUR"
    assert snapshot["settings_language"] == "ru"
    assert snapshot["user_language"] == "ru"

    bot_repo_lang = asyncio.run(_fetch_repo_language(webapp_module.engine, TEST_TELEGRAM_ID))
    assert bot_repo_lang == "ru"

    audit_response = webapp_client.get("/api/webapp/audit?limit=30&offset=0")
    assert audit_response.status_code == 200
    actions = [item["action"] for item in audit_response.json()["items"]]
    assert "budget.month.update" in actions
    assert "budget.category_limits.update" in actions

    csv_response = webapp_client.get("/api/webapp/export/csv?type=expense")
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert "filename=finance-report.csv" in csv_response.headers.get("content-disposition", "")
    assert "id,date,type,category,subcategory,amount,currency,description" in csv_response.text

    pdf_response = webapp_client.get("/api/webapp/export/pdf?period=30d")
    assert pdf_response.status_code == 200
    assert "application/pdf" in pdf_response.headers["content-type"]
    assert pdf_response.content.startswith(b"%PDF")


def test_webapp_localization_and_alias_filters(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    categories_response = webapp_client.get("/api/webapp/categories")
    assert categories_response.status_code == 200
    categories_payload = categories_response.json()
    assert categories_payload["language"] == "ru"
    available_categories = [item["category"] for item in categories_payload["items"]]
    assert ru_food in available_categories

    records_response = webapp_client.get(
        "/api/webapp/records",
        params={"type": "expense", "categories": ru_food},
    )
    assert records_response.status_code == 200
    records_payload = records_response.json()
    assert any(item["category"] == ru_food for item in records_payload["items"])

    csv_response = webapp_client.get(
        "/api/webapp/export/csv",
        params={"type": "expense"},
    )
    assert csv_response.status_code == 200
    assert "Еда и напитки" in csv_response.text


def test_webapp_records_and_recent_operations_localize_subcategory(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    ru_groceries = localize_subcategory("Food & Drinks", "Groceries", "ru")
    assert ru_food
    assert ru_groceries

    records_response = webapp_client.get(
        "/api/webapp/records",
        params={"type": "expense", "categories": ru_food},
    )
    assert records_response.status_code == 200
    records_items = records_response.json()["items"]
    assert any(item["subcategory"] == ru_groceries for item in records_items)

    dashboard_response = webapp_client.get("/api/webapp/dashboard?period=30d")
    assert dashboard_response.status_code == 200
    recent_items = dashboard_response.json()["recent_operations"]
    assert any(
        item["category"] == ru_food and item["subcategory"] == ru_groceries
        for item in recent_items
    )


def test_webapp_budget_limits_merge_aliases_and_localize_category(webapp_client: TestClient):
    start, end = _current_month_bounds()

    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    limits_response = webapp_client.put(
        "/api/webapp/budget/category-limits",
        json={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "limits": [
                {"category": "Food & Drinks", "limit_amount": 100},
                {"category": ru_food, "limit_amount": 150},
            ],
        },
    )
    assert limits_response.status_code == 200

    payload = limits_response.json()
    category_limits = payload["category_limits"]
    assert len(category_limits) == 1
    assert category_limits[0]["category"] == ru_food
    assert category_limits[0]["limit"] == 250.0


def test_webapp_analytics_merges_localized_category_aliases(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_travel = localize_category("Travel", "ru")
    assert ru_travel

    today = date.today().isoformat()
    record_1 = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": "Travel",
            "subcategory": "Tickets",
            "amount": 120.0,
            "currency": "UAH",
            "happened_on": today,
            "description": "Travel expense alias 1",
        },
    )
    assert record_1.status_code == 200

    record_2 = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": ru_travel,
            "subcategory": "Tickets",
            "amount": 80.0,
            "currency": "UAH",
            "happened_on": today,
            "description": "Travel expense alias 2",
        },
    )
    assert record_2.status_code == 200

    analytics_response = webapp_client.get("/api/webapp/analytics?period=30d")
    assert analytics_response.status_code == 200
    distribution = analytics_response.json()["distribution"]
    travel_rows = [item for item in distribution if item["category"] == ru_travel]
    assert len(travel_rows) == 1
    assert travel_rows[0]["amount"] == 200.0


def test_webapp_analytics_month_preset_with_month_to_date_range_uses_full_month_budget(webapp_client: TestClient):
    today = date.today()
    month_start = today.replace(day=1)
    if month_start.month == 12:
        month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

    analytics_response = webapp_client.get(
        "/api/webapp/analytics",
        params={
            "period": "month",
            "date_from": month_start.isoformat(),
            "date_to": today.isoformat(),
        },
    )
    assert analytics_response.status_code == 200
    payload = analytics_response.json()
    assert payload["budget"]["period_start"] == month_start.isoformat()
    assert payload["budget"]["period_end"] == month_end.isoformat()


def test_webapp_budget_subcategory_limit_isolated_from_category_fallback(webapp_client: TestClient):
    start, end = _current_month_bounds()

    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "en"},
    )
    assert settings_response.status_code == 200

    limits_response = webapp_client.put(
        "/api/webapp/budget/category-limits",
        json={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "limits": [
                {"category": "Transport", "limit_amount": 300},
                {"category": "Transport", "subcategory": "Taxi", "limit_amount": 100},
            ],
        },
    )
    assert limits_response.status_code == 200

    category_limits = limits_response.json()["category_limits"]
    category_row = next(
        item
        for item in category_limits
        if item["category"] == "Transport" and item.get("subcategory") in {None, ""}
    )
    subcategory_row = next(
        item
        for item in category_limits
        if item["category"] == "Transport" and item.get("subcategory") == "Taxi"
    )

    assert subcategory_row["spent"] == 120.5
    assert category_row["spent"] == 0.0


def test_webapp_budget_limit_series_endpoint(webapp_client: TestClient):
    start, end = _current_month_bounds()

    response = webapp_client.post(
        "/api/webapp/budget/limit-series",
        json={
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "keys": [
                {"category": "Transport"},
                {"category": "Food & Drinks"},
            ],
        },
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["period_start"] == start.isoformat()
    assert payload["period_end"] == end.isoformat()
    assert len(payload["items"]) == 2
    first = payload["items"][0]
    assert len(first["days"]) == len(first["amounts"])
    assert first["canonical_category"]


def test_webapp_categories_invalid_language_falls_back_to_current_setting(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    categories_response = webapp_client.get(
        "/api/webapp/categories",
        params={"language": "zz"},
    )
    assert categories_response.status_code == 200

    payload = categories_response.json()
    assert payload["language"] == "ru"
    assert ru_food in [item["category"] for item in payload["items"]]


def test_webapp_records_filter_supports_mixed_language_aliases(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    records_response = webapp_client.get(
        "/api/webapp/records",
        params=[
            ("type", "expense"),
            ("categories", ru_food),
            ("categories", "Food & Drinks"),
        ],
    )
    assert records_response.status_code == 200

    items = records_response.json()["items"]
    assert len(items) == 1
    assert items[0]["category"] == ru_food


def test_webapp_settings_canonicalize_favorites_and_keep_language_on_invalid_update(webapp_client: TestClient):
    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    save_response = webapp_client.put(
        "/api/webapp/settings",
        json={
            "interface_language": "ru",
            "favorite_categories": ["Food & Drinks", ru_food],
        },
    )
    assert save_response.status_code == 200
    saved_payload = save_response.json()
    assert saved_payload["interface_language"] == "ru"
    assert saved_payload["favorite_categories"] == [ru_food]

    invalid_language_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "zz"},
    )
    assert invalid_language_response.status_code == 200
    assert invalid_language_response.json()["interface_language"] == "ru"

    english_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "en"},
    )
    assert english_response.status_code == 200
    assert english_response.json()["interface_language"] == "en"
    assert english_response.json()["favorite_categories"] == ["Food & Drinks"]


def test_webapp_dashboard_merges_mixed_language_category_aliases(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    records_response = webapp_client.get("/api/webapp/records", params={"type": "expense"})
    assert records_response.status_code == 200
    expense_items = records_response.json()["items"]
    transport_item = next(item for item in expense_items if item["description"] == "Airport ride")

    patch_response = webapp_client.patch(
        f"/api/webapp/records/{transport_item['id']}",
        json={"category": ru_food, "amount": 25.0},
    )
    assert patch_response.status_code == 200

    dashboard_response = webapp_client.get("/api/webapp/dashboard?period=30d")
    assert dashboard_response.status_code == 200
    categories = dashboard_response.json()["categories"]

    food_rows = [item for item in categories if item["category"] == ru_food]
    assert len(food_rows) == 1
    assert food_rows[0]["amount"] == 100.0


def test_webapp_analytics_merges_mixed_language_category_aliases(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_food = localize_category("Food & Drinks", "ru")
    assert ru_food

    records_response = webapp_client.get("/api/webapp/records", params={"type": "expense"})
    assert records_response.status_code == 200
    expense_items = records_response.json()["items"]
    transport_item = next(item for item in expense_items if item["description"] == "Airport ride")

    patch_response = webapp_client.patch(
        f"/api/webapp/records/{transport_item['id']}",
        json={"category": ru_food, "amount": 25.0},
    )
    assert patch_response.status_code == 200

    analytics_response = webapp_client.get("/api/webapp/analytics?period=30d")
    assert analytics_response.status_code == 200
    distribution = analytics_response.json()["distribution"]

    food_rows = [item for item in distribution if item["category"] == ru_food]
    assert len(food_rows) == 1
    assert food_rows[0]["amount"] == 100.0


def test_webapp_analytics_includes_budget_snapshot(webapp_client: TestClient):
    response = webapp_client.get("/api/webapp/analytics?period=30d")
    assert response.status_code == 200

    payload = response.json()
    assert "budget" in payload
    assert isinstance(payload["budget"], dict)
    assert "monthly_plan" in payload["budget"]
    assert "projection_context" in payload["budget"]
    assert "category_forecast" in payload
    assert "forecast_alerts" in payload
    assert "week_over_week" in payload
    assert "daily_volatility" in payload


def test_aggregation_totals_cache_is_immutable_for_callers(webapp_client: TestClient):
    clear_stats_cache()

    mutated_income, refetched_income = asyncio.run(
        _mutate_totals_result_and_refetch(webapp_module.engine, TEST_TELEGRAM_ID)
    )

    assert mutated_income != refetched_income


def test_webapp_analytics_merges_mixed_language_subcategory_aliases(webapp_client: TestClient):
    settings_response = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "ru"},
    )
    assert settings_response.status_code == 200

    ru_education = localize_category("Education", "ru")
    ru_courses = localize_subcategory("Education", "Courses", "ru")
    assert ru_education
    assert ru_courses

    create_english = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": "Education",
            "subcategory": "Courses",
            "amount": 11.0,
            "currency": "UAH",
            "happened_on": date.today().isoformat(),
            "description": "Education EN",
        },
    )
    assert create_english.status_code == 200

    create_russian = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": ru_education,
            "subcategory": ru_courses,
            "amount": 19.0,
            "currency": "UAH",
            "happened_on": date.today().isoformat(),
            "description": "Education RU",
        },
    )
    assert create_russian.status_code == 200

    analytics_response = webapp_client.get("/api/webapp/analytics?period=30d")
    assert analytics_response.status_code == 200

    subcategory_distribution = analytics_response.json()["subcategory_distribution"]
    education_bucket = next(item for item in subcategory_distribution if item["category"] == ru_education)
    course_rows = [item for item in education_bucket["subcategories"] if item["subcategory"] == ru_courses]

    assert len(course_rows) == 1
    assert course_rows[0]["amount"] == 30.0


def test_bot_web_bot_settings_sync_end_to_end(webapp_client: TestClient):
    # Simulate bot onboarding selecting language/currency before user opens webapp.
    asyncio.run(_bot_save_start_currency(webapp_module.engine, TEST_TELEGRAM_ID, lang="ru", currency="EUR"))

    initial_web_settings = webapp_client.get("/api/webapp/settings")
    assert initial_web_settings.status_code == 200
    assert initial_web_settings.json()["interface_language"] == "ru"
    assert initial_web_settings.json()["currency"] == "EUR"

    # Simulate user changing settings in webapp.
    updated_web_settings = webapp_client.put(
        "/api/webapp/settings",
        json={"interface_language": "en", "currency": "USD"},
    )
    assert updated_web_settings.status_code == 200
    assert updated_web_settings.json()["interface_language"] == "en"
    assert updated_web_settings.json()["currency"] == "USD"

    # Bot-side reads should now see the same language/currency.
    bot_language = asyncio.run(_fetch_repo_language(webapp_module.engine, TEST_TELEGRAM_ID))
    assert bot_language == "en"

    bot_currency = asyncio.run(_bot_resolve_currency(webapp_module.engine, TEST_TELEGRAM_ID))
    assert bot_currency == "USD"

    # Simulate bot creating record after web change: it must use synced currency.
    created_record = asyncio.run(_bot_add_record_with_settings_currency(webapp_module.engine, TEST_TELEGRAM_ID))
    assert created_record.currency == "USD"


def test_webapp_create_record_requires_description(webapp_client: TestClient):
    response = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "expense",
            "category": "Groceries",
            "amount": 15.0,
            "currency": "UAH",
            "happened_on": date.today().isoformat(),
            "description": "   ",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "description is required"


def test_webapp_recurring_create_and_confirm_flow(webapp_client: TestClient):
    recurring_title = "Auto Salary QA"
    create_response = webapp_client.post(
        "/api/webapp/recurring",
        json={
            "title": recurring_title,
            "type": "income",
            "category": "Salary",
            "subcategory": "Main",
            "amount": 2500,
            "currency": "UAH",
            "day_of_month": 1,
            "reminder_days_before": 2,
            "is_active": True,
        },
    )
    assert create_response.status_code == 200
    recurring_item = create_response.json()["item"]
    assert recurring_item["type"] == "income"
    assert recurring_item["title"] == recurring_title

    list_response = webapp_client.get("/api/webapp/recurring")
    assert list_response.status_code == 200
    synced_item = next(item for item in list_response.json()["items"] if item["id"] == recurring_item["id"])
    assert synced_item["confirmed_for_month"] is True

    auto_records_before = webapp_client.get(
        "/api/webapp/records",
        params={"type": "income", "query": recurring_title},
    )
    assert auto_records_before.status_code == 200
    assert auto_records_before.json()["paging"]["total"] == 1

    confirm_response = webapp_client.post(f"/api/webapp/recurring/{recurring_item['id']}/confirm")
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert "item" in confirm_payload

    auto_records_after = webapp_client.get(
        "/api/webapp/records",
        params={"type": "income", "query": recurring_title},
    )
    assert auto_records_after.status_code == 200
    assert auto_records_after.json()["paging"]["total"] == 1


def test_webapp_recurring_income_allows_omitting_category(webapp_client: TestClient):
    create_response = webapp_client.post(
        "/api/webapp/recurring",
        json={
            "title": "Salary",
            "type": "income",
            "amount": 3100,
            "currency": "UAH",
            "day_of_month": 10,
            "reminder_days_before": 1,
            "is_active": True,
        },
    )

    assert create_response.status_code == 200
    item = create_response.json()["item"]
    assert item["type"] == "income"
    assert item["category"] == "Salary"
    assert item["subcategory"] == "Main"


def test_webapp_dashboard_scales_only_recurring_income_and_adds_one_time_income(webapp_client: TestClient):
    # Seeded fixture already contains one regular income record: 5000.00 (this month).
    recurring_response = webapp_client.post(
        "/api/webapp/recurring",
        json={
            "title": "Monthly Salary Projection",
            "type": "income",
            "category": "Salary",
            "subcategory": "Main",
            "amount": 28000,
            "currency": "UAH",
            "day_of_month": 31,
            "reminder_days_before": 2,
            "is_active": True,
        },
    )
    assert recurring_response.status_code == 200

    one_time_income_response = webapp_client.post(
        "/api/webapp/records",
        json={
            "type": "income",
            "category": "Gift",
            "subcategory": "Bonus",
            "amount": 2000,
            "currency": "UAH",
            "happened_on": date.today().isoformat(),
            "description": "One-time bonus",
        },
    )
    assert one_time_income_response.status_code == 200

    dashboard_response = webapp_client.get("/api/webapp/dashboard?period=month")
    assert dashboard_response.status_code == 200
    incomes = float(dashboard_response.json()["totals"]["incomes"])

    # 5000 (seed one-time) + 2000 (new one-time) + 28000 (recurring month x1)
    assert incomes == pytest.approx(35000.0, abs=0.01)


def test_webapp_recurring_expense_requires_category(webapp_client: TestClient):
    create_response = webapp_client.post(
        "/api/webapp/recurring",
        json={
            "title": "Utilities",
            "type": "expense",
            "amount": 600,
            "currency": "UAH",
            "day_of_month": 5,
            "reminder_days_before": 2,
            "is_active": True,
        },
    )

    assert create_response.status_code == 400
    assert "category is required" in create_response.json()["detail"]


def test_webapp_settings_currency_change_converts_amounts(webapp_client: TestClient):
    before_dashboard = webapp_client.get("/api/webapp/dashboard?period=month")
    assert before_dashboard.status_code == 200
    before_expenses = float(before_dashboard.json()["totals"]["expenses"])
    assert before_expenses > 0

    update_settings = webapp_client.put(
        "/api/webapp/settings",
        json={"currency": "USD"},
    )
    assert update_settings.status_code == 200
    assert update_settings.json()["currency"] == "USD"

    records_response = webapp_client.get("/api/webapp/records?type=expense&limit=20")
    assert records_response.status_code == 200
    records_payload = records_response.json()["items"]
    assert records_payload
    assert all(item["currency"] == "USD" for item in records_payload)

    after_dashboard = webapp_client.get("/api/webapp/dashboard?period=month")
    assert after_dashboard.status_code == 200
    after_expenses = float(after_dashboard.json()["totals"]["expenses"])

    # Must be real conversion, not only symbol swap.
    assert after_expenses > 0
    assert after_expenses < before_expenses


def test_webapp_settings_currency_round_trip_preserves_original_amounts(webapp_client: TestClient):
    before_response = webapp_client.get("/api/webapp/records?type=expense&limit=50")
    assert before_response.status_code == 200
    before_items = before_response.json()["items"]
    assert before_items

    before_by_id = {item["id"]: float(item["amount"]) for item in before_items}

    to_usd = webapp_client.put(
        "/api/webapp/settings",
        json={"currency": "USD"},
    )
    assert to_usd.status_code == 200
    assert to_usd.json()["currency"] == "USD"

    back_to_uah = webapp_client.put(
        "/api/webapp/settings",
        json={"currency": "UAH"},
    )
    assert back_to_uah.status_code == 200
    assert back_to_uah.json()["currency"] == "UAH"

    after_response = webapp_client.get("/api/webapp/records?type=expense&limit=50")
    assert after_response.status_code == 200
    after_items = after_response.json()["items"]
    after_by_id = {item["id"]: float(item["amount"]) for item in after_items}

    assert set(after_by_id) == set(before_by_id)
    assert after_by_id == before_by_id
