from __future__ import annotations

import re

_SPLIT_RE = re.compile(r"[;,|]")
_WS_RE = re.compile(r"\s+")

# Compact multilingual stop-list to avoid noisy tokens when expanding long keyword lines.
_STOPWORDS = {
    "and",
    "for",
    "the",
    "with",
    "\u0431\u0435\u0437",
    "\u0434\u043b\u044f",
    "\u0438\u043b\u0438",
    "\u043d\u0430\u0434",
    "\u043f\u043e\u0434",
    "\u043f\u0440\u0438",
    "\u043f\u0440\u043e",
    "\u044d\u0442\u043e",
    "\u0430\u043b\u0435",
    "\u043f\u0456\u0434",
    "\u0442\u0430",
    "\u0446\u0435",
}

def _normalize_keyword_entry(value: str) -> str:
    return _WS_RE.sub(" ", (value or "").strip())


def expand_keyword_entries(raw_line: str) -> list[str]:
    """
    Expand a raw keyword line into one or more keyword entries.

    Supported formats:
    - one phrase per line (default),
    - delimited lines (comma/semicolon/pipe),
    - compact bag-style lines with many words on one line.
    """
    line = _normalize_keyword_entry(raw_line)
    if not line or line.startswith("#"):
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        normalized = _WS_RE.sub(" ", value.strip())
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(normalized)

    # Always keep the full phrase form.
    _add(line)

    # Split explicit delimiter-based records.
    if _SPLIT_RE.search(line):
        for part in _SPLIT_RE.split(line):
            _add(part)

    tokens = [token for token in line.split(" ") if token]

    # Recover from one-line compact dictionaries: "taxi uber lyft ..."
    if len(tokens) >= 4:
        for token in tokens:
            token_lower = token.lower()
            if len(token_lower) < 3:
                continue
            if token_lower in _STOPWORDS:
                continue
            _add(token)

    return out
