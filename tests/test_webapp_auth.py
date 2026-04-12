import hmac
import json
from hashlib import sha256
from time import time
from urllib.parse import urlencode

import pytest

from app.web.auth import TelegramAuthError, validate_init_data


def _sign_payload(bot_token: str, payload: dict[str, str]) -> str:
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), sha256).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"), sha256).hexdigest()


def _build_init_data(bot_token: str, auth_date: int | None = None) -> str:
    payload = {
        "auth_date": str(auth_date if auth_date is not None else int(time())),
        "query_id": "AAH_TEST_QUERY",
        "user": json.dumps(
            {
                "id": 123456789,
                "first_name": "Test",
                "last_name": "User",
                "username": "test_user",
                "language_code": "ru",
            },
            separators=(",", ":"),
        ),
    }
    payload["hash"] = _sign_payload(bot_token, payload)
    return urlencode(payload)


def test_validate_init_data_success():
    bot_token = "123456:TEST_TOKEN"
    init_data = _build_init_data(bot_token)

    user = validate_init_data(init_data, bot_token, max_age_seconds=86400)
    assert user.telegram_id == 123456789
    assert user.username == "test_user"
    assert user.language_code == "ru"


def test_validate_init_data_invalid_hash():
    bot_token = "123456:TEST_TOKEN"
    init_data = _build_init_data(bot_token) + "x"

    with pytest.raises(TelegramAuthError):
        validate_init_data(init_data, bot_token)


def test_validate_init_data_expired():
    bot_token = "123456:TEST_TOKEN"
    old_timestamp = int(time()) - 90000
    init_data = _build_init_data(bot_token, auth_date=old_timestamp)

    with pytest.raises(TelegramAuthError):
        validate_init_data(init_data, bot_token, max_age_seconds=3600)
