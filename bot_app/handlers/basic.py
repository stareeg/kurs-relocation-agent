"""Базовые команды бота: /cost и fallback на нераспознанный текст.

/start и /help — в menu.router. При BOT_PRIVATE_ONLY=true апдейты из групп
отрезает middleware, поэтому фолбэк-регистрации start/help здесь не нужны.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot_app.api_client import CopilotApiClient
from bot_app.filters import IsAdmin
from bot_app.utils import esc

router = Router(name="basic")

_FALLBACK_HINT = "Не понял. Пересылай вакансию или HR-переписку, остальное — в меню ниже"


@router.message(IsAdmin(), Command("cost"))
async def cmd_cost(message: Message, api_client: CopilotApiClient) -> None:
    try:
        metrics = await api_client.metrics()
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Метрики недоступны: {esc(str(exc))}")
        return

    today = float(metrics.get("today_cost_usd") or 0.0)
    total = float(metrics.get("total_cost_usd") or 0.0)
    lines = [f"Сегодня: ${today:.2f}", f"Всего: ${total:.2f}"]
    for row in metrics.get("usage_by_agent") or []:
        lines.append(f"- {esc(str(row.get('agent')))}: ${float(row.get('cost_usd') or 0):.2f}")
    await message.answer("\n".join(lines))


@router.message(IsAdmin(), F.text & ~F.text.startswith("/"))
async def fallback(message: Message) -> None:
    """Нераспознанный текст — фиксированная подсказка + живое меню (без LLM)."""
    await message.answer(_FALLBACK_HINT)
    from bot_app.services.menu_manager import idle, show_menu_for

    await show_menu_for(message, idle())
