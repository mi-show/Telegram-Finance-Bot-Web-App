import secrets
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import SQLAlchemyError

from .common import route_ctx as ctx
from .common import format_limit_status
from ..services.category_service import localize_category, localize_subcategory

router = Router()


def _localized_category_display(category: str, subcategory: str | None, lang: str) -> str:
    category_label = localize_category(category, lang) or category
    if not subcategory:
        return category_label

    subcategory_label = localize_subcategory(category, subcategory, lang) or subcategory
    return f"{category_label}({subcategory_label})"


@router.message(Command("add"))
async def cmd_add(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    parts = message.text.split(maxsplit=5)  # type: ignore
    if len(parts) < 5:
        await message.answer(
            {
                "uk": f"Формат: /add <income|expense> <category> <amount> <{ctx.settings.date_format}> [note]",
                "ru": f"Формат: /add <income|expense> <category> <amount> <{ctx.settings.date_format}> [note]",
                "en": f"Format: /add <income|expense> <category> <amount> <{ctx.settings.date_format}> [note]",
            }.get(lang, "")
        )
        return

    _, type_raw, category_input, amount_raw, date_raw, *rest = parts
    description = rest[0] if rest else None

    try:
        amount = Decimal(amount_raw)
        happened_on = ctx._parse_date(date_raw)
    except (InvalidOperation, ValueError) as exc:
        ctx.logger.exception(f"Amount/date parsing error: {exc}")
        await message.answer(
            {
                "uk": "⚠️ Помилка: неправильно вказано суму або дату",
                "ru": "⚠️ Ошибка: неправильно указана сумма или дата",
                "en": "⚠️ Error: invalid amount or date",
            }.get(lang, "⚠️ Error")
        )
        return

    if type_raw not in ("income", "expense"):
        await message.answer(
            {
                "uk": "⚠️ Тип має бути income або expense",
                "ru": "⚠️ Тип должен быть income или expense",
                "en": "⚠️ Type must be income or expense",
            }.get(lang, "⚠️ Type error")
        )
        return

    lang = "uk"
    try:
        async with ctx.get_session() as session:
            user_repo = ctx.UserRepository(session)
            lang = (await user_repo.get_language(message.from_user.id) or "uk").lower()  # type: ignore
            if lang not in ctx.SUPPORTED_LANGUAGES:
                lang = "uk"
    except Exception:
        pass

    if ctx.validate_category(category_input, lang):
        payload = None
        try:
            async with ctx.get_session() as session:
                currency = await ctx._resolve_user_currency(session, message.from_user.id)  # type: ignore
                payload = ctx.RecordCreate(
                    type=type_raw,  # type: ignore
                    category=category_input,
                    subcategory=None,
                    amount=amount,
                    currency=currency,
                    happened_on=happened_on,
                    description=description,
                )
                service = ctx.RecordService(session, message.from_user.id)  # type: ignore
                record = await service.add(payload)
                await session.commit()

                base = {
                    "uk": f"✅ Додано {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} від {record.happened_on}",
                    "ru": f"✅ Добавлено {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} от {record.happened_on}",
                    "en": f"✅ Added {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} on {record.happened_on}",
                }.get(lang, "")

                try:
                    suffix = await format_limit_status(
                        session,
                        message.from_user.id,
                        record.user_id,
                        record.category,
                        record.subcategory,
                        lang,
                        record.currency,
                    )
                except Exception:
                    suffix = ""

            ctx.clear_stats_cache()
            await message.answer(base + (suffix or ""))
        except ValueError as exc:
            ctx.logger.warning(f"Validation error during add: {exc}")
            if payload is not None and ctx._is_duplicate_record_error(exc):
                token = ctx._stash_duplicate_record_payload(message.from_user.id, payload)  # type: ignore
                await message.answer(
                    f"⚠️ {exc}",
                    reply_markup=ctx._force_duplicate_add_kb(lang, token),
                )
            else:
                await message.answer(f"⚠️ {exc}")
        except SQLAlchemyError as exc:
            ctx.logger.exception(f"Database error during add: {exc}")
            await message.answer(
                {
                    "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                    "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                    "en": "❌ Database error. Try later.",
                }.get(lang, "❌ Database error.")
            )
        except Exception as exc:
            ctx.logger.exception(f"Unexpected error during add: {exc}")
            await message.answer(
                {
                    "uk": f"❌ Помилка: {exc}",
                    "ru": f"❌ Ошибка: {exc}",
                    "en": f"❌ Error: {exc}",
                }.get(lang, f"❌ Error: {exc}")
            )
        return

    closest_cat, match_score = ctx.find_closest_category(category_input, lang)

    token = secrets.token_hex(8)
    ctx.pending_add_records.set(
        token,
        {
            "type": type_raw,
            "amount": amount,
            "happened_on": happened_on,
            "description": description,
            "original_input": category_input,
        },
    )

    kb = ctx.InlineKeyboardBuilder()

    if closest_cat and match_score > 0.5:
        kb.button(text=f"✓ {closest_cat} ({int(match_score*100)}%)", callback_data=f"add_cat:{token}:{closest_cat}")

    available_cats = ctx.get_categories_for_lang(lang)
    for cat in available_cats:
        if cat != closest_cat:
            kb.button(text=cat, callback_data=f"add_cat:{token}:{cat}")

    kb.adjust(1)

    await message.answer(
        {
            "uk": f"❓ Категорію '{category_input}' не знайдено.\n\nОберіть зі списку:",
            "ru": f"❓ Категория '{category_input}' не найдена.\n\nВыберите из списка:",
            "en": f"❓ Category '{category_input}' was not found.\n\nChoose one from the list:",
        }.get(lang, ""),
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("add_cat:"))
async def add_category_selected(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token, category = parts[1], parts[2]
    record_data = ctx.pending_add_records.get(token)

    if not record_data:
        await callback.answer(
            {
                "uk": "Дані застаріли, використайте /add знову.",
                "ru": "Данные устарели, используйте /add снова.",
                "en": "Data expired, use /add again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = "uk"
    try:
        async with ctx.get_session() as session:
            user_repo = ctx.UserRepository(session)
            lang = (await user_repo.get_language(callback.from_user.id) or "uk").lower()
    except Exception:
        pass

    subcats = ctx.get_subcategories_for_category(category, lang)

    if not subcats:
        payload = None
        try:
            async with ctx.get_session() as session:
                currency = await ctx._resolve_user_currency(session, callback.from_user.id)  # type: ignore
                payload = ctx.RecordCreate(
                    type=record_data["type"],  # type: ignore
                    category=category,
                    subcategory=None,
                    amount=record_data["amount"],
                    currency=currency,
                    happened_on=record_data["happened_on"],
                    description=record_data["description"],
                )
                service = ctx.RecordService(session, callback.from_user.id)  # type: ignore
                record = await service.add(payload)
                await session.commit()

                base = {
                    "uk": f"✅ Додано {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} від {record.happened_on}",
                    "ru": f"✅ Добавлено {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} от {record.happened_on}",
                    "en": f"✅ Added {record.type.value}: {_localized_category_display(record.category, record.subcategory, lang)} {record.amount} {record.currency} on {record.happened_on}",
                }.get(lang, "")

                try:
                    suffix = await format_limit_status(
                        session,
                        callback.from_user.id,
                        record.user_id,
                        record.category,
                        record.subcategory,
                        lang,
                        record.currency,
                    )
                except Exception:
                    suffix = ""

            ctx.clear_stats_cache()
            ctx.pending_add_records.delete(token)
            await callback.message.edit_text(base + (suffix or ""))
            await callback.answer()
        except ValueError as exc:
            if payload is not None and ctx._is_duplicate_record_error(exc):
                token_dup = ctx._stash_duplicate_record_payload(callback.from_user.id, payload)  # type: ignore
                if callback.message:
                    await callback.message.answer(  # type: ignore
                        f"⚠️ {exc}",
                        reply_markup=ctx._force_duplicate_add_kb(lang, token_dup),
                    )
                await callback.answer()
            else:
                await callback.answer(
                    {
                        "uk": f"❌ Помилка: {exc}",
                        "ru": f"❌ Ошибка: {exc}",
                        "en": f"❌ Error: {exc}",
                    }.get(lang, f"❌ Error: {exc}"),
                    show_alert=True,
                )
        except Exception as exc:
            ctx.logger.exception(f"Add category save error: {exc}")
            await callback.answer(
                {
                    "uk": f"❌ Помилка: {exc}",
                    "ru": f"❌ Ошибка: {exc}",
                    "en": f"❌ Error: {exc}",
                }.get(lang, f"❌ Error: {exc}"),
                show_alert=True,
            )
        return

    kb = ctx.InlineKeyboardBuilder()
    for subcat in subcats:
        kb.button(text=subcat, callback_data=f"add_subcat:{token}:{category}:{subcat}")
    kb.adjust(1)

    record_data["category"] = category
    ctx.pending_add_records.set(token, record_data)

    await callback.message.edit_text(  # type: ignore
        {
            "uk": f"Категорія: {category}\n\nОберіть підкатегорію:",
            "ru": f"Категория: {category}\n\nВыберите подкатегорию:",
            "en": f"Category: {category}\n\nChoose a subcategory:",
        }.get(lang, ""),
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("add_subcat:"))
async def add_subcategory_selected(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 3)
    if len(parts) < 4:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token, category, subcategory = parts[1], parts[2], parts[3]
    record_data = ctx.pending_add_records.get(token)

    if not record_data:
        await callback.answer(
            {
                "uk": "Дані застаріли, використайте /add знову.",
                "ru": "Данные устарели, используйте /add снова.",
                "en": "Data expired, use /add again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    payload = None
    try:
        async with ctx.get_session() as session:
            currency = await ctx._resolve_user_currency(session, callback.from_user.id)  # type: ignore
            payload = ctx.RecordCreate(
                type=record_data["type"],  # type: ignore
                category=category,
                subcategory=subcategory,
                amount=record_data["amount"],
                currency=currency,
                happened_on=record_data["happened_on"],
                description=record_data["description"],
            )
            service = ctx.RecordService(session, callback.from_user.id)  # type: ignore
            record = await service.add(payload)
            await session.commit()
        ctx.clear_stats_cache()
        ctx.pending_add_records.delete(token)

        cat_display = _localized_category_display(record.category, record.subcategory, lang)
        base = {
            "uk": f"✅ Додано {record.type.value}: {cat_display} {record.amount} {record.currency} від {record.happened_on}",
            "ru": f"✅ Добавлено {record.type.value}: {cat_display} {record.amount} {record.currency} от {record.happened_on}",
            "en": f"✅ Added {record.type.value}: {cat_display} {record.amount} {record.currency} on {record.happened_on}",
        }.get(lang, "")

        try:
            suffix = await format_limit_status(
                session,
                callback.from_user.id,
                record.user_id,
                record.category,
                record.subcategory,
                lang,
                record.currency,
            )
        except Exception:
            suffix = ""

        await callback.message.edit_text(base + (suffix or ""))
        await callback.answer()
    except ValueError as exc:
        if payload is not None and ctx._is_duplicate_record_error(exc):
            token_dup = ctx._stash_duplicate_record_payload(callback.from_user.id, payload)  # type: ignore
            if callback.message:
                await callback.message.answer(  # type: ignore
                    f"⚠️ {exc}",
                    reply_markup=ctx._force_duplicate_add_kb(lang, token_dup),
                )
            await callback.answer()
        else:
            await callback.answer(
                {
                    "uk": f"❌ Помилка: {exc}",
                    "ru": f"❌ Ошибка: {exc}",
                    "en": f"❌ Error: {exc}",
                }.get(lang, f"❌ Error: {exc}"),
                show_alert=True,
            )
    except Exception as exc:
        ctx.logger.exception(f"Add subcategory save error: {exc}")
        await callback.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}"),
            show_alert=True,
        )
