from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

from app.scripts.load_custom import CATEGORIES, SEED_KEYWORDS_PATH, load_seed_keyword_entries


_ALNUM_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")
_WORD_SPLIT_RE = re.compile(r"[\s/]+")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_MOJIBAKE_MARKERS = ("\ufffd", "Ð", "Ñ", "Ã", "Â")


def _phrase_issue(phrase: str, language: str) -> str | None:
    if len(phrase) < 2:
        return "too short"
    if len(phrase) > 80:
        return "too long"
    if phrase.startswith("#"):
        return "comment-like phrase"
    if not _ALNUM_RE.search(phrase):
        return "no alphanumeric characters"
    if _REPEATED_CHAR_RE.search(phrase):
        return "long repeated character sequence"
    if any(marker in phrase for marker in _MOJIBAKE_MARKERS):
        return "possible mojibake"

    words = [word for word in _WORD_SPLIT_RE.split(phrase) if word]
    if len(words) > 10:
        return "too many tokens"

    for word in words:
        has_latin = bool(_LATIN_RE.search(word))
        has_cyrillic = bool(_CYRILLIC_RE.search(word))
        if has_latin and has_cyrillic:
            return "mixed-script token"

    if language == "en" and _CYRILLIC_RE.search(phrase):
        return "cyrillic symbols in en phrase"

    return None


def run_seed_sanity_check(
    seed_path: Path = SEED_KEYWORDS_PATH,
    *,
    check_subcategory_coverage: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        entries = load_seed_keyword_entries(seed_path)
    except Exception as exc:
        return [str(exc)], []

    seen: dict[tuple[str, str], int] = {}
    category_counts: dict[tuple[str, str], int] = defaultdict(int)
    subcategory_counts: dict[tuple[str, str, str], int] = defaultdict(int)

    for idx, entry in enumerate(entries):
        language = str(entry["language"])
        category = str(entry["category"])
        subcategory = entry.get("subcategory")
        phrase = str(entry["phrase"])

        if language not in CATEGORIES:
            errors.append(f"[{idx}] unsupported language: {language}")
            continue

        categories = CATEGORIES[language]
        if category not in categories:
            errors.append(f"[{idx}] unknown category for {language}: {category}")
            continue

        category_counts[(language, category)] += 1

        if subcategory:
            valid_subcategories = categories.get(category, [])
            if subcategory not in valid_subcategories:
                errors.append(
                    f"[{idx}] unknown subcategory for {language}: {category}/{subcategory}"
                )
            else:
                subcategory_counts[(language, category, str(subcategory))] += 1

        issue = _phrase_issue(phrase, language)
        if issue is not None:
            errors.append(f"[{idx}] suspicious phrase for {language}: '{phrase}' ({issue})")

        key = (language, phrase)
        previous = seen.get(key)
        if previous is not None:
            warnings.append(
                f"[{idx}] duplicate phrase in {language}: '{phrase}' (first at index {previous})"
            )
        else:
            seen[key] = idx

    for language, categories in CATEGORIES.items():
        for category in categories:
            if category_counts[(language, category)] == 0:
                warnings.append(f"missing category coverage: {language}/{category}")

    if check_subcategory_coverage:
        for language, categories in CATEGORIES.items():
            for category, subcategories in categories.items():
                for subcategory in subcategories:
                    if subcategory_counts[(language, category, subcategory)] == 0:
                        warnings.append(
                            f"missing subcategory coverage: {language}/{category}/{subcategory}"
                        )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate JSON seed keywords data")
    parser.add_argument("--seed", type=Path, default=SEED_KEYWORDS_PATH, help="Path to seed JSON file")
    parser.add_argument("--max-errors", type=int, default=50, help="How many errors to print")
    parser.add_argument("--max-warnings", type=int, default=50, help="How many warnings to print")
    parser.add_argument(
        "--fail-on-warnings",
        action="store_true",
        help="Return non-zero if warnings are found",
    )
    parser.add_argument(
        "--check-subcategory-coverage",
        action="store_true",
        help="Warn if any configured subcategory has no seed keywords",
    )
    args = parser.parse_args()

    errors, warnings = run_seed_sanity_check(
        args.seed.resolve(),
        check_subcategory_coverage=args.check_subcategory_coverage,
    )

    if warnings:
        print(f"Warnings: {len(warnings)}")
        for warning in warnings[: args.max_warnings]:
            print(f"WARN: {warning}")

    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[: args.max_errors]:
            print(f"ERR: {error}")
        return 1

    if args.fail_on_warnings and warnings:
        print("Failing due to warnings (--fail-on-warnings enabled).")
        return 1

    print("Seed keyword sanity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
