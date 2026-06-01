from __future__ import annotations

import pytest

from app.handlers.common import format_limit_status


@pytest.mark.asyncio
async def test_format_limit_status_includes_used_limit_remaining_and_recommendation(monkeypatch):
    async def fake_budget_snapshot(session, telegram_id, user_id, period_start, period_end, language):
        return {
            "category_limits": [
                {
                    "category": "Food & Drinks",
                    "subcategory": None,
                    "limit": 10000,
                    "spent": 2000,
                    "used_percent": 20,
                    "recommended_daily_spend": 300,
                }
            ]
        }

    monkeypatch.setattr("app.handlers.common._budget_snapshot", fake_budget_snapshot)

    suffix = await format_limit_status(
        session=None,
        telegram_id=1,
        user_id=1,
        category="Food & Drinks",
        subcategory=None,
        lang="en",
        currency="UAH",
    )

    assert "2000/10000" in suffix
    assert "20" in suffix
    assert "300" in suffix
    assert "Remaining" in suffix
