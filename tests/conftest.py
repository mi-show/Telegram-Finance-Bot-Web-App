"""Pytest configuration and fixtures."""
import os

import pytest


# Some modules instantiate Settings during import, so provide a test token
# before test collection starts regardless of shell environment.
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")


@pytest.fixture
def sample_decimal():
    """Fixture providing sample Decimal values."""
    from decimal import Decimal
    return Decimal("10.50")


@pytest.fixture
def sample_date():
    """Fixture providing sample date values."""
    from datetime import date
    return date(2024, 1, 15)
