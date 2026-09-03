"""`/outreach` (HR-first контакт) должен ставить тот же фоновый хвост, что уже есть у
`/messages` и `/import` — извлечение события/предложение статуса воронки по HR-тексту
(`on_incoming_hr_message`). До этого фикса первый контакт из HR-first сценария не запускал
`extract_event`/`suggest_funnel_from_dialog` вовсе (см. план local_context_blind_spots §3,
подтверждённый кейс — job 323, МТС: HR подтвердил звонок в самом первом сообщении, но
`interview_stages` осталась пустой).
"""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks

from api.routers.assistant import conversations as router_module
from api.schemas import ConversationOutreachRequest
from api.security import AccountContext
from core.app.scenarios.conversations import ConversationView, OutreachResult
from core.domains.pipeline.hr_threads import HrThread


def _account() -> AccountContext:
    return AccountContext(account_id=7, telegram_user_id=1, telegram_username=None, role="owner")


def _outreach_result(vacancy_id: str = "tg_web_abc") -> OutreachResult:
    thread = HrThread(id=1, vacancy_id=vacancy_id, company="ООО Ромашка")
    return OutreachResult(
        vacancy_id=vacancy_id,
        scored=False,
        conversation=ConversationView(vacancy_id=vacancy_id, thread=thread),
    )


async def test_outreach_with_initial_text_queues_hr_message_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_outreach(**_kwargs: object) -> OutreachResult:
        return _outreach_result()

    monkeypatch.setattr(router_module, "create_outreach", fake_create_outreach)

    background = BackgroundTasks()
    body = ConversationOutreachRequest(initial_text="Здравствуйте! Расскажите о себе.")
    await router_module.conversation_outreach(body, background, account=_account())

    assert len(background.tasks) == 1
    task = background.tasks[0]
    assert task.func is router_module.on_incoming_hr_message
    assert task.args == ("tg_web_abc", "outreach")
    assert task.kwargs == {"account_id": 7}


async def test_outreach_without_initial_text_does_not_queue_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_outreach(**_kwargs: object) -> OutreachResult:
        return _outreach_result()

    monkeypatch.setattr(router_module, "create_outreach", fake_create_outreach)

    background = BackgroundTasks()
    body = ConversationOutreachRequest(company="ООО Ромашка", position="Аналитик")
    await router_module.conversation_outreach(body, background, account=_account())

    assert background.tasks == []
