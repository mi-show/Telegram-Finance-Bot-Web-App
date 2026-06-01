from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message

from .common import route_ctx as ctx
from ..services.category_service import localize_category, localize_subcategory

router = Router()


def _localized_category_display(category: str, subcategory: str | None, lang: str) -> str:
    category_label = localize_category(category, lang) or category
    if not subcategory:
        return category_label

    subcategory_label = localize_subcategory(category, subcategory, lang) or subcategory
    return f"{category_label}({subcategory_label})"


def _menu_onetime_income_key(telegram_id: int) -> str:
    return f"menu:onetime_income:{telegram_id}"


class MenuOneTimeIncomePending(Filter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user or not message.text or message.text.startswith("/"):
            return False

        pending = ctx.pending_add_records.get(_menu_onetime_income_key(message.from_user.id))
        if not pending:
            return False

        menu_keys = (
            "menu_add_expense",
            "menu_add_income",
            "menu_list",
            "menu_stats",
            "menu_budget",
            "menu_receipt",
            "menu_webapp",
            "menu_language",
        )
        return all(message.text not in ctx._ui_variants(key) for key in menu_keys)


class OnboardingAmountPending(Filter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user or not message.text or message.text.startswith("/"):
            return False
        setup = ctx.pending_start_onboarding.get(str(message.from_user.id))
        return bool(setup and setup.get("step") == "amount")


def _onboarding_recurring_kb(lang: str):
    kb = ctx.InlineKeyboardBuilder()
    kb.button(text=ctx._t(lang, "onboarding_recurring_yes"), callback_data="onbreg:yes")
    kb.button(text=ctx._t(lang, "onboarding_recurring_no"), callback_data="onbreg:no")
    kb.button(text=ctx._t(lang, "onboarding_recurring_skip"), callback_data="onbreg:skip")
    kb.adjust(1)
    return kb.as_markup()


def _onboarding_income_offer_kb(lang: str):
    kb = ctx.InlineKeyboardBuilder()
    kb.button(text=ctx._t(lang, "onboarding_income_offer_add"), callback_data="onbinc:add")
    kb.button(text=ctx._t(lang, "onboarding_income_offer_skip"), callback_data="onbinc:skip")
    kb.adjust(1)
    return kb.as_markup()


def _menu_income_kind_kb(lang: str):
    kb = ctx.InlineKeyboardBuilder()
    kb.button(text=ctx._t(lang, "menu_income_kind_regular_btn"), callback_data="menuinc:recurring")
    kb.button(text=ctx._t(lang, "menu_income_kind_one_time_btn"), callback_data="menuinc:onetime")
    kb.adjust(1)
    return kb.as_markup()


@router.message(F.text.in_(ctx._ui_variants("menu_receipt")))
async def btn_receipt(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(ctx._t(lang, "hint_send_receipt"))


@router.message(F.text.in_(ctx._ui_variants("menu_webapp")))
async def btn_webapp(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    if ctx.settings.webapp_url:
        await message.answer(ctx._t(lang, "hint_open_webapp", url=ctx.settings.webapp_url))
        return
    await message.answer(ctx._t(lang, "hint_webapp_unavailable"))


@router.message(F.text.in_(ctx._ui_variants("menu_add_expense")))
async def btn_add_expense_hint(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(ctx._t(lang, "hint_add_expense_menu"))


@router.message(F.text.in_(ctx._ui_variants("menu_add_income")))
async def btn_add_income_hint(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(
        ctx._t(lang, "menu_income_kind_prompt"),
        reply_markup=_menu_income_kind_kb(lang),
    )


@router.callback_query(F.data.startswith("menuinc:"))
async def menu_income_kind_selected(callback: CallbackQuery):
    current_lang = ctx._normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    choice = callback.data.split(":", 1)[1].lower().strip()
    if choice not in {"recurring", "onetime"}:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    today = ctx.date.today().strftime(ctx.settings.date_format)
    selected_key = "menu_income_kind_selected_recurring" if choice == "recurring" else "menu_income_kind_selected_onetime"
    hint_key = "hint_add_income_recurring" if choice == "recurring" else "hint_add_income_onetime"

    if choice == "onetime":
        ctx.pending_add_records.set(_menu_onetime_income_key(callback.from_user.id), True)
    else:
        ctx.pending_add_records.delete(_menu_onetime_income_key(callback.from_user.id))

    if callback.message:
        await ctx._safe_edit_callback_message(
            callback,
            ctx._t(lang, selected_key),
            reply_markup=None,
        )
        await callback.message.answer(  # type: ignore
            ctx._t(lang, hint_key, today=today),
        )

    await callback.answer()


@router.message(MenuOneTimeIncomePending())
async def menu_onetime_income_amount(message: Message):
    if not message.from_user or not message.text:
        return

    lang = await ctx._get_user_language(message.from_user.id)
    raw_amount = message.text.strip()
    if raw_amount.startswith("+"):
        raw_amount = raw_amount[1:].strip()
    amount = ctx._parse_amount_input(raw_amount)
    if amount is None:
        await message.answer(ctx._t(lang, "menu_income_onetime_amount_invalid"))
        return

    payload = None
    try:
        async with ctx.get_session() as session:
            currency = await ctx._resolve_user_currency(session, message.from_user.id)
            service = ctx.RecordService(session, message.from_user.id)
            payload = ctx.RecordCreate(
                type="income",
                category="Salary",
                subcategory="Main",
                amount=amount,
                currency=currency,
                happened_on=ctx.date.today(),
                description=None,
            )
            record = await service.add(payload)
            await session.commit()
        ctx.clear_stats_cache()
        ctx.pending_add_records.delete(_menu_onetime_income_key(message.from_user.id))

        cat_display = _localized_category_display(record.category, record.subcategory, lang)
        await message.answer(
            ctx._t(
                lang,
                "menu_income_onetime_added",
                category=cat_display,
                amount=record.amount,
                currency=record.currency,
                happened_on=record.happened_on,
            )
        )
    except ValueError as exc:
        if payload is not None and ctx._is_duplicate_record_error(exc):
            token = ctx._stash_duplicate_record_payload(message.from_user.id, payload)
            await message.answer(
                f"⚠️ {exc}",
                reply_markup=ctx._force_duplicate_add_kb(lang, token),
            )
        else:
            await message.answer(f"⚠️ {exc}")
    except Exception as exc:
        ctx.logger.exception("Failed to save one-time income from menu: %s", exc)
        await message.answer(ctx._t(lang, "error_data"))


@router.callback_query(F.data.startswith("dupadd:"))
async def force_add_duplicate_record(callback: CallbackQuery):
    lang = await ctx._get_user_language(callback.from_user.id)  # type: ignore
    if not callback.data:
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    token = callback.data.split(":", 1)[1]
    pending = ctx._get_stashed_duplicate_record_payload(token)
    if not pending:
        await callback.answer(
            {
                "uk": "Дані застаріли, спробуйте додати запис ще раз.",
                "ru": "Данные устарели, попробуйте добавить запись снова.",
                "en": "Data expired, try adding the record again.",
            }.get(lang, "Data expired, try adding the record again."),
            show_alert=True,
        )
        return

    owner_id = pending.get("owner_id")
    payload = pending.get("payload")
    if owner_id != callback.from_user.id or payload is None:
        await callback.answer(
            {
                "uk": "Ця дія недоступна.",
                "ru": "Это действие недоступно.",
                "en": "This action is unavailable.",
            }.get(lang, "This action is unavailable."),
            show_alert=True,
        )
        return

    try:
        async with ctx.get_session() as session:
            service = ctx.RecordService(session, callback.from_user.id)
            record = await service.add(payload, allow_duplicate=True)
            await session.commit()

        ctx._delete_stashed_duplicate_record_payload(token)
        ctx.clear_stats_cache()

        cat_display = _localized_category_display(record.category, record.subcategory, lang)
        if callback.message:
            await callback.message.answer(  # type: ignore
                {
                    "uk": f"✅ Додано {record.type.value}: {cat_display} {record.amount} {record.currency} від {record.happened_on}",
                    "ru": f"✅ Добавлено {record.type.value}: {cat_display} {record.amount} {record.currency} от {record.happened_on}",
                    "en": f"✅ Added {record.type.value}: {cat_display} {record.amount} {record.currency} on {record.happened_on}",
                }.get(lang, "")
            )
        await callback.answer(
            {
                "uk": "Запис додано.",
                "ru": "Запись добавлена.",
                "en": "Record added.",
            }.get(lang, "Record added.")
        )
    except Exception as exc:
        ctx.logger.exception("Failed to force-add duplicate record: %s", exc)
        await callback.answer(
            {
                "uk": "❌ Не вдалося додати запис.",
                "ru": "❌ Не удалось добавить запись.",
                "en": "❌ Failed to add record.",
            }.get(lang, "❌ Failed to add record."),
            show_alert=True,
        )


@router.message(Command("start"))
async def cmd_start(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(
        ctx._t(lang, "pick_language_intro"),
        reply_markup=ctx._language_picker_kb(lang, origin="start"),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(
        ctx._t(lang, "start_help"),
        reply_markup=ctx._main_menu_kb(lang),
    )


@router.message(Command("convert"))
async def cmd_convert(message: Message):
    if not message.text:
        return
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    parts = message.text.split()
    if len(parts) < 3 or len(parts) > 4:
        await message.answer(ctx._t(lang, "convert_usage"))
        return

    amount = ctx._parse_amount_input(parts[1])
    source_currency = ctx._normalize_currency_code(parts[2])
    target_currency = (
        ctx._normalize_currency_code(parts[3])
        if len(parts) == 4
        else ctx._default_target_currency(source_currency or "")
    )
    if amount is None or source_currency is None or target_currency is None:
        await message.answer(ctx._t(lang, "convert_invalid"))
        return

    rates_by_usd = await ctx._get_live_rates_by_usd()
    converted = ctx._convert_amount_with_rates(amount, source_currency, target_currency, rates_by_usd)
    pair_rate = ctx._convert_amount_with_rates(
        Decimal("1"),
        source_currency,
        target_currency,
        rates_by_usd,
    )
    await message.answer(
        ctx._t(
            lang,
            "convert_result",
            amount=ctx._fmt_amount(amount),
            from_currency=source_currency,
            converted=ctx._fmt_amount(converted),
            to_currency=target_currency,
            pair_rate=ctx._fmt_amount(pair_rate),
        )
    )


@router.message(Command("language"))
async def cmd_language(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    await message.answer(ctx._t(lang, "language_pick_prompt"), reply_markup=ctx._language_picker_kb(lang, origin="set"))


@router.message(F.text.in_(ctx._ui_variants("menu_language")))
async def btn_language(message: Message):
    await cmd_language(message)


@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery):
    current_lang = ctx._normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    flow_origin = parts[1] if parts[1] in {"set", "start"} else "set"
    new_lang = parts[2].lower()
    if new_lang not in ctx.SUPPORTED_LANGUAGES:
        await callback.answer(ctx._t(current_lang, "error_unsupported_lang"), show_alert=True)
        return

    try:
        async with ctx.get_session() as session:
            user_repo = ctx.UserRepository(session)
            await user_repo.set_language(callback.from_user.id, new_lang)  # type: ignore
            await session.commit()
        if callback.message:
            await ctx._safe_edit_callback_message(
                callback,
                ctx._language_changed_text(new_lang),
                reply_markup=None,
            )
            if flow_origin == "start":
                existing_setup = ctx.pending_start_onboarding.get(str(callback.from_user.id))
                if (
                    isinstance(existing_setup, dict)
                    and existing_setup.get("lang") == new_lang
                    and existing_setup.get("step") in {"currency", "income_offer", "amount", "recurring"}
                ):
                    await callback.answer(ctx._t(new_lang, "language_saved_toast"))
                    return
                ctx.pending_start_onboarding.set(
                    str(callback.from_user.id),
                    {
                        "step": "currency",
                        "lang": new_lang,
                    },
                )
                await callback.message.answer(  # type: ignore
                    ctx._t(new_lang, "onboarding_currency_prompt"),
                    reply_markup=ctx._onboarding_currency_kb(new_lang),
                )
            else:
                await callback.message.answer(  # type: ignore
                    ctx._t(new_lang, "language_menu_updated"),
                    reply_markup=ctx._main_menu_kb(new_lang),
                )
        await callback.answer(ctx._t(new_lang, "language_saved_toast"))
    except Exception as exc:
        ctx.logger.exception("Failed to save language: %s", exc)
        await callback.answer(ctx._t(current_lang, "error_save_lang"), show_alert=True)


@router.message(OnboardingAmountPending())
async def onboarding_income_amount(message: Message):
    if not message.from_user or not message.text:
        return

    setup_key = str(message.from_user.id)
    setup = ctx.pending_start_onboarding.get(setup_key)
    if not setup or setup.get("step") != "amount":
        return

    lang = ctx._normalize_lang(setup.get("lang", "uk"))
    amount = ctx._parse_amount_input(message.text)
    if amount is None:
        await message.answer(ctx._t(lang, "onboarding_income_invalid"))
        return

    currency = str(setup.get("currency", "")).upper().strip()
    if currency not in ctx.SUPPORTED_ONBOARDING_CURRENCIES:
        ctx.pending_start_onboarding.delete(setup_key)
        await message.answer(ctx._t(lang, "onboarding_currency_stale"))
        return

    ctx.pending_start_onboarding.set(
        setup_key,
        {
            "step": "recurring",
            "lang": lang,
            "amount": str(amount),
            "currency": currency,
        },
    )
    await message.answer(
        ctx._t(lang, "onboarding_recurring_prompt"),
        reply_markup=_onboarding_recurring_kb(lang),
    )


@router.callback_query(F.data.startswith("onbcur:"))
async def onboarding_pick_currency(callback: CallbackQuery):
    current_lang = ctx._normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    currency = callback.data.split(":", 1)[1].upper().strip()
    if currency not in ctx.SUPPORTED_ONBOARDING_CURRENCIES:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    setup_key = str(callback.from_user.id)
    setup = ctx.pending_start_onboarding.get(setup_key)
    if not setup or setup.get("step") != "currency":
        await callback.answer(ctx._t(current_lang, "onboarding_currency_stale"), show_alert=True)
        return

    lang = ctx._normalize_lang(setup.get("lang", current_lang))
    try:
        async with ctx.get_session() as session:
            await ctx._save_start_currency(
                session,
                callback.from_user.id,
                lang,
                currency,
            )
            await session.commit()
    except Exception as exc:
        ctx.logger.exception("Failed to save onboarding currency: %s", exc)
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
        return

    ctx.pending_start_onboarding.set(
        setup_key,
        {
            "step": "income_offer",
            "lang": lang,
            "currency": currency,
        },
    )

    if callback.message:
        await ctx._safe_edit_callback_message(
            callback,
            ctx._t(lang, "onboarding_currency_selected", currency=currency),
            reply_markup=None,
        )
        await callback.message.answer(  # type: ignore
            ctx._t(lang, "onboarding_income_offer_prompt"),
            reply_markup=_onboarding_income_offer_kb(lang),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("onbinc:"))
async def onboarding_income_offer(callback: CallbackQuery):
    current_lang = ctx._normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    choice = callback.data.split(":", 1)[1].lower().strip()
    if choice not in {"add", "skip"}:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    setup_key = str(callback.from_user.id)
    setup = ctx.pending_start_onboarding.get(setup_key)
    if not setup or setup.get("step") != "income_offer":
        await callback.answer(ctx._t(current_lang, "onboarding_currency_stale"), show_alert=True)
        return

    lang = ctx._normalize_lang(setup.get("lang", current_lang))
    currency = str(setup.get("currency", "")).upper().strip()
    if currency not in ctx.SUPPORTED_ONBOARDING_CURRENCIES:
        ctx.pending_start_onboarding.delete(setup_key)
        await callback.answer(ctx._t(lang, "onboarding_currency_stale"), show_alert=True)
        return

    if choice == "add":
        ctx.pending_start_onboarding.set(
            setup_key,
            {
                "step": "amount",
                "lang": lang,
                "currency": currency,
            },
        )

        if callback.message:
            await ctx._safe_edit_callback_message(
                callback,
                ctx._t(lang, "onboarding_income_offer_selected_add"),
                reply_markup=None,
            )
            await callback.message.answer(  # type: ignore
                ctx._t(lang, "onboarding_income_prompt"),
            )

        await callback.answer()
        return

    ctx.pending_start_onboarding.delete(setup_key)
    if callback.message:
        await ctx._safe_edit_callback_message(
            callback,
            ctx._t(lang, "onboarding_income_offer_selected_skip"),
            reply_markup=None,
        )
        await callback.message.answer(  # type: ignore
            ctx._t(lang, "onboarding_income_skipped_note"),
        )
        await callback.message.answer(  # type: ignore
            ctx._t(lang, "start_help"),
            reply_markup=ctx._main_menu_kb(lang),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("onbreg:"))
async def onboarding_pick_recurring(callback: CallbackQuery):
    current_lang = ctx._normalize_lang(callback.from_user.language_code)
    if not callback.data:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    recurring_choice = callback.data.split(":", 1)[1].lower().strip()
    if recurring_choice not in {"yes", "no", "skip"}:
        await callback.answer(ctx._t(current_lang, "error_data"), show_alert=True)
        return

    setup_key = str(callback.from_user.id)
    setup = ctx.pending_start_onboarding.get(setup_key)
    if not setup or setup.get("step") != "recurring":
        await callback.answer(ctx._t(current_lang, "onboarding_currency_stale"), show_alert=True)
        return

    lang = ctx._normalize_lang(setup.get("lang", current_lang))
    amount = ctx._parse_amount_input(str(setup.get("amount", "")))
    currency = str(setup.get("currency", "")).upper().strip()

    if amount is None or currency not in ctx.SUPPORTED_ONBOARDING_CURRENCIES:
        ctx.pending_start_onboarding.delete(setup_key)
        await callback.answer(ctx._t(lang, "onboarding_currency_stale"), show_alert=True)
        return

    create_recurring = recurring_choice == "yes"

    selected_key = {
        "yes": "onboarding_recurring_selected_yes",
        "no": "onboarding_recurring_selected_no",
        "skip": "onboarding_recurring_selected_skip",
    }[recurring_choice]
    note_key = "onboarding_recurring_note_with" if create_recurring else "onboarding_recurring_note_without"

    try:
        async with ctx.get_session() as session:
            await ctx._save_start_income_and_currency(
                session,
                callback.from_user.id,
                lang,
                amount,
                currency,
                create_recurring=create_recurring,
            )
            await session.commit()
        ctx.clear_stats_cache()

        ctx.pending_start_onboarding.delete(setup_key)
        rates_by_usd = await ctx._get_live_rates_by_usd()
        alt_currencies = [code for code in ctx.SUPPORTED_CONVERSION_ORDER if code != currency]
        alt1_currency = alt_currencies[0]
        alt2_currency = alt_currencies[1]
        alt1_amount = ctx._convert_amount_with_rates(amount, currency, alt1_currency, rates_by_usd)
        alt2_amount = ctx._convert_amount_with_rates(amount, currency, alt2_currency, rates_by_usd)

        if callback.message:
            await ctx._safe_edit_callback_message(
                callback,
                ctx._t(lang, selected_key),
                reply_markup=None,
            )
            await callback.message.answer(  # type: ignore
                ctx._t(
                    lang,
                    "onboarding_currency_saved",
                    amount=ctx._fmt_amount(amount),
                    currency=currency,
                    alt1_amount=ctx._fmt_amount(alt1_amount),
                    alt1_currency=alt1_currency,
                    alt2_amount=ctx._fmt_amount(alt2_amount),
                    alt2_currency=alt2_currency,
                )
            )
            await callback.message.answer(  # type: ignore
                ctx._t(lang, note_key),
            )
            await callback.message.answer(  # type: ignore
                ctx._t(lang, "start_help"),
                reply_markup=ctx._main_menu_kb(lang),
            )

        await callback.answer(ctx._t(lang, "onboarding_currency_saved_toast"))
    except Exception as exc:
        ctx.logger.exception("Failed to save onboarding income/currency: %s", exc)
        await callback.answer(ctx._t(lang, "error_data"), show_alert=True)
