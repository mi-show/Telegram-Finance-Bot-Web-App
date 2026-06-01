from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Optional, List


@dataclass
class ParsedLineItem:
    """Single line item extracted from receipt text."""

    name: str
    price: Optional[Decimal]
    quantity: Optional[Decimal] = None
    raw: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ParsedReceipt:
    amount: Optional[Decimal]
    merchant: Optional[str]
    date: Optional[date]
    description: Optional[str]
    items: List[ParsedLineItem] = field(default_factory=list)
    amount_confidence: float = 0.0
    merchant_confidence: float = 0.0
    items_confidence: float = 0.0
    overall_confidence: float = 0.0
    consistency_delta: Optional[Decimal] = None
    quality_flags: List[str] = field(default_factory=list)


class ReceiptParser:
    """Heuristics to extract amount, merchant, date and line items from OCR text."""

    amount_keywords = re.compile(r"(total|итого|сумма|сума|amount|sum)", re.IGNORECASE)
    amount_fallback = re.compile(r"(\d+[.,]\d{2})")
    date_re = re.compile(r"(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{2,4})")
    price_tail_re = re.compile(
        r"(?P<price>\d{1,5}[.,]\d{2})(?:\s*(?:грн|uah|₴|[A-Za-zА-Яа-яІіЇїЄєҐґ]))?\s*$",
        re.IGNORECASE,
    )
    quantity_re = re.compile(r"(?:x|х)\s?(?P<qty>\d{1,3})", re.IGNORECASE)
    amount_near_start_re = re.compile(r"^\s*\d{1,2}[.,]\d{2,3}\s*[xх×]", re.IGNORECASE)
    ignore_line_tokens = (
        "итог",
        "итого",
        "сума",
        "сумма",
        "нал",
        "карта",
        "каса",
        "пдв",
        "nds",
        "tax",
        "change",
        "rest",
        "сдача",
        "решта",
        "коп",
        "коп.",
        "копi",
        "копій",
        "сум",
        "total",
        "податок",
    )
    cash_change_tokens = (
        "грош",
        "готів",
        "налич",
        "cash",
        "received",
        "change",
        "решта",
        "сдача",
    )
    total_like_line = re.compile(r"(сума|сумма|итого|total|всього)", re.IGNORECASE)
    tax_percent_re = re.compile(r"(п\W*д\W*в|н\W*д\W*с|vat|tax).{0,16}%", re.IGNORECASE)
    receipt_service_tokens = (
        "гаряча лінія",
        "горячая линия",
        "hotline",
        "e-mail",
        "email",
        "www",
        "http",
        "вул",
        "ул.",
        "улица",
        "прим",
        "документ",
        "службов",
        "служеб",
        "копія",
        "копия",
        "фіскаль",
        "фискаль",
    )
    max_reasonable_amount = Decimal("99999.99")
    max_reasonable_item_price = Decimal("9999.99")

    def parse(self, text: str) -> ParsedReceipt:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        amount, amount_confidence, amount_flags = self._extract_amount_stage(lines)
        merchant, merchant_confidence = self._extract_merchant_stage(lines)
        dt = self._extract_date(lines)
        description = "; ".join(lines[:3]) if lines else None
        items = self._extract_items(lines)

        amount_inferred_from_items = False
        if amount is None and items:
            prices = [item.price for item in items if item.price is not None]
            if prices:
                amount = sum(prices, Decimal("0"))
                amount_confidence = max(amount_confidence, 0.55)
                amount_flags.append("amount_inferred_from_items")
                amount_inferred_from_items = True

        items_confidence = self._items_confidence(items)
        amount_confidence, items_confidence, consistency_delta, consistency_flags = self._post_validate_total_vs_items(
            amount,
            amount_confidence,
            items,
            items_confidence,
        )

        quality_flags = amount_flags + consistency_flags
        overall_confidence = self._overall_confidence(
            amount_confidence,
            merchant_confidence,
            items_confidence,
            has_items=bool(items),
            amount_inferred=amount_inferred_from_items,
        )

        return ParsedReceipt(
            amount=amount,
            merchant=merchant,
            date=dt,
            description=description,
            items=items,
            amount_confidence=amount_confidence,
            merchant_confidence=merchant_confidence,
            items_confidence=items_confidence,
            overall_confidence=overall_confidence,
            consistency_delta=consistency_delta,
            quality_flags=quality_flags,
        )

    def _extract_amount_stage(self, lines: list[str]) -> tuple[Optional[Decimal], float, list[str]]:
        total_candidates: list[tuple[int, int, Decimal]] = []
        keyword_candidates: list[tuple[int, int, Decimal]] = []
        fallback_candidates: list[tuple[int, Decimal]] = []

        for idx, ln in enumerate(lines):
            lower = ln.lower()
            if self._is_cash_change_line(lower, allow_total=True) and not self.total_like_line.search(lower):
                continue

            amount_candidates = self._line_amount_candidates(ln)
            if not amount_candidates:
                continue

            total_match = self.total_like_line.search(lower)
            if total_match:
                pos, value = self._pick_keyword_candidate(amount_candidates, total_match.end())
                total_candidates.append((idx, abs(pos - total_match.end()), value))
                continue

            keyword_match = self.amount_keywords.search(lower)
            if keyword_match and not self._is_cash_change_line(lower):
                pos, value = self._pick_keyword_candidate(amount_candidates, keyword_match.end())
                keyword_candidates.append((idx, abs(pos - keyword_match.end()), value))
                continue

            if not self._is_cash_change_line(lower):
                _pos, strongest = max(amount_candidates, key=lambda item: item[1])
                fallback_candidates.append((idx, strongest))

        if total_candidates:
            _idx, _distance, amount = max(total_candidates, key=lambda item: (item[0], -item[1]))
            confidence = 0.93
            return amount, confidence, ["amount_from_total_line"]

        if keyword_candidates:
            _idx, _distance, amount = max(keyword_candidates, key=lambda item: (item[0], -item[1]))
            confidence = 0.78
            return amount, confidence, ["amount_from_keyword_line"]

        if fallback_candidates:
            _idx, amount = max(fallback_candidates, key=lambda item: item[1])
            confidence = 0.56
            return amount, confidence, ["amount_from_fallback_max"]

        return None, 0.0, ["amount_not_found"]

    def _extract_amount(self, lines: list[str]) -> Optional[Decimal]:
        amount, _confidence, _flags = self._extract_amount_stage(lines)
        return amount

    def _line_amount_candidates(self, line: str) -> list[tuple[int, Decimal]]:
        candidates: list[tuple[int, Decimal]] = []
        for match in self.amount_fallback.finditer(line):
            value = self._to_decimal(match.group(1))
            if value is None:
                continue
            if value <= Decimal("0") or value > self.max_reasonable_amount:
                continue
            if self._looks_like_date_fragment(line, match.start(), match.end()):
                continue
            candidates.append((match.start(), value))
        return candidates

    @staticmethod
    def _pick_keyword_candidate(candidates: list[tuple[int, Decimal]], anchor_pos: int) -> tuple[int, Decimal]:
        candidates_after = [candidate for candidate in candidates if candidate[0] >= anchor_pos]
        if candidates_after:
            return min(candidates_after, key=lambda candidate: candidate[0] - anchor_pos)
        return min(candidates, key=lambda candidate: abs(candidate[0] - anchor_pos))

    @staticmethod
    def _looks_like_date_fragment(line: str, start: int, end: int) -> bool:
        # Filters out captures like 25.01 from date strings 25.01.2017.
        if end + 1 < len(line) and line[end] in "./-" and line[end + 1].isdigit():
            return True
        if start >= 2 and line[start - 1].isdigit() and line[start - 2] in "./-":
            return True
        return False

    def _extract_merchant_stage(self, lines: list[str]) -> tuple[Optional[str], float]:
        for ln in lines:
            letters = sum(ch.isalpha() for ch in ln)
            digits = sum(ch.isdigit() for ch in ln)
            total = letters + digits
            if letters >= digits and len(ln) > 2:
                ratio = (letters / total) if total else 0.0
                confidence = min(0.95, max(0.45, 0.45 + ratio * 0.5))
                return ln[:64], confidence
        return None, 0.0

    def _extract_merchant(self, lines: list[str]) -> Optional[str]:
        merchant, _confidence = self._extract_merchant_stage(lines)
        return merchant

    def _extract_date(self, lines: list[str]) -> Optional[date]:
        for ln in lines:
            m = self.date_re.search(ln)
            if m:
                d = int(m.group("d"))
                mth = int(m.group("m"))
                y = int(m.group("y"))
                y = 2000 + y if y < 100 else y
                try:
                    return date(y, mth, d)
                except ValueError:
                    continue
        return None

    def _find_number(self, text: str) -> Optional[Decimal]:
        m = self.amount_fallback.search(text)
        if m:
            return self._to_decimal(m.group(1))
        return None

    def _extract_items(self, lines: list[str]) -> List[ParsedLineItem]:
        items: List[ParsedLineItem] = []
        idx = 0
        while idx < len(lines):
            ln = lines[idx]
            ln_clean = re.sub(r"\s+", " ", ln.strip())
            if not ln_clean:
                idx += 1
                continue

            # Recover common receipt OCR split: name on line N, quantity/price on line N+1.
            merged_with_next = False
            if idx + 1 < len(lines) and not self.amount_fallback.search(ln_clean):
                nxt = re.sub(r"\s+", " ", lines[idx + 1].strip())
                if self.amount_near_start_re.search(nxt) and self.amount_fallback.search(nxt):
                    ln_clean = f"{ln_clean} {nxt}"
                    idx += 1
                    merged_with_next = True

            lower = ln_clean.lower()
            if self._should_skip_item_line(ln_clean, lower):
                idx += 1
                continue

            price_match = self.price_tail_re.search(ln_clean)
            price = None
            price_start = -1
            if price_match:
                price = self._to_decimal(price_match.group("price"))
                price_start = price_match.start()
                price_match_type = "tail"
            else:
                # Fallback for OCR lines where amount is present near the tail but with extra noise.
                candidates = list(self.amount_fallback.finditer(ln_clean))
                if not candidates:
                    idx += 1
                    continue
                last = candidates[-1]
                if len(ln_clean) - last.end() > 6:
                    idx += 1
                    continue
                price = self._to_decimal(last.group(1))
                price_start = last.start()
                price_match_type = "fallback"

            if price is None or price_start < 0:
                idx += 1
                continue
            if price > self.max_reasonable_item_price:
                idx += 1
                continue

            name = ln_clean[:price_start].strip(" -–.:;=+|")
            # Strip trailing "x unit_price" fragments often left by OCR.
            name = re.sub(r"[\d\s.,]*[xх×]\s*[\d.,]+\s*=?\s*$", "", name, flags=re.IGNORECASE).strip()

            # Skip near-empty names and lines with no letters.
            if len(name) < 3:
                idx += 1
                continue
            letters = sum(ch.isalpha() for ch in name)
            if letters < 3:
                idx += 1
                continue
            if not re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]{3,}", name):
                idx += 1
                continue

            qty = None
            qty_match = self.quantity_re.search(name)
            if qty_match:
                qty = self._to_decimal(qty_match.group("qty"))
                name = self.quantity_re.sub("", name).strip()

            confidence = 0.70
            if price_match_type == "tail":
                confidence += 0.15
            else:
                confidence -= 0.10

            if letters >= 6:
                confidence += 0.05
            if merged_with_next:
                confidence += 0.05
            if qty is not None:
                confidence += 0.03

            confidence = max(0.0, min(1.0, confidence))

            items.append(
                ParsedLineItem(
                    name=name,
                    price=price,
                    quantity=qty,
                    raw=ln_clean,
                    confidence=confidence,
                )
            )

            idx += 1

        return items

    def _should_skip_item_line(self, line: str, lower_line: str) -> bool:
        if any(token in lower_line for token in self.ignore_line_tokens):
            return True
        if self._is_cash_change_line(lower_line):
            return True
        if any(token in lower_line for token in self.receipt_service_tokens):
            return True
        if self.tax_percent_re.search(lower_line):
            return True
        if "@" in line:
            return True

        digits = sum(ch.isdigit() for ch in line)
        letters = sum(ch.isalpha() for ch in line)
        if digits >= 10 and letters <= 6:
            return True

        return False

    @staticmethod
    def _items_confidence(items: List[ParsedLineItem]) -> float:
        if not items:
            return 0.30
        return max(0.0, min(1.0, sum(item.confidence for item in items) / len(items)))

    def _post_validate_total_vs_items(
        self,
        amount: Optional[Decimal],
        amount_confidence: float,
        items: List[ParsedLineItem],
        items_confidence: float,
    ) -> tuple[float, float, Optional[Decimal], List[str]]:
        flags: List[str] = []
        prices = [item.price for item in items if item.price is not None]
        if amount is None or not prices:
            return amount_confidence, items_confidence, None, flags

        item_total = sum(prices, Decimal("0"))
        delta = abs(amount - item_total)
        tolerance = max(Decimal("2.00"), amount * Decimal("0.10"))

        if delta <= tolerance:
            flags.append("total_matches_items")
            return (
                min(1.0, amount_confidence + 0.05),
                min(1.0, items_confidence + 0.05),
                delta,
                flags,
            )

        flags.append("total_items_mismatch")
        amount_confidence = max(0.0, amount_confidence - 0.25)
        items_confidence = max(0.0, items_confidence - 0.10)
        return amount_confidence, items_confidence, delta, flags

    @staticmethod
    def _overall_confidence(
        amount_confidence: float,
        merchant_confidence: float,
        items_confidence: float,
        *,
        has_items: bool,
        amount_inferred: bool,
    ) -> float:
        if has_items:
            score = amount_confidence * 0.45 + merchant_confidence * 0.15 + items_confidence * 0.40
        else:
            score = amount_confidence * 0.75 + merchant_confidence * 0.25
        if amount_inferred:
            score -= 0.10
        return max(0.0, min(1.0, score))

    def _is_cash_change_line(self, lower_line: str, allow_total: bool = False) -> bool:
        if allow_total and self.total_like_line.search(lower_line):
            return False
        return any(token in lower_line for token in self.cash_change_tokens)

    @staticmethod
    def _to_decimal(raw: str) -> Optional[Decimal]:
        normalized = raw.replace(",", ".")
        try:
            return Decimal(normalized)
        except (InvalidOperation, ValueError):
            return None
