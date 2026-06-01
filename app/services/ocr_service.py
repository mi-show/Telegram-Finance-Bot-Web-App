import asyncio
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageStat
import pytesseract
from pytesseract import Output, TesseractNotFoundError


class OCRConfigurationError(RuntimeError):
    """Raised when the Tesseract binary or language data is missing."""


DEFAULT_TESSERACT_PATHS = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path("/usr/bin/tesseract"),
    Path("/usr/local/bin/tesseract"),
]

PRICE_LINE_RE = re.compile(r"\d+[.,]\d{2}\s*(?:[A-Za-zА-Яа-яІіЇїЄєҐґ])?$")
QTY_PRICE_RE = re.compile(r"\d+[.,]\d+\s*[xх×]\s*\d+[.,]\d+", re.IGNORECASE)
TOTAL_TOKENS = ("сума", "сумма", "итого", "total", "всього")
ALNUM_RE = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґ]")
CLEAN_LINE_RE = re.compile(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ.,/%+\-()\s]")


class OCRService:
    """Async wrapper around pytesseract with graceful language fallback."""

    def __init__(
        self,
        preferred_langs: List[str] | None = None,
        tesseract_cmd: str | None = None,
        *,
        enable_diagnostics: bool | None = None,
        diagnostics_dir: str | Path | None = None,
    ):
        # order matters; will choose the first available combination
        self.preferred_langs = preferred_langs or ["rus", "ukr", "eng"]
        env_diag = os.getenv("OCR_ENABLE_DIAGNOSTICS", "").strip().lower() in {"1", "true", "yes", "on"}
        self.enable_diagnostics = enable_diagnostics if enable_diagnostics is not None else env_diag
        self.diagnostics_dir = Path(diagnostics_dir or os.getenv("OCR_DIAGNOSTICS_DIR", "data/ocr_diagnostics"))
        if self.enable_diagnostics:
            self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self._configure_tesseract_cmd(tesseract_cmd)

    async def extract_text(self, image_path: Path) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._extract, image_path)

    def _configure_tesseract_cmd(self, tesseract_cmd: str | None) -> None:
        candidate = tesseract_cmd or os.getenv("TESSERACT_CMD")
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return
        for path in DEFAULT_TESSERACT_PATHS:
            if path.exists():
                pytesseract.pytesseract.tesseract_cmd = str(path)
                return

    def _available_langs(self) -> set[str]:
        try:
            return set(pytesseract.get_languages(config=""))
        except TesseractNotFoundError as exc:
            raise OCRConfigurationError(
                "Tesseract binary not found. Install tesseract-ocr and ensure it is in PATH "
                "or set the TESSERACT_CMD environment variable to the binary location."
            ) from exc

    def _pick_lang_options(self, available: set[str]) -> list[str]:
        preferred = [lang for lang in self.preferred_langs if lang in available]
        options: list[str] = []

        if preferred:
            options.append("+".join(preferred))
            options.append(preferred[0])
        elif available:
            fallback = sorted(available)
            options.append("+".join(fallback))
            options.append(fallback[0])
        else:
            raise OCRConfigurationError(
                "Tesseract is installed but no language data found. "
                "Install language packs (e.g. tesseract-ocr-eng, tesseract-ocr-rus)."
            )

        if "eng" in available and "eng" not in options:
            options.append("eng")

        deduped: list[str] = []
        seen: set[str] = set()
        for option in options:
            if option and option not in seen:
                seen.add(option)
                deduped.append(option)

        # Keep OCR latency acceptable in production.
        return deduped[:2]

    def _extract(self, image_path: Path) -> str:
        try:
            available = self._available_langs()
            lang_options = self._pick_lang_options(available)
            detection_lang = lang_options[0]

            with Image.open(image_path) as source:
                transposed = ImageOps.exif_transpose(source)
                if transposed is None:
                    transposed = source
                base = ImageOps.grayscale(transposed.convert("RGB"))

            base = self._crop_receipt_region(base, detection_lang)
            base = self._autorotate(base, detection_lang)
            profile = self._image_profile(base)
            variants = self._build_variants(base, profile)
            configs = self._pick_ocr_configs(profile)

            if not self.enable_diagnostics:
                variants = variants[:1]
                configs = configs[:1]
                lang_options = lang_options[:1]

            candidates: list[dict] = []
            for variant_idx, image in enumerate(variants):
                for lang in lang_options:
                    for config in configs:
                        text_candidates = [
                            ("string", pytesseract.image_to_string(image, lang=lang, config=config)),
                            ("data", self._extract_lines_with_data(image, lang=lang, config=config)),
                        ]
                        for source_kind, text in text_candidates:
                            cleaned = self._cleanup_text(text)
                            if not cleaned:
                                continue
                            details = self._score_text_details(cleaned)
                            candidates.append(
                                {
                                    "score": int(details["score"]),
                                    "text": cleaned,
                                    "variant": variant_idx,
                                    "lang": lang,
                                    "config": config,
                                    "source": source_kind,
                                    "details": details,
                                }
                            )

            if not candidates:
                return ""

            candidates.sort(key=lambda item: int(item["score"]), reverse=True)
            merged = self._merge_top_candidates(
                [(int(item["score"]), str(item["text"])) for item in candidates],
                top_n=6,
            )
            final_text = self._cleanup_text(merged) or str(candidates[0]["text"])

            if self.enable_diagnostics:
                self._write_diagnostics(image_path, profile, candidates, final_text)

            return final_text
        except TesseractNotFoundError as exc:
            raise OCRConfigurationError(
                "Tesseract binary not found during OCR run. "
                "Install tesseract-ocr and ensure it is available in PATH."
            ) from exc

    @staticmethod
    def _image_profile(image: Image.Image) -> dict[str, float]:
        stat = ImageStat.Stat(image)
        brightness = float(stat.mean[0]) if stat.mean else 0.0
        contrast = float(stat.stddev[0]) if stat.stddev else 0.0
        aspect = float(image.width) / max(1.0, float(image.height))
        return {
            "brightness": brightness,
            "contrast": contrast,
            "aspect": aspect,
            "width": float(image.width),
            "height": float(image.height),
        }

    @staticmethod
    def _pick_ocr_configs(profile: dict[str, float]) -> list[str]:
        configs: list[str] = []
        aspect = profile.get("aspect", 1.0)
        contrast = profile.get("contrast", 30.0)

        if aspect >= 1.35:
            configs.append("--oem 3 --psm 4 -c preserve_interword_spaces=1")
        configs.append("--oem 3 --psm 6 -c preserve_interword_spaces=1")
        if contrast < 24:
            configs.append("--oem 3 --psm 11 -c preserve_interword_spaces=1")
        else:
            configs.append("--oem 3 --psm 11 -c preserve_interword_spaces=1")

        deduped: list[str] = []
        seen: set[str] = set()
        for config in configs:
            if config in seen:
                continue
            seen.add(config)
            deduped.append(config)
        return deduped

    def _merge_top_candidates(self, candidates: list[tuple[int, str]], top_n: int = 4) -> str:
        seen: set[str] = set()
        merged_lines: list[str] = []
        for _score, text in candidates[:top_n]:
            for raw in text.splitlines():
                line = self._cleanup_line(raw)
                if not line:
                    continue
                norm = re.sub(r"\s+", " ", line.lower())
                if norm in seen:
                    continue
                seen.add(norm)
                merged_lines.append(line)
        return "\n".join(merged_lines)

    def _autorotate(self, image: Image.Image, lang: str) -> Image.Image:
        # Use OSD to normalize 90/180/270 rotations that are common in chat photos.
        try:
            osd = pytesseract.image_to_osd(image, lang=lang, config="--psm 0")
            match = re.search(r"Rotate:\s+(\d+)", osd)
            if not match:
                return image
            rotate = int(match.group(1))
            if rotate in {90, 180, 270}:
                return image.rotate(-rotate, expand=True, fillcolor=255)
        except Exception:
            return image
        return image

    def _build_variants(self, image: Image.Image, profile: dict[str, float]) -> list[Image.Image]:
        normalized = ImageOps.autocontrast(image, cutoff=1)
        brightness = profile.get("brightness", 150.0)
        contrast_metric = profile.get("contrast", 30.0)

        min_width = 900
        if profile.get("width", 900.0) < 700:
            min_width = 980

        if brightness < 95:
            brightness_gain = 1.24
            primary_threshold = 168
            secondary_threshold = 192
        elif brightness > 200:
            brightness_gain = 0.95
            primary_threshold = 186
            secondary_threshold = 208
        else:
            brightness_gain = 1.08
            primary_threshold = int(min(205, max(168, brightness + 20)))
            secondary_threshold = int(min(225, max(185, brightness + 38)))

        if contrast_metric < 24:
            contrast_a, contrast_b = 2.5, 2.8
            sharpness_a, sharpness_b = 2.2, 2.4
        else:
            contrast_a, contrast_b = 2.0, 2.3
            sharpness_a, sharpness_b = 1.9, 2.1

        return [
            self._preprocess(
                normalized,
                threshold=None,
                min_width=min_width,
                contrast=contrast_a,
                sharpness=sharpness_a,
                brightness=brightness_gain,
            ),
            self._preprocess(
                normalized,
                threshold=primary_threshold,
                min_width=min_width,
                contrast=contrast_b,
                sharpness=sharpness_b,
                brightness=brightness_gain,
            ),
            self._preprocess(
                normalized,
                threshold=secondary_threshold,
                min_width=min_width + 40,
                contrast=contrast_a,
                sharpness=sharpness_b,
                brightness=brightness_gain,
            ),
        ]

    def _crop_receipt_region(self, image: Image.Image, lang: str) -> Image.Image:
        if image.width < 240 or image.height < 240:
            return image

        sample = image.copy()
        if sample.width > 1400:
            ratio = 1400 / sample.width
            sample = sample.resize((1400, max(1, int(sample.height * ratio))), Image.Resampling.LANCZOS)

        scale_x = image.width / sample.width
        scale_y = image.height / sample.height

        data = pytesseract.image_to_data(
            sample,
            lang=lang,
            config="--oem 3 --psm 11",
            output_type=Output.DICT,
        )

        boxes: list[tuple[int, int, int, int]] = []
        total = len(data.get("text", []))
        for idx in range(total):
            token = (data["text"][idx] or "").strip()
            if not token or not ALNUM_RE.search(token):
                continue
            conf = self._parse_conf(data["conf"][idx])
            if conf < 20.0:
                continue
            left = int(data["left"][idx])
            top = int(data["top"][idx])
            width = int(data["width"][idx])
            height = int(data["height"][idx])
            if width <= 0 or height <= 0:
                continue
            boxes.append((left, top, left + width, top + height))

        if len(boxes) < 10:
            return image

        clusters = self._cluster_boxes_by_rows(boxes)
        if not clusters:
            return image

        best = max(clusters, key=lambda cluster: self._score_cluster(cluster, sample.width, sample.height))
        left, top, right, bottom, count = best
        if count < 8:
            return image

        margin_x = max(14, int((right - left) * 0.08))
        margin_y = max(18, int((bottom - top) * 0.06))

        crop_box = (
            max(0, int((left - margin_x) * scale_x)),
            max(0, int((top - margin_y) * scale_y)),
            min(image.width, int((right + margin_x) * scale_x)),
            min(image.height, int((bottom + margin_y) * scale_y)),
        )

        crop_width = crop_box[2] - crop_box[0]
        crop_height = crop_box[3] - crop_box[1]
        if crop_width < int(image.width * 0.18) or crop_height < int(image.height * 0.22):
            return image

        return image.crop(crop_box)

    def _cluster_boxes_by_rows(self, boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int, int]]:
        ordered = sorted(boxes, key=lambda box: box[1])
        heights = [box[3] - box[1] for box in ordered]
        median_height = self._median(heights)
        gap_threshold = max(24, int(median_height * 1.6))

        clusters: list[tuple[int, int, int, int, int]] = []
        cur_left = cur_top = cur_right = cur_bottom = 0
        cur_count = 0

        for left, top, right, bottom in ordered:
            if cur_count == 0:
                cur_left, cur_top, cur_right, cur_bottom = left, top, right, bottom
                cur_count = 1
                continue

            gap = top - cur_bottom
            if gap <= gap_threshold:
                cur_left = min(cur_left, left)
                cur_top = min(cur_top, top)
                cur_right = max(cur_right, right)
                cur_bottom = max(cur_bottom, bottom)
                cur_count += 1
            else:
                clusters.append((cur_left, cur_top, cur_right, cur_bottom, cur_count))
                cur_left, cur_top, cur_right, cur_bottom = left, top, right, bottom
                cur_count = 1

        if cur_count:
            clusters.append((cur_left, cur_top, cur_right, cur_bottom, cur_count))

        return clusters

    @staticmethod
    def _score_cluster(cluster: tuple[int, int, int, int, int], image_width: int, image_height: int) -> float:
        left, top, right, bottom, count = cluster
        width = max(1, right - left)
        height = max(1, bottom - top)
        aspect = height / width
        center_y = (top + bottom) / 2
        center_penalty = abs(center_y - (image_height / 2)) / max(1, image_height)
        wide_penalty = 3.0 if width > image_width * 0.9 else 0.0
        bottom_penalty = 2.0 if top > image_height * 0.72 else 0.0
        return (count * 2.5) + (aspect * 6.0) - (center_penalty * 3.0) - wide_penalty - bottom_penalty

    @staticmethod
    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[middle])
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def _extract_lines_with_data(self, image: Image.Image, lang: str, config: str) -> str:
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=Output.DICT,
        )
        lines: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
        tops: dict[tuple[int, int, int], int] = {}

        total = len(data.get("text", []))
        for idx in range(total):
            token = self._normalize_token((data["text"][idx] or "").strip())
            if not token:
                continue

            conf = self._parse_conf(data["conf"][idx])
            if conf < 14.0:
                continue

            key = (data["block_num"][idx], data["par_num"][idx], data["line_num"][idx])
            left = int(data["left"][idx])
            top = int(data["top"][idx])
            lines.setdefault(key, []).append((left, token))
            tops[key] = min(top, tops.get(key, top))

        ordered_keys = sorted(lines.keys(), key=lambda key: (tops.get(key, 0), key[0], key[1], key[2]))
        assembled: list[str] = []
        for key in ordered_keys:
            words = sorted(lines[key], key=lambda item: item[0])
            line = self._cleanup_line(" ".join(word for _, word in words))
            if line:
                assembled.append(line)

        return "\n".join(assembled)

    @staticmethod
    def _parse_conf(raw: str) -> float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return -1.0

    def _preprocess(
        self,
        image: Image.Image,
        threshold: int | None,
        min_width: int,
        contrast: float,
        sharpness: float,
        brightness: float,
    ) -> Image.Image:
        # Pre-processing pipeline tuned for receipt photos from chat apps.
        prepared = image.filter(ImageFilter.MedianFilter(size=3))
        prepared = ImageEnhance.Contrast(prepared).enhance(contrast)
        prepared = ImageEnhance.Sharpness(prepared).enhance(sharpness)
        prepared = ImageEnhance.Brightness(prepared).enhance(brightness)

        if prepared.width < min_width:
            scale_factor = min_width / prepared.width
            new_size = (int(prepared.width * scale_factor), int(prepared.height * scale_factor))
            prepared = prepared.resize(new_size, Image.Resampling.LANCZOS)

        if threshold is None:
            return prepared

        threshold_value = int(threshold)
        lut = [255 if value > threshold_value else 0 for value in range(256)]
        return prepared.point(lut)

    def _cleanup_text(self, text: str) -> str:
        seen: set[str] = set()
        lines: list[str] = []
        for raw in text.splitlines():
            line = self._cleanup_line(raw)
            if not line:
                continue
            norm = re.sub(r"\s+", " ", line.lower())
            if norm in seen:
                continue
            seen.add(norm)
            lines.append(line)
        return "\n".join(lines)

    def _cleanup_line(self, raw: str) -> str:
        line = raw.replace("|", " ").replace("¦", " ").replace("—", "-").replace("–", "-")
        line = CLEAN_LINE_RE.sub(" ", line)
        line = re.sub(r"\s+", " ", line).strip(" -_=~")
        if not line:
            return ""

        line = re.sub(
            r"(\d{1,4})\s+(\d{2})(?=\s*(?:[A-Za-zА-Яа-яІіЇїЄєҐґ]|$))",
            r"\1,\2",
            line,
        )
        line = re.sub(r"([.,]){2,}", r"\1", line)

        if self._is_noise_line(line):
            return ""
        return line

    @staticmethod
    def _normalize_token(token: str) -> str:
        token = token.replace("`", "'").replace("’", "'")
        token = re.sub(r"^[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ]+", "", token)
        token = re.sub(r"[^0-9A-Za-zА-Яа-яІіЇїЄєҐґ.,/%+\-]+$", "", token)
        return token

    @staticmethod
    def _is_noise_line(line: str) -> bool:
        if len(line) < 2:
            return True

        letters = sum(ch.isalpha() for ch in line)
        digits = sum(ch.isdigit() for ch in line)
        if letters == 0 and digits == 0:
            return True

        if letters == 0 and not re.search(r"\d+[.,]\d{2}", line):
            return digits < 4

        lower = line.lower()
        if re.search(r"[bcdfghjklmnpqrstvwxyz]{7,}|[бвгджзйклмнпрстфхцчшщ]{7,}", lower):
            return True
        return False

    @staticmethod
    def _score_text(text: str) -> int:
        details = OCRService._score_text_details(text)
        return int(details["score"])

    @staticmethod
    def _score_text_details(text: str) -> dict[str, int]:
        # Favor outputs that look like receipt lines with totals and item prices,
        # and penalize gibberish-like lines aggressively.
        letters = sum(ch.isalpha() for ch in text)
        digits = sum(ch.isdigit() for ch in text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        line_count = len(lines)
        item_like_lines = 0
        qty_like_lines = 0
        total_like_lines = 0
        noisy_lines = 0
        for line in lines:
            lower = line.lower()
            if PRICE_LINE_RE.search(lower):
                item_like_lines += 1
            if QTY_PRICE_RE.search(lower):
                qty_like_lines += 1
            if any(token in lower for token in TOTAL_TOKENS):
                total_like_lines += 1
            if re.search(r"[bcdfghjklmnpqrstvwxyz]{7,}|[бвгджзйклмнпрстфхцчшщ]{7,}", lower):
                noisy_lines += 1

        score = (
            letters
            + (digits * 4)
            + (line_count * 3)
            + (item_like_lines * 14)
            + (qty_like_lines * 8)
            + (total_like_lines * 9)
            - (noisy_lines * 10)
        )

        return {
            "score": int(score),
            "letters": int(letters),
            "digits": int(digits),
            "line_count": int(line_count),
            "item_like_lines": int(item_like_lines),
            "qty_like_lines": int(qty_like_lines),
            "total_like_lines": int(total_like_lines),
            "noisy_lines": int(noisy_lines),
        }

    def _write_diagnostics(
        self,
        image_path: Path,
        profile: dict[str, float],
        candidates: list[dict],
        final_text: str,
    ) -> None:
        if not self.enable_diagnostics:
            return

        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"
        top_candidates = []
        for item in candidates[:10]:
            top_candidates.append(
                {
                    "score": item.get("score"),
                    "variant": item.get("variant"),
                    "lang": item.get("lang"),
                    "config": item.get("config"),
                    "source": item.get("source"),
                    "details": item.get("details"),
                    "text": item.get("text"),
                }
            )

        payload = {
            "run_id": run_id,
            "image_name": image_path.name,
            "profile": profile,
            "top_candidates": top_candidates,
            "final_text": final_text,
        }

        json_path = self.diagnostics_dir / f"{run_id}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
