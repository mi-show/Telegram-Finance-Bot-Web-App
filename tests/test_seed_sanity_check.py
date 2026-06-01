import json
from pathlib import Path

from app.scripts.sanity_check_seed_keywords import run_seed_sanity_check


def _write_seed(path: Path, entries: list[dict]) -> Path:
    payload = {"version": 1, "entries": entries}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _entry(*, phrase: str, language: str = "en", category: str = "Housing", subcategory: str = "Rent") -> dict:
    return {
        "language": language,
        "category": category,
        "subcategory": subcategory,
        "phrase": phrase,
        "weight": 2,
    }


def test_seed_sanity_detects_too_long_phrase(tmp_path):
    seed = _write_seed(
        tmp_path / "seed.json",
        [_entry(phrase="a" * 81)],
    )

    errors, _warnings = run_seed_sanity_check(seed)

    assert any("too long" in error for error in errors)


def test_seed_sanity_detects_mixed_script_token(tmp_path):
    seed = _write_seed(
        tmp_path / "seed.json",
        [_entry(phrase="такsi", language="ru", category="🏠 Жильё", subcategory="Аренда")],
    )

    errors, _warnings = run_seed_sanity_check(seed)

    assert any("mixed-script token" in error for error in errors)


def test_seed_sanity_detects_duplicate_phrases(tmp_path):
    seed = _write_seed(
        tmp_path / "seed.json",
        [
            _entry(phrase="rent"),
            _entry(phrase="rent"),
        ],
    )

    _errors, warnings = run_seed_sanity_check(seed)

    assert any("duplicate phrase" in warning for warning in warnings)


def test_seed_sanity_subcategory_coverage_flag_adds_warnings(tmp_path):
    seed = _write_seed(
        tmp_path / "seed.json",
        [_entry(phrase="rent")],
    )

    _errors, warnings = run_seed_sanity_check(seed, check_subcategory_coverage=True)

    assert any("missing subcategory coverage" in warning for warning in warnings)
