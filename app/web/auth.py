import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from time import time
from urllib.parse import parse_qsl


@dataclass(frozen=True)
class TelegramWebUser:
    telegram_id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramAuthError(ValueError):
    pass


def _build_data_check_string(init_data: str) -> tuple[str, str]:
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    if not pairs:
        raise TelegramAuthError("Empty init data")

    payload = dict(pairs)
    received_hash = payload.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Missing hash")

    check_parts = [f"{key}={value}" for key, value in sorted(payload.items(), key=lambda item: item[0])]
    return "\n".join(check_parts), received_hash


def _verify_signature(bot_token: str, data_check_string: str, received_hash: str) -> bool:
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), sha256).hexdigest()
    return hmac.compare_digest(expected_hash, received_hash)


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
) -> TelegramWebUser:
    data_check_string, received_hash = _build_data_check_string(init_data)

    if not _verify_signature(bot_token, data_check_string, received_hash):
        raise TelegramAuthError("Invalid Telegram signature")

    payload = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))

    auth_date_raw = payload.get("auth_date")
    if not auth_date_raw:
        raise TelegramAuthError("Missing auth_date")

    try:
        auth_timestamp = int(auth_date_raw)
    except ValueError as exc:
        raise TelegramAuthError("Invalid auth_date") from exc

    if int(time()) - auth_timestamp > max_age_seconds:
        raise TelegramAuthError("Expired init data")

    user_raw = payload.get("user")
    if not user_raw:
        raise TelegramAuthError("Missing user payload")

    try:
        user_data = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise TelegramAuthError("Invalid user payload") from exc

    telegram_id = user_data.get("id")
    if not telegram_id:
        raise TelegramAuthError("Missing user id")

    return TelegramWebUser(
        telegram_id=int(telegram_id),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        username=user_data.get("username"),
        language_code=user_data.get("language_code"),
    )
