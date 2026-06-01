import pytest
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from app.services.ocr_service import OCRService, OCRConfigurationError


def _make_test_image(tmp_path):
    path = tmp_path / "ocr_test.png"
    font = _load_font()
    if font is None:
        pytest.skip("No suitable TrueType font found for stable OCR test")

    image = Image.new("L", (600, 220), 255)
    draw = ImageDraw.Draw(image)
    draw.text((60, 60), "1234", fill=0, font=font)
    image.save(path)
    return path


def _load_font():
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=88)
            except OSError:
                continue
    return None


@pytest.mark.asyncio
async def test_extract_text_reads_amount(tmp_path):
    try:
        service = OCRService(preferred_langs=["eng"])
    except OCRConfigurationError as exc:
        pytest.skip(f"OCR not available: {exc}")

    image_path = _make_test_image(tmp_path)
    try:
        text = await service.extract_text(image_path)
    except OCRConfigurationError as exc:
        pytest.skip(f"OCR not available: {exc}")

    digits = "".join(ch for ch in text if ch.isdigit())
    assert "1234" in digits


def test_cleanup_text_normalizes_receipt_lines():
    service = OCRService(preferred_langs=["eng"])
    raw = """
    Мандарин 0,820 X 32,99 = 27 05 A
    ||
    Мандарин 0,820 X 32,99 = 27 05 A
    Сума   174,02
    """

    cleaned = service._cleanup_text(raw)
    lines = cleaned.splitlines()

    assert len(lines) == 2
    assert any("27,05" in line for line in lines)
    assert any("Сума 174,02" in line for line in lines)


def test_score_text_prefers_receipt_like_output():
    good = """
    Майонез 350 г 13,90 A
    Банан 0,724 X 21,99 = 15,92 A
    Сума 174,02
    """
    noisy = """
    xqzvbnm pqrrr
    lllkkk tttss
    11111 22222
    """

    assert OCRService._score_text(good) > OCRService._score_text(noisy)


def test_score_text_details_contains_signal_breakdown():
    text = """
    Apple 1,000 x 2,49 = 2,49 A
    Bread 1,99 A
    Total 4,48
    """

    details = OCRService._score_text_details(text)

    assert details["score"] > 0
    assert details["line_count"] >= 3
    assert details["item_like_lines"] >= 1
    assert details["total_like_lines"] >= 1


def test_pick_ocr_configs_adapts_to_profile():
    narrow_profile = {"aspect": 1.8, "contrast": 18.0}
    configs = OCRService._pick_ocr_configs(narrow_profile)

    assert any("--psm 4" in cfg for cfg in configs)
    assert any("--psm 11" in cfg for cfg in configs)


def test_write_diagnostics_creates_debug_artifact(tmp_path):
    service = OCRService(preferred_langs=["eng"], enable_diagnostics=True, diagnostics_dir=tmp_path)
    service._write_diagnostics(
        image_path=Path("receipt.jpg"),
        profile={"brightness": 120.0, "contrast": 22.0, "aspect": 1.5, "width": 900.0, "height": 600.0},
        candidates=[
            {
                "score": 123,
                "variant": 0,
                "lang": "eng",
                "config": "--oem 3 --psm 6 -c preserve_interword_spaces=1",
                "source": "data",
                "details": {"score": 123, "line_count": 3},
                "text": "Total 4,48",
            }
        ],
        final_text="Total 4,48",
    )

    artifacts = list(tmp_path.glob("*.json"))
    assert artifacts

    payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert payload["image_name"] == "receipt.jpg"
    assert payload["final_text"] == "Total 4,48"
