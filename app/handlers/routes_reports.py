from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import Message
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .common import route_ctx as ctx
from ..services.category_service import localize_category, localize_subcategory

router = Router()


def _menu_list_count_key(telegram_id: int) -> str:
    return f"menu:list_count:{telegram_id}"


class MenuListCountPending(Filter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user or not message.text or message.text.startswith("/"):
            return False

        pending = ctx.pending_add_records.get(_menu_list_count_key(message.from_user.id))
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


async def _send_records_list(message: Message, lang: str, filters: ctx.RecordFilter, limit: int) -> None:
    async with ctx.get_session() as session:
        service = ctx.RecordService(session, message.from_user.id)  # type: ignore
        records = await service.list(filters, limit=limit)

    if not records:
        await message.answer(
            {
                "uk": "📭 Немає записів за вибраними фільтрами.",
                "ru": "📭 Нет записей по выбранным фильтрам.",
                "en": "📭 No records for selected filters.",
            }.get(lang, "")
        )
        return

    lines = []
    for record in records[:limit]:
        category_label = localize_category(record.category, lang) or record.category
        if record.subcategory:
            subcategory_label = localize_subcategory(record.category, record.subcategory, lang) or record.subcategory
            cat_display = f"{category_label}({subcategory_label})"
        else:
            cat_display = category_label
        line = f"{record.happened_on} {record.type.value} {cat_display}: {record.amount} {record.currency}"
        if record.description:
            line += f" - {record.description}"
        lines.append(line)

    if len(records) == limit:
        lines.append(
            {
                "uk": f"\n(Показано перші {limit} записів)",
                "ru": f"\n(Показаны первые {limit} записей)",
                "en": f"\n(Showing first {limit} records)",
            }.get(lang, "")
        )

    await ctx._answer_chunked(message, "\n".join(lines))


@router.message(F.text.in_(ctx._ui_variants("menu_list")))
async def btn_list(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    ctx.pending_add_records.set(_menu_list_count_key(message.from_user.id), True)  # type: ignore
    await message.answer(ctx._t(lang, "list_count_prompt", max_count=ctx.settings.max_list_records))


@router.message(MenuListCountPending())
async def menu_list_count_received(message: Message):
    if not message.from_user or not message.text:
        return

    lang = await ctx._get_user_language(message.from_user.id)
    raw_count = message.text.strip()
    try:
        count = int(raw_count)
    except ValueError:
        await message.answer(ctx._t(lang, "list_count_invalid", max_count=ctx.settings.max_list_records))
        return

    if count < 1 or count > ctx.settings.max_list_records:
        await message.answer(ctx._t(lang, "list_count_invalid", max_count=ctx.settings.max_list_records))
        return

    ctx.pending_add_records.delete(_menu_list_count_key(message.from_user.id))

    try:
        await _send_records_list(message, lang, ctx.RecordFilter(), limit=count)
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"Database error in menu list count flow: {exc}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as exc:
        ctx.logger.exception(f"Unexpected error in menu list count flow: {exc}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}")
        )


@router.message(F.text.in_(ctx._ui_variants("menu_stats")))
async def btn_stats(message: Message):
    await cmd_stats(message)


@router.message(F.text.in_(ctx._ui_variants("menu_budget")))
async def btn_budget(message: Message):
    await cmd_budget(message)


@router.message(Command("list"))
async def cmd_list(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    if not message.text:
        return
    tokens = message.text.split()[1:]
    filters = ctx._parse_filters(tokens)

    try:
        await _send_records_list(message, lang, filters, limit=ctx.settings.max_list_records)
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"Database error in list: {exc}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as exc:
        ctx.logger.exception(f"Unexpected error in list: {exc}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}")
        )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        async with ctx.get_session() as session:
            agg = ctx.AggregationService(session, message.from_user.id)  # type: ignore
            totals = await agg.totals()
            day_sum = await agg.totals(ctx.RecordFilter(date_from=today, date_to=today))
            week_sum = await agg.totals(ctx.RecordFilter(date_from=week_start, date_to=today))
            month_sum = await agg.totals(ctx.RecordFilter(date_from=month_start, date_to=today))
            avg = await agg.averages()
            max_exp = await agg.max_expense()
            month_details = await agg.detailed_stats(ctx.RecordFilter(date_from=month_start, date_to=today))

        avg_val = f"{avg:.2f}" if avg is not None else "0.00"
        max_val = f"{max_exp:.2f}" if max_exp is not None else "0.00"

        breakdown_lines = []
        if month_details.get("by_category"):
            breakdown_lines.append(
                {
                    "uk": "💸 Витрати за категоріями (місяць):",
                    "ru": "💸 Расходы по категориям (месяц):",
                    "en": "💸 Expenses by category (month):",
                }.get(lang, "")
            )
            for cat, details in sorted(month_details["by_category"].items(), key=lambda x: x[1]["total"], reverse=True):
                total = details["total"]
                category_label = localize_category(cat, lang) or cat
                breakdown_lines.append(f"  {category_label}: {total:.2f}")
                for item in details.get("items", []):
                    if item["subcategory"]:
                        subcategory_label = (
                            localize_subcategory(cat, item["subcategory"], lang) or item["subcategory"]
                        )
                        breakdown_lines.append(f"    └ {subcategory_label}: {item['amount']:.2f}")

        breakdown_text = "\n".join(breakdown_lines) if breakdown_lines else ""

        stats_text = (
            {
                "uk": (
                    "📊 Статистика\n"
                    f"💰 Баланс: {totals['balance']:.2f}\n"
                    f"🗓 Витрати сьогодні: {day_sum['expenses']:.2f}\n"
                    f"📆 За тиждень: {week_sum['expenses']:.2f}\n"
                    f"🗓 За місяць: {month_sum['expenses']:.2f}\n"
                    f"📉 Середня витрата: {avg_val}\n"
                    f"🏁 Макс. витрата: {max_val}"
                ),
                "ru": (
                    "📊 Статистика\n"
                    f"💰 Баланс: {totals['balance']:.2f}\n"
                    f"🗓 Расходы сегодня: {day_sum['expenses']:.2f}\n"
                    f"📆 За неделю: {week_sum['expenses']:.2f}\n"
                    f"🗓 За месяц: {month_sum['expenses']:.2f}\n"
                    f"📉 Средний расход: {avg_val}\n"
                    f"🏁 Макс. расход: {max_val}"
                ),
                "en": (
                    "📊 Stats\n"
                    f"💰 Balance: {totals['balance']:.2f}\n"
                    f"🗓 Expenses today: {day_sum['expenses']:.2f}\n"
                    f"📆 This week: {week_sum['expenses']:.2f}\n"
                    f"🗓 This month: {month_sum['expenses']:.2f}\n"
                    f"📉 Average expense: {avg_val}\n"
                    f"🏁 Max expense: {max_val}"
                ),
            }.get(lang, "")
        )

        if breakdown_text:
            stats_text += "\n\n" + breakdown_text

        await ctx._answer_chunked(message, stats_text)
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"Database error in stats: {exc}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as exc:
        ctx.logger.exception(f"Unexpected error in stats: {exc}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}")
        )


@router.message(Command("budget"))
async def cmd_budget(message: Message):
    lang = await ctx._get_user_language(message.from_user.id)  # type: ignore
    if not message.text:
        return
    parts = message.text.split()
    sub = parts[1] if len(parts) > 1 else None

    try:
        async with ctx.get_session() as session:
            agg = ctx.AggregationService(session, message.from_user.id)  # type: ignore

            if sub == "set":
                if len(parts) < 6:
                    await message.answer(
                        {
                            "uk": f"Формат: /budget set <plan_expense> <plan_income> <start={ctx.settings.date_format}> <end={ctx.settings.date_format}>",
                            "ru": f"Формат: /budget set <plan_expense> <plan_income> <start={ctx.settings.date_format}> <end={ctx.settings.date_format}>",
                            "en": f"Format: /budget set <plan_expense> <plan_income> <start={ctx.settings.date_format}> <end={ctx.settings.date_format}>",
                        }.get(lang, "")
                    )
                    return
                _, _, plan_expense, plan_income, start_raw, end_raw = parts[:6]
                try:
                    plan = ctx.BudgetPlanCreate(
                        planned_expense=Decimal(plan_expense),
                        planned_income=Decimal(plan_income),
                        period_start=ctx._parse_date(start_raw),
                        period_end=ctx._parse_date(end_raw),
                    )
                except (InvalidOperation, ValueError, ValidationError) as exc:
                    ctx.logger.exception(f"Input error in budget set: {exc}")
                    await message.answer(
                        {
                            "uk": f"⚠️ Помилка вводу: {exc}",
                            "ru": f"⚠️ Ошибка ввода: {exc}",
                            "en": f"⚠️ Input error: {exc}",
                        }.get(lang, f"⚠️ Input error: {exc}")
                    )
                    return

                await agg.save_budget(plan)
                await session.commit()
                ctx.clear_stats_cache()
                status = await agg.budget_status(plan)
                await message.answer(
                    {
                        "uk": (
                            f"🧾 Бюджет збережено.\nПлан: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Витрачено: {status['spent']} | ✅ Залишилось: {status['remaining']}"
                        ),
                        "ru": (
                            f"🧾 Бюджет сохранен.\nПлан: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Потрачено: {status['spent']} | ✅ Осталось: {status['remaining']}"
                        ),
                        "en": (
                            f"🧾 Budget saved.\nPlan: {plan.planned_expense} | {plan.period_start} - {plan.period_end}\n"
                            f"💸 Spent: {status['spent']} | ✅ Remaining: {status['remaining']}"
                        ),
                    }.get(lang, "")
                )
                return

            last = await agg.last_budget()
            await session.commit()
            if not last:
                plan = await agg.simple_budget_suggestion()
                await agg.save_budget(plan)
                await session.commit()
                ctx.clear_stats_cache()
                status = await agg.budget_status(plan)
                await message.answer(
                    {
                        "uk": (
                            "📑 Створив базовий місячний бюджет.\n"
                            f"💰 План витрат: {plan.planned_expense:.2f}\n"
                            f"✅ Залишилось: {status['remaining']:.2f}"
                        ),
                        "ru": (
                            "📑 Создал базовый месячный бюджет.\n"
                            f"💰 План расходов: {plan.planned_expense:.2f}\n"
                            f"✅ Осталось: {status['remaining']:.2f}"
                        ),
                        "en": (
                            "📑 Created a basic monthly budget.\n"
                            f"💰 Expense plan: {plan.planned_expense:.2f}\n"
                            f"✅ Remaining: {status['remaining']:.2f}"
                        ),
                    }.get(lang, "")
                )
                return

            plan = ctx.BudgetPlanCreate(
                planned_expense=last.planned_expense,
                planned_income=last.planned_income,
                period_start=last.period_start,
                period_end=last.period_end,
            )
            status = await agg.budget_status(plan)
            await message.answer(
                {
                    "uk": (
                        f"📊 Поточний бюджет {plan.period_start} - {plan.period_end}\n"
                        f"План: {plan.planned_expense} | 💸 Витрачено: {status['spent']} | ✅ Залишилось: {status['remaining']} ({status['used_percent']}%)"
                    ),
                    "ru": (
                        f"📊 Текущий бюджет {plan.period_start} - {plan.period_end}\n"
                        f"План: {plan.planned_expense} | 💸 Потрачено: {status['spent']} | ✅ Осталось: {status['remaining']} ({status['used_percent']}%)"
                    ),
                    "en": (
                        f"📊 Current budget {plan.period_start} - {plan.period_end}\n"
                        f"Plan: {plan.planned_expense} | 💸 Spent: {status['spent']} | ✅ Remaining: {status['remaining']} ({status['used_percent']}%)"
                    ),
                }.get(lang, "")
            )
    except SQLAlchemyError as exc:
        ctx.logger.exception(f"Database error in budget: {exc}")
        await message.answer(
            {
                "uk": "❌ Помилка бази даних. Спробуйте пізніше.",
                "ru": "❌ Ошибка базы данных. Попробуйте позже.",
                "en": "❌ Database error. Try later.",
            }.get(lang, "❌ Database error.")
        )
    except Exception as exc:
        ctx.logger.exception(f"Unexpected error in budget: {exc}")
        await message.answer(
            {
                "uk": f"❌ Помилка: {exc}",
                "ru": f"❌ Ошибка: {exc}",
                "en": f"❌ Error: {exc}",
            }.get(lang, f"❌ Error: {exc}")
        )
