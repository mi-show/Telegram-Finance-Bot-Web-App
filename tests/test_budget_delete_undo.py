import asyncio
from datetime import date

from fastapi.testclient import TestClient

from app.web.app import app, _db_session, _get_auth_user
from app.web.auth import TelegramWebUser


def test_budget_delete_and_undo(webapp_client: TestClient):
    # create a budget
    start = date.today().replace(day=1)
    end = date(start.year, start.month, 28) if start.day <= 28 else date(start.year, start.month, 28)
    resp = webapp_client.put(
        "/api/webapp/budget/month",
        json={
            "planned_expense": 1234,
            "planned_income": 2000,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
    )
    assert resp.status_code == 200
    created = resp.json()
    bid = created.get("id")
    assert bid is not None

    # delete it
    del_resp = webapp_client.delete(f"/api/webapp/budget/{bid}")
    assert del_resp.status_code == 200
    payload = del_resp.json()
    assert payload.get("ok") is True
    deleted = payload.get("deleted")
    assert deleted is not None
    assert deleted["id"] == bid

    # confirm budget no longer present in snapshot for that month
    get_resp = webapp_client.get(f"/api/webapp/budget?year={start.year}&month={start.month}")
    assert get_resp.status_code == 200
    snap = get_resp.json()
    # monthly_plan id should not equal deleted id
    mp = snap.get("monthly_plan") or {}
    assert mp.get("id") != bid

    # undo by recreating using returned payload
    undo_resp = webapp_client.put(
        "/api/webapp/budget/month",
        json={
            "planned_expense": deleted["planned_expense"],
            "planned_income": deleted.get("planned_income", 0),
            "period_start": deleted["period_start"],
            "period_end": deleted["period_end"],
        },
    )
    assert undo_resp.status_code == 200
    # now snapshot should show a monthly_plan
    get_resp2 = webapp_client.get(f"/api/webapp/budget?year={start.year}&month={start.month}")
    assert get_resp2.status_code == 200
    snap2 = get_resp2.json()
    assert (snap2.get("monthly_plan") or {}).get("planned_expense") == float(deleted["planned_expense"])
