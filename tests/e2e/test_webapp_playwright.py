from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync.sync_playwright

pytestmark = pytest.mark.e2e

ROOT_DIR = Path(__file__).resolve().parents[2]
PORT = 8010
BASE_URL = f"http://127.0.0.1:{PORT}"


def _wait_for_webapp(timeout_seconds: float = 40.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = httpx.get(f"{BASE_URL}/api/webapp/health", timeout=1.5)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


@pytest.fixture(scope="module")
def e2e_server():
    db_path = ROOT_DIR / "data" / "e2e_webapp.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    env = os.environ.copy()
    env.update(
        {
            "BOT_TOKEN": "123456:E2E_TEST_TOKEN",
            "DATABASE_URL": database_url,
            "WEBAPP_DEV_TELEGRAM_ID": "915551234",
            "WEBAPP_HOST": "127.0.0.1",
            "WEBAPP_PORT": str(PORT),
            "LOG_LEVEL": "WARNING",
            "E2E_DATABASE_URL": database_url,
            "E2E_TELEGRAM_ID": "915551234",
        }
    )

    prepare = subprocess.run(
        [sys.executable, "-m", "scripts.e2e_prepare_db"],
        cwd=str(ROOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if prepare.returncode != 0:
        pytest.fail(f"Failed to prepare e2e database:\n{prepare.stdout}\n{prepare.stderr}")

    process = subprocess.Popen(
        [sys.executable, "-m", "app.web_main"],
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not _wait_for_webapp():
        process.terminate()
        pytest.fail("Web app did not start for Playwright e2e tests")

    yield

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="module")
def browser(e2e_server):
    with sync_playwright() as playwright:
        try:
            browser_instance = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium browser is not available for Playwright tests: {exc}")

        yield browser_instance
        browser_instance.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context(accept_downloads=True, locale="en-US")
    page = context.new_page()
    page.goto(f"{BASE_URL}/webapp", wait_until="networkidle")
    page.wait_for_selector("#page-dashboard.page.active")
    yield page
    context.close()


def open_operations(page):
    page.click('button[data-page="operations"]')
    page.wait_for_selector("#page-operations.page.active")
    page.wait_for_selector("#recordsBody tr")


def open_settings(page):
    page.click('button[data-page="settings"]')
    page.wait_for_selector("#page-settings.page.active")


def open_analytics(page):
    page.click('button[data-page="analytics"]')
    page.wait_for_selector("#page-analytics.page.active")


def test_create_operation_with_quick_templates(page):
    open_operations(page)

    page.wait_for_function(
        "() => document.querySelector('#createCategory') && document.querySelector('#createCategory').options.length > 1"
    )
    page.select_option("#createType", "expense")
    page.select_option("#createCategory", index=1)

    unique_description = f"PW create {int(time.time())}"
    page.fill("#createAmount", "42.50")
    page.fill("#createDescription", unique_description)
    page.click("#createRecordBtn")

    page.wait_for_selector(f"text={unique_description}")


def test_filters_flow(page):
    open_operations(page)

    page.fill("#filterMin", "200")
    page.click('#filtersForm button[type="submit"]')
    page.wait_for_selector("#recordsBody tr")

    body_text = page.locator("#recordsBody").inner_text()
    assert "Weekly basket" in body_text
    assert "Airport ride" not in body_text


def test_record_editing_flow(page):
    open_operations(page)

    page.locator("#recordsBody button[data-edit-id]").first.click()
    page.wait_for_selector("#recordEditModal.show")

    updated_description = f"PW edit {int(time.time())}"
    page.fill("#modalAmount", "333.33")
    page.fill("#modalDescription", updated_description)
    page.click('#recordEditForm button[type="submit"]')

    page.wait_for_selector(f"text={updated_description}")


def test_export_flow(page):
    open_operations(page)

    with page.expect_download() as csv_info:
        page.click("#exportCsvBtn")
    csv_download = csv_info.value
    assert csv_download.suggested_filename.endswith(".csv")

    with page.expect_download() as pdf_info:
        page.click("#exportPdfBtn")
    pdf_download = pdf_info.value
    assert pdf_download.suggested_filename.endswith(".pdf")


def test_settings_and_localization_flow(page):
    open_settings(page)

    page.select_option("#settingLanguage", "ru")
    page.select_option("#settingTheme", "light")
    page.click('#settingsForm button[type="submit"]')

    page.wait_for_function(
        "() => document.querySelector('button[data-page=\"operations\"]').textContent.includes('Операции')"
    )
    assert "Операции" in page.locator('button[data-page="operations"]').inner_text()


def test_budget_overview_drilldown_flow(page):
    open_analytics(page)

    page.wait_for_selector("#budgetOverview")
    page.wait_for_selector("#budgetPlanChart")
    page.wait_for_selector(".limit-row")
    page.wait_for_selector("canvas.limit-spark")

    page.locator(".limit-row").first.click()
    page.wait_for_selector("#page-operations.page.active")
    assert page.locator("#filterType").input_value() == "expense"
