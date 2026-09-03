"""Kill switch автооткликов (Фаза 7.4): `/pause_autoapply` — мгновенно `enabled=False` везде.

Не через inline-меню — команда для случая «что-то пошло не так», набирается руками с
телефона, без захода в «Расширение» и правки каждой площадки отдельно. Доступна любому
активному аккаунту (`IsAccount`), не только оператору: конфиг автооткликов per-account, у
каждого свой. Один сценарий с веб-тумблером (`core.app.scenarios.auto_apply.pause_all`).
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot_app.access import resolve_account
from bot_app.filters import IsAccount
from core.app.scenarios.auto_apply import pause_all

logger = logging.getLogger(__name__)
router = Router(name="auto_apply")


@router.message(IsAccount(), Command("pause_autoapply"))
async def cmd_pause_autoapply(message: Message) -> None:
    if message.from_user is None:
        return
    account = await resolve_account(user_id=message.from_user.id)
    if account is None:
        return
    await pause_all(account_id=account.id)
    await message.answer(
        "Автоотклики остановлены на всех площадках (hh.ru, getmatch, Habr Карьера). "
        "Включить обратно — в «Расширении» на сайте."
    )
