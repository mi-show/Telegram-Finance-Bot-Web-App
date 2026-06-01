import asyncio
import json
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.request import urlopen

from ...cache import SimpleCache
from .constants import (
    CURRENCY_SCALE,
    FALLBACK_RATES_BY_USD,
    LIVE_FX_API_URL,
    SUPPORTED_CONVERSION_ORDER,
    SUPPORTED_ONBOARDING_CURRENCIES,
)

logger = logging.getLogger(__name__)


class CurrencyService:
    """Handles amount parsing and conversion rates for onboarding and /convert."""

    def __init__(
        self,
        live_fx_cache: SimpleCache | None = None,
        live_fx_api_url: str = LIVE_FX_API_URL,
        fallback_rates_by_usd: dict[str, Decimal] | None = None,
    ) -> None:
        self._live_fx_cache = live_fx_cache or SimpleCache(ttl_seconds=1800)
        self._live_fx_api_url = live_fx_api_url
        self._fallback_rates = dict(fallback_rates_by_usd or FALLBACK_RATES_BY_USD)

    @property
    def live_fx_cache(self) -> SimpleCache:
        return self._live_fx_cache

    def fmt_amount(self, value: Decimal | None) -> str:
        return f"{value:.2f}" if value is not None else "?"

    def parse_amount_input(self, raw_text: str) -> Decimal | None:
        cleaned = raw_text.strip().replace(" ", "").replace(",", ".")
        if not cleaned or not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
            return None
        try:
            amount = Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None
        if amount <= 0:
            return None
        return amount.quantize(CURRENCY_SCALE, rounding=ROUND_HALF_UP)

    def normalize_currency_code(self, currency: str | None) -> str | None:
        if not currency:
            return None
        normalized = currency.upper().strip()
        return normalized if normalized in SUPPORTED_ONBOARDING_CURRENCIES else None

    def fallback_rates_by_usd(self) -> dict[str, Decimal]:
        return dict(self._fallback_rates)

    def extract_live_rates(self, payload: dict) -> dict[str, Decimal] | None:
        raw_rates = payload.get("rates") if isinstance(payload, dict) else None
        if not isinstance(raw_rates, dict):
            return None

        parsed = {"USD": Decimal("1.00")}
        for currency in SUPPORTED_CONVERSION_ORDER:
            if currency == "USD":
                continue
            raw_value = raw_rates.get(currency)
            if raw_value is None:
                return None
            try:
                rate = Decimal(str(raw_value))
            except (InvalidOperation, ValueError):
                return None
            if rate <= 0:
                return None
            parsed[currency] = rate
        return parsed

    async def get_live_rates_by_usd(self) -> dict[str, Decimal]:
        cached = self._live_fx_cache.get("rates_by_usd")
        if isinstance(cached, dict):
            return cached

        rates = self.fallback_rates_by_usd()
        try:

            def fetch_payload() -> dict | None:
                with urlopen(self._live_fx_api_url, timeout=6) as response:
                    raw = response.read()
                return json.loads(raw.decode("utf-8"))

            payload = await asyncio.to_thread(fetch_payload)
            if isinstance(payload, dict):
                live_rates = self.extract_live_rates(payload)
                if live_rates:
                    rates = live_rates
        except Exception as exc:
            logger.warning("Failed to fetch live FX rates, using fallback values: %s", exc)

        self._live_fx_cache.set("rates_by_usd", rates)
        return rates

    def convert_amount_with_rates(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        rates_by_usd: dict[str, Decimal],
    ) -> Decimal:
        source = self.normalize_currency_code(from_currency)
        target = self.normalize_currency_code(to_currency)
        if source is None or target is None:
            raise ValueError("Unsupported conversion pair")

        if source == target:
            return amount.quantize(CURRENCY_SCALE, rounding=ROUND_HALF_UP)

        source_rate = rates_by_usd.get(source)
        target_rate = rates_by_usd.get(target)
        if source_rate is None or target_rate is None or source_rate <= 0 or target_rate <= 0:
            raise ValueError("Rates are unavailable for conversion")

        amount_in_usd = amount / source_rate
        converted = amount_in_usd * target_rate
        return converted.quantize(CURRENCY_SCALE, rounding=ROUND_HALF_UP)

    def default_target_currency(self, source_currency: str) -> str:
        defaults = {
            "UAH": "USD",
            "USD": "UAH",
            "EUR": "UAH",
        }
        return defaults.get(source_currency, "UAH")
