from decimal import Decimal, InvalidOperation

from aiogram import F, Router
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


@router.message(F.text & ~F.text.startswith("/") & F.text.regexp(r"(?i).+\s+\d+[\.,]?\d*$"))
async def quick_expense_freeform(message: Message):
    if not message.text:
        return

    if message.from_user and ctx.pending_add_records.get(f"menu:list_count:{message.from_user.id}"):
        lang = await ctx._get_user_language(message.from_user.id)
        await message.answer(ctx._t(lang, "list_count_invalid", max_count=ctx.settings.max_list_records))
        return

    # Show activity for potentially heavy first-run classifier warmup.
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    pending_payload = None
    try:
        async with ctx.get_session() as session:
            lang = await ctx._prepare_classifier(session, message.from_user.id)  # type: ignore
            parsed = ctx._parse_quick_expense(message.text)
            if not parsed:
                return

            description, amount = parsed
            currency = await ctx._resolve_user_currency(session, message.from_user.id)  # type: ignore
            ctx.logger.info(f"Quick expense: text='{message.text}' -> description='{description}', amount={amount}")

            category, subcategory, confidence, source = ctx.user_classifier.predict_with_user_context_confidence(
                description,
                message.from_user.id,  # type: ignore
                language=lang,
            )

            gibberish = ctx._looks_like_gibberish(description)
            trusted_sources = {"user_exact", "user_fuzzy", "override", "dictionary"}
            needs_confirmation = (
                source not in trusted_sources
                or confidence < 0.8
                or (gibberish and source not in {"user_exact", "user_fuzzy"})
            )
            ctx.logger.info(
                "Quick classification: category='%s', subcategory='%s', source=%s, confidence=%.3f, gibberish=%s",
                category,
                subcategory,
                source,
                confidence,
                gibberish,
            )

            if needs_confirmation:
                categories = ctx._build_quick_category_candidates(
                    description,
                    message.from_user.id,  # type: ignore
                    lang,
                    category,
                )
                if not categories:
                    categories = ctx.get_categories_for_lang(lang)[:6]

                token = ctx.secrets.token_hex(8)
                ctx.pending_quick_records.set(
                    token,
                    {
                        "description": description,
                        "amount": amount,
                        "happened_on": ctx.date.today(),
                        "language": lang,
                        "categories": categories,
                        "selected_category": None,
                        "selected_subcategory": None,
                        "predicted_subcategory": subcategory,
                        "category_page": 0,
                    },
                )

                await message.answer(
                    {
                        "uk": (
                            "🤖 Я не до кінця зрозумів, до якої категорії це віднести.\n"
                            f"Текст: '{description}' | Сума: {amount} {currency}\n\n"
                            "Можеш обрати категорію вручну, і я запам'ятаю слово,\n"
                            "або сказати, що слово було написано неправильно."
                        ),
                        "ru": (
                            "🤖 Я не совсем понял, к какой категории это отнести.\n"
                            f"Текст: '{description}' | Сумма: {amount} {currency}\n\n"
                            "Вы можете выбрать категорию вручную, и я запомню слово,\n"
                            "или сказать, что слово было написано неправильно."
                        ),
                        "en": (
                            "🤖 I am not sure which category this belongs to.\n"
                            f"Text: '{description}' | Amount: {amount} {currency}\n\n"
                            "You can choose a category manually and I will remember this word,\n"
                            "or tell me the word was misspelled."
                        ),
                    }.get(lang, ""),
                    reply_markup=ctx._quick_category_keyboard(token, categories, page=0, lang=lang),
                )
                return

            service = ctx.RecordService(session, message.from_user.id)  # type: ignore
            pending_payload = ctx.RecordCreate(
                type="expense",
                category=category,
                subcategory=subcategory,
                amount=amount,
                currency=currency,
                happened_on=ctx.date.today(),
                description=description,
            )
            record = await service.add(pending_payload)
            await session.commit()

            base = {
                "uk": f"✅ Додав {_localized_category_display(record.category, record.subcategory, lang)}: {record.amount} {record.currency} від {record.happened_on}",
                "ru": f"✅ Добавил {_localized_category_display(record.category, record.subcategory, lang)}: {record.amount} {record.currency} от {record.happened_on}",
                "en": f"✅ Added {_localized_category_display(record.category, record.subcategory, lang)}: {record.amount} {record.currency} on {record.happened_on}",
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
        if pending_payload is not None and ctx._is_duplicate_record_error(exc):
            token = ctx._stash_duplicate_record_payload(message.from_user.id, pending_payload)  # type: ignore
            await message.answer(
                f"⚠️ {exc}",
                reply_markup=ctx._force_duplicate_add_kb(
                    await ctx._get_user_language(message.from_user.id),
                    token,
                ),
            )
        else:
            await message.answer(f"⚠️ {exc}")
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"Quick expense DB error: {exc}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше або /add.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже или /add.",
                "en": "❌ Database error. Try again later or use /add.",
            }.get(await ctx._get_user_language(message.from_user.id), "❌ Database error.")  # type: ignore
        )
    except Exception as exc:
        ctx.logger.exception(f"Quick expense error: {exc}")
        await message.answer(
            {
                "uk": "❌ Не вдалося зберегти. Спробуйте /add або пізніше.",
                "ru": "❌ Не удалось сохранить. Попробуйте /add или позже.",
                "en": "❌ Could not save. Try /add or again later.",
            }.get(await ctx._get_user_language(message.from_user.id), "❌ Could not save.")  # type: ignore
        )


@router.callback_query(F.data.startswith("qcat:"))
async def quick_category_selected(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token = parts[1]
    pending = ctx.pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = ctx._normalize_lang(pending.get("language", "uk"))

    action = "c"
    value_raw = ""
    if len(parts) >= 4:
        action = parts[2]
        value_raw = parts[3]
    else:
        value_raw = parts[2]

    categories = pending.get("categories", [])

    if action == "p":
        try:
            target_page = int(value_raw)
        except ValueError:
            await callback.answer(
                {
                    "uk": "Помилка навігації.",
                    "ru": "Ошибка навигации.",
                    "en": "Navigation error.",
                }.get(lang, "Navigation error."),
                show_alert=True,
            )
            return

        pending["category_page"] = max(0, target_page)
        ctx.pending_quick_records.set(token, pending)
        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=ctx._quick_category_keyboard(token, categories, page=pending["category_page"], lang=lang),
        )
        await callback.answer()
        return

    try:
        idx = int(value_raw)
    except ValueError:
        await callback.answer(
            {
                "uk": "Помилка вибору категорії.",
                "ru": "Ошибка выбора категории.",
                "en": "Category selection error.",
            }.get(lang, "Category selection error."),
            show_alert=True,
        )
        return

    if idx < 0 or idx >= len(categories):
        await callback.answer(
            {
                "uk": "Категорію не знайдено.",
                "ru": "Категория не найдена.",
                "en": "Category not found.",
            }.get(lang, "Category not found."),
            show_alert=True,
        )
        return

    selected_category = categories[idx]
    pending["selected_category"] = selected_category
    pending["selected_subcategory"] = None
    pending["category_page"] = idx // ctx.QUICK_CATEGORY_PAGE_SIZE
    ctx.pending_quick_records.set(token, pending)

    subcats = ctx.get_subcategories_for_category(selected_category, pending.get("language", "uk"))
    if subcats:
        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": f"Ви обрали категорію: {selected_category}\n\nТепер оберіть підкатегорію:",
                "ru": f"Вы выбрали категорию: {selected_category}\n\nТеперь выберите подкатегорию:",
                "en": f"You selected category: {selected_category}\n\nNow choose a subcategory:",
            }.get(lang, ""),
            reply_markup=ctx._quick_subcategory_keyboard(token, subcats, lang=lang),
        )
        await callback.answer()
        return

    await ctx._safe_edit_callback_message(
        callback,
        {
            "uk": (
                f"Ви обрали категорію: {selected_category}\n\n"
                "Слово написано правильно?\n"
                "Якщо так, я запам'ятаю його для наступних записів."
            ),
            "ru": (
                f"Вы выбрали категорию: {selected_category}\n\n"
                "Слово написано правильно?\n"
                "Если да, я запомню его для следующих записей."
            ),
            "en": (
                f"You selected category: {selected_category}\n\n"
                "Is the word spelled correctly?\n"
                "If yes, I will remember it for future entries."
            ),
        }.get(lang, ""),
        reply_markup=ctx._quick_spelling_keyboard(token, lang=lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qsub:"))
async def quick_subcategory_selected(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token, decision = parts[1], parts[2]
    pending = ctx.pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = ctx._normalize_lang(pending.get("language", "uk"))

    if decision == "back":
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

        selected_category = pending.get("selected_category")
        page = pending.get("category_page", 0)
        if selected_category in categories:
            page = categories.index(selected_category) // ctx.QUICK_CATEGORY_PAGE_SIZE

        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=ctx._quick_category_keyboard(token, categories, page=page, lang=lang),
        )
        await callback.answer()
        return

    selected_category = pending.get("selected_category")
    if not selected_category:
        await callback.answer(
            {
                "uk": "Спочатку оберіть категорію.",
                "ru": "Сначала выберите категорию.",
                "en": "Select a category first.",
            }.get(lang, "Select a category first."),
            show_alert=True,
        )
        return

    language = pending.get("language", "uk")
    subcats = ctx.get_subcategories_for_category(selected_category, language)

    if decision == "none":
        pending["selected_subcategory"] = None
        ctx.pending_quick_records.set(token, pending)
    else:
        try:
            idx = int(decision)
        except ValueError:
            await callback.answer(
                {
                    "uk": "Помилка вибору підкатегорії.",
                    "ru": "Ошибка выбора подкатегории.",
                    "en": "Subcategory selection error.",
                }.get(lang, "Subcategory selection error."),
                show_alert=True,
            )
            return

        if idx < 0 or idx >= len(subcats):
            await callback.answer(
                {
                    "uk": "Підкатегорію не знайдено.",
                    "ru": "Подкатегория не найдена.",
                    "en": "Subcategory not found.",
                }.get(lang, "Subcategory not found."),
                show_alert=True,
            )
            return

        pending["selected_subcategory"] = subcats[idx]
        ctx.pending_quick_records.set(token, pending)

    subcat_value = pending.get("selected_subcategory")
    subcat_label = subcat_value if subcat_value else ctx._t(lang, "btn_subcat_none")
    await ctx._safe_edit_callback_message(
        callback,
        {
            "uk": (
                f"Ви обрали категорію: {selected_category}\n"
                f"Підкатегорія: {subcat_label}\n\n"
                "Слово написано правильно?\n"
                "Якщо так, я запам'ятаю його для наступних записів."
            ),
            "ru": (
                f"Вы выбрали категорию: {selected_category}\n"
                f"Подкатегория: {subcat_label}\n\n"
                "Слово написано правильно?\n"
                "Если да, я запомню его для следующих записей."
            ),
            "en": (
                f"You selected category: {selected_category}\n"
                f"Subcategory: {subcat_label}\n\n"
                "Is the word spelled correctly?\n"
                "If yes, I will remember it for future entries."
            ),
        }.get(lang, ""),
        reply_markup=ctx._quick_spelling_keyboard(token, lang=lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qspell:"))
async def quick_spelling_confirmed(callback: CallbackQuery):
    lang = "uk"
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token, decision = parts[1], parts[2]
    pending = ctx.pending_quick_records.get(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, надішліть запис ще раз.",
                "ru": "Данные устарели, отправьте запись снова.",
                "en": "Data expired, send the expense again.",
            }.get(lang, "Data expired."),
            show_alert=True,
        )
        return

    lang = ctx._normalize_lang(pending.get("language", "uk"))

    if decision == "back":
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

        selected_category = pending.get("selected_category")
        page = pending.get("category_page", 0)
        if selected_category in categories:
            page = categories.index(selected_category) // ctx.QUICK_CATEGORY_PAGE_SIZE

        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": "Оберіть категорію вручну:",
                "ru": "Выберите категорию вручную:",
                "en": "Choose a category manually:",
            }.get(lang, "Choose a category manually:"),
            reply_markup=ctx._quick_category_keyboard(token, categories, page=page, lang=lang),
        )
        await callback.answer()
        return

    if decision == "no":
        ctx.pending_quick_records.delete(token)
        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": "Ок, запис не додаю.\nНадішліть витрату ще раз у форматі: опис сума",
                "ru": "Окей, запись не добавляю.\nОтправьте расход заново в формате: описание сумма",
                "en": "Okay, I will not add the record.\nSend expense again in format: description amount",
            }.get(lang, "")
        )
        await callback.answer()
        return

    remember_word = True
    selected_category = pending.get("selected_category")
    if not selected_category:
        await callback.answer(
            {
                "uk": "Спочатку оберіть категорію.",
                "ru": "Сначала выберите категорию.",
                "en": "Select a category first.",
            }.get(lang, "Select a category first."),
            show_alert=True,
        )
        return

    description = pending.get("description")
    amount = pending.get("amount")
    happened_on = pending.get("happened_on", ctx.date.today())
    selected_subcategory = pending.get("selected_subcategory")

    pending_payload = None
    try:
        async with ctx.get_session() as session:
            currency = await ctx._resolve_user_currency(session, callback.from_user.id)  # type: ignore
            service = ctx.RecordService(session, callback.from_user.id)  # type: ignore
            pending_payload = ctx.RecordCreate(
                type="expense",
                category=selected_category,
                subcategory=selected_subcategory,
                amount=amount,
                currency=currency,
                happened_on=happened_on,
                description=description,
            )
            record = await service.add(pending_payload)

            remembered = False
            if remember_word and description:
                remembered = await ctx.user_classifier.remember_user_phrase(
                    session,
                    callback.from_user.id,
                    description,
                    selected_category,
                    selected_subcategory,
                )

            await session.commit()

        ctx.user_classifier._user_history_stats[callback.from_user.id][selected_category] += 1
        ctx.pending_quick_records.delete(token)
        ctx.clear_stats_cache()

        cat_display = _localized_category_display(record.category, record.subcategory, lang)
        if remember_word and description and remembered:
            learn_suffix = {
                "uk": "\n💾 Слово збережено в словник.",
                "ru": "\n💾 Слово сохранено в словарь.",
                "en": "\n💾 Word saved to dictionary.",
            }.get(lang, "")
        elif remember_word and description:
            learn_suffix = {
                "uk": "\n⚠️ Не вдалося зберегти слово у словник.",
                "ru": "\n⚠️ Не удалось сохранить слово в словарь.",
                "en": "\n⚠️ Failed to save word to dictionary.",
            }.get(lang, "")
        else:
            learn_suffix = ""
        await ctx._safe_edit_callback_message(
            callback,
            {
                "uk": f"✅ Додав {cat_display}: {record.amount} {record.currency} від {record.happened_on}{learn_suffix}",
                "ru": f"✅ Добавил {cat_display}: {record.amount} {record.currency} от {record.happened_on}{learn_suffix}",
                "en": f"✅ Added {cat_display}: {record.amount} {record.currency} on {record.happened_on}{learn_suffix}",
            }.get(lang, "")
        )
        await callback.answer()
    except ValueError as exc:
        if pending_payload is not None and ctx._is_duplicate_record_error(exc):
            token_dup = ctx._stash_duplicate_record_payload(callback.from_user.id, pending_payload)  # type: ignore
            if callback.message:
                await callback.message.answer(  # type: ignore
                    f"⚠️ {exc}",
                    reply_markup=ctx._force_duplicate_add_kb(lang, token_dup),
                )
            await callback.answer()
        else:
            await callback.answer(
                {
                    "uk": "❌ Не вдалося зберегти запис.",
                    "ru": "❌ Не удалось сохранить запись.",
                    "en": "❌ Failed to save record.",
                }.get(lang, "❌ Failed to save record."),
                show_alert=True,
            )
    except Exception as exc:
        ctx.logger.exception(f"Quick spelling confirmation error: {exc}")
        await callback.answer(
            {
                "uk": "❌ Не вдалося зберегти запис.",
                "ru": "❌ Не удалось сохранить запись.",
                "en": "❌ Failed to save record.",
            }.get(lang, "❌ Failed to save record."),
            show_alert=True,
        )


@router.callback_query(F.data.startswith("select_category:"))
async def select_category_for_unknown_word(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    pending_payload = None
    try:
        parts = callback.data.split(":", 3)
        if len(parts) < 4:
            await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
            return

        description = parts[1]
        amount_str = parts[2]
        category = parts[3]

        try:
            amount = Decimal(amount_str.replace(",", "."))
        except (InvalidOperation, ValueError):
            await callback.answer(
                {
                    "uk": "Помилка суми.",
                    "ru": "Ошибка суммы.",
                    "en": "Invalid amount.",
                }.get(lang, "Invalid amount."),
                show_alert=True,
            )
            return

        telegram_id = callback.from_user.id  # type: ignore
        lang = await ctx._get_user_language(telegram_id)

        _, predicted_subcat = ctx.user_classifier.predict_with_user_context(
            description, telegram_id, language=lang
        )

        async with ctx.get_session() as session:
            all_subcats = ctx.get_subcategories_for_category(category, lang)
            if predicted_subcat not in all_subcats:
                predicted_subcat = None

        async with ctx.get_session() as session:
            currency = await ctx._resolve_user_currency(session, telegram_id)
            service = ctx.RecordService(session, telegram_id)  # type: ignore
            pending_payload = ctx.RecordCreate(
                type="expense",
                category=category,
                subcategory=predicted_subcat,
                amount=amount,
                currency=currency,
                happened_on=ctx.date.today(),
                description=description,
            )
            record = await service.add(pending_payload)

            await ctx.user_classifier.remember_user_phrase(
                session,
                telegram_id,
                description,
                category,
                predicted_subcat,
            )

            ctx.user_classifier._user_history_stats[telegram_id][category] += 1

            await session.commit()

        ctx.clear_stats_cache()

        cat_display = _localized_category_display(record.category, record.subcategory, lang)

        await callback.message.edit_text(  # type: ignore
            {
                "uk": (
                    f"✅ Додав {cat_display}: {record.amount} {record.currency} від {record.happened_on}\n"
                    f"💾 Запам'ятав '{description}' -> {category}"
                ),
                "ru": (
                    f"✅ Добавил {cat_display}: {record.amount} {record.currency} от {record.happened_on}\n"
                    f"💾 Запомнил '{description}' -> {category}"
                ),
                "en": (
                    f"✅ Added {cat_display}: {record.amount} {record.currency} on {record.happened_on}\n"
                    f"💾 Remembered '{description}' -> {category}"
                ),
            }.get(lang, "")
        )
        await callback.answer()

    except ValueError as exc:
        if pending_payload is not None and ctx._is_duplicate_record_error(exc):
            token_dup = ctx._stash_duplicate_record_payload(callback.from_user.id, pending_payload)  # type: ignore
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
        ctx.logger.exception(f"Select category error: {exc}")
        await callback.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}"),
            show_alert=True,
        )
