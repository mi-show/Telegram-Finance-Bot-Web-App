import tempfile
from decimal import Decimal
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.exc import SQLAlchemyError

from .common import route_ctx as ctx
from ..services.category_service import localize_category, localize_subcategory

router = Router()


def _localized_category_display(category: str, subcategory: str | None, lang: str) -> str:
    category_label = localize_category(category, lang) or category
    if not subcategory:
        return category_label

    subcategory_label = localize_subcategory(category, subcategory, lang) or subcategory
    return f"{category_label}({subcategory_label})"


def _cache_ocr_payload(token: str, payload: dict):
    ctx.pending_receipts.set(token, payload)


def _pop_ocr_payload(token: str) -> dict | None:
    payload = ctx.pending_receipts.get(token)
    if payload:
        ctx.pending_receipts.delete(token)
        cleanup_tokens = payload.get("_cleanup") if isinstance(payload, dict) else None
        if cleanup_tokens:
            for cleanup_token in cleanup_tokens:
                ctx.pending_receipts.delete(cleanup_token)
                ctx.pending_quick_records.delete(cleanup_token)
    return payload


@router.callback_query(F.data.startswith("ocr_unknown:"))
async def ocr_unknown_start(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token = callback.data.split(":", 1)[1]
    pending = ctx.pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть чек знову.",
                "ru": "Данные устарели, отправьте чек снова.",
                "en": "Data expired, send receipt again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = ctx._normalize_lang(pending.get("language", lang))

    categories = pending.get("categories", [])
    if not categories:
        await callback.answer(
            {
                "uk": "Немає варіантів категорій.",
                "ru": "Нет вариантов категорий.",
                "en": "No category options.",
            }.get(lang, "No category options."),
            show_alert=True,
        )
        return

    description = pending.get("description", "")
    amount = pending.get("amount")
    await callback.message.answer(  # type: ignore
        {
            "uk": (
                f"Невідома позиція:\n{description} — {ctx._fmt_amount(amount)} UAH\n\n"
                "Оберіть категорію вручну:"
            ),
            "ru": (
                f"Неизвестная позиция:\n{description} — {ctx._fmt_amount(amount)} UAH\n\n"
                "Выберите категорию вручную:"
            ),
            "en": (
                f"Unknown item:\n{description} — {ctx._fmt_amount(amount)} UAH\n\n"
                "Choose category manually:"
            ),
        }.get(lang, ""),
        reply_markup=ctx._quick_category_keyboard(token, categories, page=0, lang=lang),
    )
    await callback.answer()


@router.message(F.photo)
async def handle_receipt_photo(message: Message, bot: Bot):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    try:
        photo = message.photo[-1]  # type: ignore

        file_info = await bot.get_file(photo.file_id)
        file_bytesio = await bot.download(file_info)

        if hasattr(file_bytesio, "read"):
            file_bytes: bytes = file_bytesio.read()  # type: ignore
        else:
            file_bytes = file_bytesio  # type: ignore

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(file_bytes)
            path = Path(tmp.name)

        text = await ctx.ocr_service.extract_text(path)

        async with ctx.get_session() as session:
            lang = await ctx._prepare_classifier(session, message.from_user.id)  # type: ignore

        parsed = ctx.receipt_parser.parse(text)
        amount = parsed.amount
        items = parsed.items
        when = parsed.date or ctx.date.today()
        description = parsed.description or parsed.merchant or "Чек"
        receipt_low_confidence = (
            parsed.overall_confidence < ctx.MIN_RECEIPT_OVERALL_CONFIDENCE_AUTO
            or parsed.amount_confidence < ctx.MIN_AMOUNT_CONFIDENCE_AUTO
        )

        item_rows: list[dict] = []
        for item in items:
            cat, subcat, confidence, source = ctx.user_classifier.predict_with_user_context_confidence(
                item.name,
                message.from_user.id,  # type: ignore
                language=lang,
            )
            recognized = (
                ctx._is_item_confidently_recognized(item.name, cat, source, confidence)
                and item.confidence >= ctx.MIN_ITEM_CONFIDENCE_AUTO
                and not receipt_low_confidence
            )
            item_rows.append(
                {
                    "name": item.name,
                    "price": item.price,
                    "quantity": item.quantity,
                    "category": cat,
                    "subcategory": subcat,
                    "source": source,
                    "confidence": confidence,
                    "ocr_confidence": item.confidence,
                    "recognized": recognized,
                }
            )

        distinct_cats = {row["category"] for row in item_rows if row.get("category") and row.get("recognized")}
        total_from_items = sum((row["price"] or Decimal("0")) for row in item_rows) if item_rows else None
        if amount is None and total_from_items:
            amount = total_from_items

        if amount is None:
            await message.answer(
                {
                    "uk": "❌ Не вдалося знайти суму на чеку. Спробуйте інше фото.",
                    "ru": "❌ Не удалось найти сумму на чеке. Попробуйте другое фото.",
                    "en": "❌ Could not find total amount on receipt. Try another photo.",
                }.get(lang, "❌ Could not parse amount.")
            )
            path.unlink(missing_ok=True)
            return

        if lang == "uk":
            uncertain_fallback = "❗ Інше"
        elif lang == "ru":
            uncertain_fallback = "❗ Другое"
        else:
            uncertain_fallback = "Other"

        dominant_cat = ctx._dominant_category(list(distinct_cats), fallback=uncertain_fallback)

        single_token = ctx.secrets.token_hex(8)
        single_payload = {
            "records": [
                {
                    "type": "expense",
                    "category": dominant_cat,
                    "amount": str(amount),
                    "currency": "UAH",
                    "happened_on": when.isoformat(),
                    "description": f"{description} (OCR, {len(item_rows) or 1} поз.)",
                }
            ],
            "items": item_rows,
            "_cleanup": [],
        }

        split_records = []
        if not receipt_low_confidence:
            for row in item_rows:
                if row["price"] is None or not row.get("recognized"):
                    continue
                split_records.append(
                    {
                        "type": "expense",
                        "category": row["category"],
                        "subcategory": row.get("subcategory"),
                        "amount": str(row["price"]),
                        "currency": "UAH",
                        "happened_on": when.isoformat(),
                        "description": row["name"],
                    }
                )

        unknown_candidates = [
            row for row in item_rows if row.get("price") is not None and not row.get("recognized")
        ]
        unknown_entries: list[dict] = []
        for row in unknown_candidates:
            token = ctx.secrets.token_hex(8)
            categories = ctx._build_quick_category_candidates(
                row["name"],
                message.from_user.id,  # type: ignore
                lang,
                row.get("category") or "Other",
            )
            ctx.pending_quick_records.set(
                token,
                {
                    "description": row["name"],
                    "amount": row["price"],
                    "happened_on": when,
                    "language": lang,
                    "categories": categories,
                    "selected_category": None,
                    "selected_subcategory": None,
                    "predicted_subcategory": row.get("subcategory"),
                    "category_page": 0,
                },
            )
            unknown_entries.append(
                {
                    "token": token,
                    "name": row["name"],
                    "price": row["price"],
                    "source": row.get("source"),
                    "confidence": row.get("confidence"),
                }
            )

        split_token = ctx.secrets.token_hex(8) if split_records else None
        split_payload = None
        if split_records:
            split_payload = {
                "records": split_records,
                "items": item_rows,
                "unknown_entries": unknown_entries,
                "_cleanup": [],
            }
        single_payload["unknown_entries"] = unknown_entries

        linked_tokens = [single_token]
        if split_token:
            linked_tokens.append(split_token)
        single_payload["_cleanup"] = linked_tokens
        if split_payload:
            split_payload["_cleanup"] = linked_tokens

        _cache_ocr_payload(single_token, single_payload)
        if split_token and split_payload:
            _cache_ocr_payload(split_token, split_payload)

        kb = InlineKeyboardBuilder()
        kb.button(
            text={
                "uk": f"💾 1 запис ({ctx._fmt_amount(amount)})",
                "ru": f"💾 1 запись ({ctx._fmt_amount(amount)})",
                "en": f"💾 1 record ({ctx._fmt_amount(amount)})",
            }.get(lang, f"💾 1 record ({ctx._fmt_amount(amount)})"),
            callback_data=f"ocr_save:{single_token}",
        )
        if split_token:
            kb.button(
                text={
                    "uk": f"💾 За позиціями ({len(split_records)})",
                    "ru": f"💾 По позициям ({len(split_records)})",
                    "en": f"💾 By items ({len(split_records)})",
                }.get(lang, f"💾 By items ({len(split_records)})"),
                callback_data=f"ocr_save:{split_token}",
            )
        kb.button(
            text={"uk": "🗑 Скасувати", "ru": "🗑 Отмена", "en": "🗑 Cancel"}.get(lang, "🗑 Cancel"),
            callback_data=f"ocr_cancel:{single_token}",
        )
        kb.adjust(2 if not split_token else 3)

        grouped = ctx._group_recognized_items(item_rows)
        grouped_lines = []
        for (cat, subcat), details in sorted(grouped.items(), key=lambda x: x[1]["total"], reverse=True):
            cat_display = _localized_category_display(cat, subcat, lang)
            grouped_lines.append(
                f"- {cat_display}: {ctx._fmt_amount(details['total'])} ({details['count']} поз.)"
            )

        unknown_lines = []
        for idx, row in enumerate(unknown_entries[:6], start=1):
            conf = row.get("confidence")
            conf_txt = f", conf={conf:.2f}" if isinstance(conf, float) else ""
            unknown_lines.append(
                f"{idx}. {row['name']} — {ctx._fmt_amount(row['price'])} [{row.get('source', '?')}{conf_txt}]"
            )

        quality_hint = ""
        if receipt_low_confidence:
            quality_hint = {
                "uk": (
                    "\n\n⚠️ Низька впевненість OCR. Я не буду автозберігати позиції по категоріях, "
                    "краще вручну підтвердити невідомі пункти."
                ),
                "ru": (
                    "\n\n⚠️ Низкая уверенность OCR. Я не буду автосохранять позиции по категориям, "
                    "лучше вручную подтвердить неизвестные пункты."
                ),
                "en": (
                    "\n\n⚠️ Low OCR confidence. I will not auto-save itemized categories, "
                    "please confirm unknown entries manually."
                ),
            }.get(lang, "")

        known_block = "\n".join(grouped_lines) if grouped_lines else {
            "uk": "Немає впевнено розпізнаних позицій.",
            "ru": "Нет уверенно распознанных позиций.",
            "en": "No confidently recognized items.",
        }.get(lang, "No confidently recognized items.")
        unknown_block = "\n".join(unknown_lines) if unknown_lines else {
            "uk": "Немає",
            "ru": "Нет",
            "en": "None",
        }.get(lang, "None")

        await message.answer(
            {
                "uk": (
                    "Знайшов чек:\n"
                    f"Магазин: {parsed.merchant or '-'}\n"
                    f"Сума: {ctx._fmt_amount(amount)}\n"
                    f"Дата: {when}\n"
                    f"\nРозпізнані категорії:\n{known_block}\n"
                    f"\nНевідомі позиції:\n{unknown_block}\n"
                    "\nЩо зберегти?"
                    f"{quality_hint}"
                ),
                "ru": (
                    "Нашел чек:\n"
                    f"Магазин: {parsed.merchant or '-'}\n"
                    f"Сумма: {ctx._fmt_amount(amount)}\n"
                    f"Дата: {when}\n"
                    f"\nРаспознанные категории:\n{known_block}\n"
                    f"\nНеизвестные позиции:\n{unknown_block}\n"
                    "\nЧто сохранить?"
                    f"{quality_hint}"
                ),
                "en": (
                    "Receipt detected:\n"
                    f"Store: {parsed.merchant or '-'}\n"
                    f"Amount: {ctx._fmt_amount(amount)}\n"
                    f"Date: {when}\n"
                    f"\nRecognized categories:\n{known_block}\n"
                    f"\nUnknown items:\n{unknown_block}\n"
                    "\nWhat should be saved?"
                    f"{quality_hint}"
                ),
            }.get(lang, ""),
            reply_markup=kb.as_markup(),
        )
        path.unlink(missing_ok=True)
    except ctx.OCRConfigurationError as exc:
        ctx.logger.error(f"OCR is not configured: {exc}", exc_info=True)
        await message.answer(
            {
                "uk": "OCR не налаштовано: встановіть tesseract-ocr і мовні пакети (eng/rus/ukr).",
                "ru": "OCR не настроен: установите tesseract-ocr и языковые пакеты (eng/rus/ukr).",
                "en": "OCR is not configured: install tesseract-ocr and language packs (eng/rus/ukr).",
            }.get(lang, "OCR is not configured.")
        )
    except Exception as exc:
        ctx.logger.exception(f"OCR handler error: {exc}")
        await message.answer(
            {
                "uk": "❌ Не вдалося обробити фото. Спробуйте ще раз.",
                "ru": "❌ Не удалось обработать фото. Попробуйте еще раз.",
                "en": "❌ Could not process photo. Please try again.",
            }.get(lang, "❌ Could not process photo.")
        )


@router.callback_query(F.data.startswith("ocr_save:"))
async def ocr_save(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return
    token = callback.data.split(":", 1)[1]  # type: ignore
    payload = _pop_ocr_payload(token)
    if not payload:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть фото ще раз.",
                "ru": "Данные устарели, пришлите фото еще раз.",
                "en": "Data expired, send photo again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    last_payload = None
    try:
        records_payload = payload.get("records") if isinstance(payload, dict) else None
        if not records_payload:
            records_payload = [payload]

        async with ctx.get_session() as session:
            service = ctx.RecordService(session, callback.from_user.id)
            default_currency = await ctx._resolve_user_currency(session, callback.from_user.id)  # type: ignore
            saved = []
            for rec in records_payload:
                last_payload = ctx.RecordCreate(
                    type=rec["type"],
                    category=rec["category"],
                    subcategory=rec.get("subcategory"),
                    amount=Decimal(rec["amount"]),
                    currency=(rec.get("currency") or default_currency),
                    happened_on=ctx.date.fromisoformat(rec["happened_on"]),
                    description=rec.get("description"),
                )
                record = await service.add(last_payload)
                saved.append(record)
            await session.commit()

        unknown_entries = payload.get("unknown_entries", []) if isinstance(payload, dict) else []

        ctx.clear_stats_cache()
        if callback.message:
            if len(saved) == 1:
                rec = saved[0]
                cat_display = _localized_category_display(rec.category, rec.subcategory, lang)
                await callback.message.answer(  # type: ignore
                    {
                        "uk": f"✅ Збережено {cat_display}: {rec.amount} {rec.currency} від {rec.happened_on}",
                        "ru": f"✅ Сохранил {cat_display}: {rec.amount} {rec.currency} от {rec.happened_on}",
                        "en": f"✅ Saved {cat_display}: {rec.amount} {rec.currency} on {rec.happened_on}",
                    }.get(lang, "")
                )
            else:
                text_lines = [
                    {
                        "uk": "✅ Збережено позиції:",
                        "ru": "✅ Сохранил позиции:",
                        "en": "✅ Saved items:",
                    }.get(lang, "✅ Saved items:"),
                    *[
                        f"- {_localized_category_display(r.category, r.subcategory, lang)}: {r.amount} {r.currency}"
                        for r in saved
                    ],
                ]
                await callback.message.answer("\n".join(text_lines))  # type: ignore

            if unknown_entries:
                kb = InlineKeyboardBuilder()
                for idx, row in enumerate(unknown_entries, start=1):
                    kb.button(
                        text=f"❓ {idx}. {row['name']} — {ctx._fmt_amount(row['price'])}",
                        callback_data=f"ocr_unknown:{row['token']}",
                    )
                kb.adjust(1)
                await callback.message.answer(  # type: ignore
                    {
                        "uk": "Я не впевнений щодо частини позицій. Натисніть на кожну, щоб обрати категорію та запам'ятати на майбутнє:",
                        "ru": "Я не уверен в части позиций. Нажмите на каждую, чтобы выбрать категорию и запомнить её на будущее:",
                        "en": "I am unsure about some items. Tap each one to choose category and remember it for future:",
                    }.get(lang, ""),
                    reply_markup=kb.as_markup(),
                )

        await callback.answer()
    except ValueError as exc:
        ctx.logger.warning(f"OCR save validation error: {exc}")
        if callback.message:
            if last_payload is not None and ctx._is_duplicate_record_error(exc):
                token = ctx._stash_duplicate_record_payload(callback.from_user.id, last_payload)  # type: ignore
                await callback.message.answer(  # type: ignore
                    f"⚠️ {exc}",
                    reply_markup=ctx._force_duplicate_add_kb(lang, token),
                )
            else:
                await callback.message.answer(f"⚠️ {exc}")  # type: ignore
        await callback.answer()
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"OCR save DB error: {exc}")
        if callback.message:
            await callback.message.answer(  # type: ignore
                {
                    "uk": "❌ Помилка бази даних. Спробуйте знову.",
                    "ru": "❌ Ошибка базы данных. Попробуйте снова.",
                    "en": "❌ Database error. Try again.",
                }.get(lang, "❌ Database error.")
            )
        await callback.answer()
    except Exception as exc:
        ctx.logger.exception(f"OCR save unexpected error: {exc}")
        if callback.message:
            await callback.message.answer(  # type: ignore
                {
                    "uk": f"❌ Помилка: {exc}",
                    "ru": f"❌ Ошибка: {exc}",
                    "en": f"❌ Error: {exc}",
                }.get(lang, f"❌ Error: {exc}")
            )
        await callback.answer()


@router.callback_query(F.data.startswith("ocr_cancel:"))
async def ocr_cancel(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data or not callback.message:  # type: ignore
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return
    token = callback.data.split(":", 1)[1]  # type: ignore
    _pop_ocr_payload(token)
    await callback.message.answer(  # type: ignore
        {"uk": "🛑 Скасовано.", "ru": "🛑 Отменено.", "en": "🛑 Cancelled."}.get(lang, "🛑 Cancelled.")
    )
    await callback.answer()
